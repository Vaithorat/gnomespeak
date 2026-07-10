#!/usr/bin/env python3
import asyncio
import json
import sys
import signal
import time
from pathlib import Path
import websockets

from config import Config
from auth import Auth
from intent_parser import IntentParser
from command_executor import CommandExecutor


class VoiceTalkServer:
    def __init__(self, config_path="config.json"):
        self.config = Config(config_path)
        self.auth = Auth()
        self.intent_parser = None
        self.executor = None
        self._ws = None
        self._pending_questions: dict[str, asyncio.Future] = {}
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda s, f: sys.exit(0))
            except (ValueError, AttributeError):
                pass

    def setup(self, master_password: str):
        self.config.unlock(master_password)
        self.intent_parser = IntentParser(self.config)
        self.executor = CommandExecutor(self.config)

    async def _send_question(
        self, message: str, options: list[str] | None = None
    ) -> dict:
        q_id = f"q_{int(time.time() * 1000)}_{id(self._ws)}"
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_questions[q_id] = future
        payload = {
            "type": "question",
            "id": q_id,
            "message": message,
            "options": options or [],
        }
        await self._ws.send(json.dumps(payload))
        try:
            answer = await asyncio.wait_for(future, timeout=60)
            return {"success": True, "text": answer}
        except asyncio.TimeoutError:
            self._pending_questions.pop(q_id, None)
            return {"success": False, "message": "No answer received within 60s"}

    async def handle_client(self, websocket):
        self._ws = websocket
        async for raw in websocket:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await self._send_result(websocket, False, "Invalid JSON")
                continue

            msg_type = data.get("type")
            if msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
                continue

            if msg_type == "answer":
                await self._handle_answer(data)
                continue

            if msg_type != "command":
                await self._send_result(websocket, False, "Unknown message type")
                continue

            api_key = data.get("api_key", "")
            if not self.auth.validate(api_key):
                await self._send_result(websocket, False, "Invalid API key")
                continue

            text = data.get("text", "").strip()
            if not text:
                await self._send_result(websocket, False, "Empty command")
                continue

            ask_callback = (
                lambda q, opts: self._send_question(q, opts)
            )
            result = await self.intent_parser.parse(
                text, executor=self.executor, ask_callback=ask_callback
            )
            result["type"] = "result"
            await websocket.send(json.dumps(result))

    async def _handle_answer(self, data: dict):
        q_id = data.get("id", "")
        text = data.get("text", "")
        future = self._pending_questions.pop(q_id, None)
        if future and not future.done():
            future.set_result(text)

    async def _send_result(self, websocket, success: bool, message: str):
        await websocket.send(
            json.dumps(
                {
                    "type": "result",
                    "success": success,
                    "message": message,
                }
            )
        )

    async def run_async(self):
        async with websockets.serve(
            self.handle_client,
            self.config.host,
            self.config.port,
            ping_interval=30,
            ping_timeout=10,
        ):
            print(
                f"VoiceTalk server running on ws://{self.config.host}:{self.config.port}"
            )
            print("Press Ctrl+C to stop.")
            await asyncio.Future()

    def run(self):
        asyncio.run(self.run_async())


def prompt_setup(server: VoiceTalkServer):
    print("VoiceTalk Server Setup")
    print("======================")

    if not server.config.get_secret("openai_api_key"):
        print("\nFirst-time setup detected.")

        api_key = input("Enter your OpenAI API key (sk-...): ").strip()
        while not api_key.startswith("sk-"):
            api_key = input(
                "Invalid key. Enter your OpenAI API key (sk-...): "
            ).strip()
        server.config.set_secret("openai_api_key", api_key)

        if input("\nConfigure email? (y/N): ").strip().lower() == "y":
            server.config.set_secret(
                "smtp_server",
                (
                    input("SMTP server [smtp.gmail.com]: ").strip()
                    or "smtp.gmail.com"
                ),
            )
            server.config.set_secret(
                "smtp_port",
                input("SMTP port [587]: ").strip() or "587",
            )
            server.config.set_secret(
                "smtp_username",
                input("SMTP username: ").strip(),
            )
            server.config.set_secret(
                "smtp_password",
                input("SMTP password: ").strip(),
            )

        server.config.save()
        print("\nConfiguration saved.\n")


if __name__ == "__main__":
    server = VoiceTalkServer()

    if len(sys.argv) > 1:
        master_password = sys.argv[1]
    else:
        import getpass

        master_password = getpass.getpass("Enter master password: ").strip()

    if not master_password:
        print("Master password is required.")
        sys.exit(1)

    try:
        server.setup(master_password)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    prompt_setup(server)
    try:
        server.run()
    except KeyboardInterrupt:
        print("\nShutting down.")
