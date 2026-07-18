import asyncio
import platform
from pathlib import Path
from handlers.file_ops import FileOps
from handlers.app_launcher import AppLauncher
from handlers.email_sender import EmailSender
from handlers.browser_control import BrowserControl
from handlers.bluetooth_control import BluetoothControl
from handlers.media_player import MediaPlayer
from handlers.media_control import MediaControl
from safety import SafetyChecker
from env_model import EnvironmentModel


class CommandExecutor:
    def __init__(self, config):
        self.config = config
        self.env_model = EnvironmentModel()
        self.file_ops = FileOps()
        self.app_launcher = AppLauncher(env_model=self.env_model)
        self.email_sender = EmailSender(config)
        self.browser = BrowserControl()
        self.bluetooth = BluetoothControl()
        self.media_player = MediaPlayer()
        self.media_control = MediaControl()
        self.safety = SafetyChecker()

    async def initialize(self):
        await self.env_model.initialize()

    async def execute(self, command: dict) -> dict:
        action = command.get("action", "")
        params = command.get("params", {})
        return await self.execute_tool(action, params)

    async def execute_tool(self, name: str, args: dict, ask_callback=None) -> dict:
        if name == "open_app":
            args = dict(args)
            resolved_path = self.app_launcher.resolve_cached(args.get("name", "")) or ""
            if not resolved_path:
                resolved_path = await asyncio.to_thread(
                    self.app_launcher.find_app, args.get("name", "")
                ) or ""
            args["_resolved_path"] = resolved_path

        blocked = await self.safety.check(name, args, ask_callback)
        if blocked is not None:
            return blocked

        if name == "navigate":
            result = await asyncio.to_thread(self.file_ops.navigate, args.get("path", ""))
        elif name == "list_dir":
            result = await asyncio.to_thread(self.file_ops.list_dir, args.get("path", "."))
        elif name == "open_app":
            result = await asyncio.to_thread(
                self.app_launcher.launch,
                args.get("name", ""),
                args.get("_resolved_path", ""),
            )
        elif name == "create_file":
            result = await asyncio.to_thread(
                self.file_ops.create_file, args.get("path", ""), args.get("content", "")
            )
            if result.get("success"):
                await self.env_model.refresh_folder(str(
                    Path(args.get("path", "")).parent
                ))
        elif name == "create_folder":
            result = await asyncio.to_thread(self.file_ops.create_folder, args.get("path", ""))
            if result.get("success"):
                await self.env_model.refresh_folder(str(
                    Path(args.get("path", "")).parent
                ))
        elif name == "delete":
            result = await asyncio.to_thread(self.file_ops.delete, args.get("path", ""))
            if result.get("success"):
                await self.env_model.refresh_folder(str(
                    Path(args.get("path", "")).parent
                ))
        elif name == "copy":
            result = await asyncio.to_thread(
                self.file_ops.copy, args.get("source", ""), args.get("destination", "")
            )
            if result.get("success"):
                await self.env_model.refresh_folder(str(
                    Path(args.get("destination", "")).parent
                ))
        elif name == "move":
            result = await asyncio.to_thread(
                self.file_ops.move, args.get("source", ""), args.get("destination", "")
            )
            if result.get("success"):
                await self.env_model.refresh_folder(str(
                    Path(args.get("source", "")).parent
                ))
                await self.env_model.refresh_folder(str(
                    Path(args.get("destination", "")).parent
                ))
        elif name == "send_email":
            result = await asyncio.wait_for(asyncio.to_thread(
                self.email_sender.send,
                args.get("to", ""),
                args.get("subject", "No Subject"),
                args.get("body", ""),
            ), timeout=30)
        elif name in ("browser_navigate", "open_url"):
            result = await self.browser.navigate(args.get("url", ""))
        elif name == "browser_search":
            result = await self.browser.search_web(
                args.get("query", ""), args.get("engine", "google")
            )
        elif name == "yt_play":
            result = await self.browser.yt_play_first(args.get("query", ""))
        elif name == "yt_play_first_result":
            result = await self.browser.yt_play_first_result()
        elif name == "yt_search":
            result = await self.browser.yt_search(args.get("query", ""))
        elif name == "yt_results":
            result = await self.browser.yt_results(args.get("query", ""))
        elif name == "control_bluetooth":
            result = await asyncio.to_thread(self.bluetooth.execute, args)
        elif name == "play_media":
            result = await asyncio.to_thread(self.media_player.play_local, args.get("query", ""))
        elif name == "volume_up":
            result = await asyncio.to_thread(self.media_player.volume_up)
        elif name == "volume_down":
            result = await asyncio.to_thread(self.media_player.volume_down)
        elif name == "volume_mute":
            result = await asyncio.to_thread(self.media_player.volume_mute)
        elif name == "set_volume":
            try:
                level = int(args.get("level", 50))
            except (ValueError, TypeError):
                level = 50
            result = await asyncio.to_thread(self.media_player.set_volume, level)
        elif name == "get_system_info":
            result = await asyncio.to_thread(self._get_system_info)
        elif name == "media_control":
            result = await asyncio.to_thread(self.media_control.execute, args.get("action", "play_pause"))
        else:
            result = {"success": False, "message": f"Unknown tool: {name}"}

        return result

    def _get_system_info(self) -> dict:
        info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
        }
        bt = self.bluetooth.status()
        info["bluetooth"] = bt.get("message", "unknown")
        return {"success": True, "message": "System info retrieved", "info": info}
