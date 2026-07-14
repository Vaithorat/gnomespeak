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
        self.shutdown_event = asyncio.Event()
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda s, f: self.shutdown_event.set())
            except (ValueError, AttributeError):
                pass

    def setup(self):
        self.config.auto_unlock()
        self.executor = CommandExecutor(self.config)
        self.intent_parser = IntentParser(self.config, env_model=self.executor.env_model)
        stored_key = self.config.get_secret("openai_api_key")
        if stored_key:
            print("Found stored API key in config")

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
            provider = data.get("provider", "")
            text = data.get("text", "").strip()
            session_id = data.get("session_id", "")

            if not text:
                await self._send_result(websocket, False, "Empty command")
                continue

            ask_callback = (
                lambda q, opts: self._send_question(q, opts)
            )

            await self.executor.env_model.refresh_if_stale()

            full_response = ""
            try:
                async for chunk in self.intent_parser.parse_stream(
                    text,
                    executor=self.executor,
                    ask_callback=ask_callback,
                    api_key=api_key,
                    provider=provider,
                    session_id=session_id or None,
                ):
                    if chunk["type"] == "chunk":
                        full_response += chunk["content"]
                        await websocket.send(json.dumps({
                            "type": "stream_chunk",
                            "content": chunk["content"],
                        }))
                    elif chunk["type"] == "tool_result":
                        pass
                    elif chunk["type"] == "final":
                        result = chunk["result"]
                        final_message = full_response if full_response else result.get("message", "")
                        await websocket.send(json.dumps({
                            "type": "stream_result",
                            "success": result.get("success", True),
                            "message": final_message,
                        }))
            except Exception as e:
                await websocket.send(json.dumps({
                    "type": "stream_result",
                    "success": False,
                    "message": f"Error: {str(e)}",
                }))

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
        self.shutdown_event.clear()
        await self.executor.initialize()
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
            await self.shutdown_event.wait()

    def run(self):
        asyncio.run(self.run_async())


def prompt_setup(server: VoiceTalkServer):
    return

    if not server.config.get_secret("smtp_server"):
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
    server.setup()
    prompt_setup(server)
    try:
        server.run()
    except KeyboardInterrupt:
        print("\nShutting down.")
