import platform
from handlers.file_ops import FileOps
from handlers.app_launcher import AppLauncher
from handlers.email_sender import EmailSender
from handlers.browser_control import BrowserControl
from handlers.bluetooth_control import BluetoothControl
from handlers.media_player import MediaPlayer


class CommandExecutor:
    def __init__(self, config):
        self.file_ops = FileOps()
        self.app_launcher = AppLauncher()
        self.email_sender = EmailSender(config)
        self.browser = BrowserControl()
        self.bluetooth = BluetoothControl()
        self.media_player = MediaPlayer()

    def execute(self, command: dict) -> dict:
        action = command.get("action", "")
        params = command.get("params", {})
        return self.execute_tool(action, params)

    def execute_tool(self, name: str, args: dict) -> dict:
        if name == "navigate":
            return self.file_ops.navigate(args.get("path", ""))
        elif name == "list_dir":
            return self.file_ops.list_dir(args.get("path", "."))
        elif name == "open_app":
            return self.app_launcher.launch(args.get("name", ""))
        elif name == "create_file":
            return self.file_ops.create_file(
                args.get("path", ""), args.get("content", "")
            )
        elif name == "create_folder":
            return self.file_ops.create_folder(args.get("path", ""))
        elif name == "delete":
            return self.file_ops.delete(args.get("path", ""))
        elif name == "copy":
            return self.file_ops.copy(
                args.get("source", ""), args.get("destination", "")
            )
        elif name == "move":
            return self.file_ops.move(
                args.get("source", ""), args.get("destination", "")
            )
        elif name == "send_email":
            return self.email_sender.send(
                args.get("to", ""),
                args.get("subject", "No Subject"),
                args.get("body", ""),
            )
        elif name in ("browser_navigate", "open_url"):
            return self.browser.navigate(args.get("url", ""))
        elif name == "browser_search":
            return self.browser.search_web(
                args.get("query", ""), args.get("engine", "google")
            )
        elif name == "yt_play":
            return self.browser.yt_play_first(args.get("query", ""))
        elif name == "control_bluetooth":
            return self.bluetooth.execute(args)
        elif name == "play_media":
            return self.media_player.play_local(args.get("query", ""))
        elif name == "volume_up":
            return self.media_player.volume_up()
        elif name == "volume_down":
            return self.media_player.volume_down()
        elif name == "volume_mute":
            return self.media_player.volume_mute()
        elif name == "set_volume":
            return self.media_player.set_volume(int(args.get("level", 50)))
        elif name == "get_system_info":
            return self._get_system_info()
        else:
            return {
                "success": False,
                "message": f"Unknown tool: {name}",
            }

    def _get_system_info(self) -> dict:
        info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
        }
        bt = self.bluetooth.status()
        info["bluetooth"] = bt.get("message", "unknown")
        return {"success": True, "message": "System info retrieved", "info": info}
