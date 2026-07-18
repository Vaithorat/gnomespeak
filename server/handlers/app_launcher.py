import os
import subprocess
from pathlib import Path


class AppLauncher:
    def __init__(self, env_model=None):
        self.env_model = env_model
        self.start_menu_dirs = self._get_start_menu_dirs()
        self.common_dirs = [
            Path("C:\\Program Files"),
            Path("C:\\Program Files (x86)"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        ]
        self.aliases = {
            "browser": ["chrome", "firefox", "edge", "msedge", "brave", "opera", "vivaldi", "internet explorer", "iexplore"],
            "the browser": ["chrome", "firefox", "edge", "msedge", "brave", "opera", "vivaldi"],
            "music player": ["spotify", "wmplayer", "music", "groove music", "windows media player"],
            "video player": ["vlc", "movies & tv", "windows media player", "mpv"],
            "file explorer": ["explorer", "file explorer"],
            "explorer": ["explorer", "file explorer"],
            "terminal": ["cmd", "command prompt", "windows terminal", "powershell"],
            "command prompt": ["cmd", "command prompt"],
            "notepad": ["notepad"],
            "calculator": ["calc", "calculator"],
            "settings": ["ms-settings:", "settings"],
            "control panel": ["control", "control panel"],
            "task manager": ["taskmgr", "task manager"],
            "snipping tool": ["snippingtool", "snipping tool"],
            "paint": ["mspaint", "paint"],
            "word": ["winword", "word", "microsoft word"],
            "excel": ["excel", "microsoft excel"],
            "powershell": ["powershell", "pwsh"],
            "vs code": ["code", "visual studio code"],
            "vscode": ["code", "visual studio code"],
            "visual studio code": ["code", "visual studio code"],
            "discord": ["discord"],
            "spotify": ["spotify"],
            "steam": ["steam"],
            "whatsapp": ["whatsapp"],
            "telegram": ["telegram"],
            "slack": ["slack"],
        }

    def _get_start_menu_dirs(self):
        dirs = []
        progdata = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
        appdata = os.environ.get("APPDATA", "")
        dirs.append(
            Path(progdata)
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
        )
        if appdata:
            dirs.append(
                Path(appdata)
                / "Microsoft"
                / "Windows"
                / "Start Menu"
                / "Programs"
            )
        return dirs

    def find_app(self, name: str):
        name_lower = name.lower().strip()

        cached = self.resolve_cached(name_lower)
        if cached:
            return cached

        candidate_names = [name_lower]
        if name_lower in self.aliases:
            candidate_names = self.aliases[name_lower]

        if name_lower.startswith("the "):
            without_article = name_lower[4:]
            if without_article in self.aliases:
                candidate_names = self.aliases[without_article]
            else:
                candidate_names.append(without_article)

        if name_lower.startswith("a ") or name_lower.startswith("an "):
            without_article = name_lower.split(" ", 1)[1]
            if without_article in self.aliases:
                candidate_names = self.aliases[without_article]
            else:
                candidate_names.append(without_article)

        for try_name in candidate_names:
            result = self._search_with_powershell(try_name)
            if result:
                return result
            result = self._search_name(try_name)
            if result:
                return result
        return None

    def resolve_cached(self, name: str):
        name_lower = name.lower().strip()
        if self.env_model:
            cached = self.env_model.get_app_path(name_lower)
            if cached:
                return cached
        return None

    def _search_with_powershell(self, name: str):
        try:
            safe_name = name.replace("'", "''")
            ps_cmd = (
                f"Get-StartApps | Where-Object {{$_.Name -like '*{safe_name}*'}} "
                f"| Select-Object -First 1 -ExpandProperty AppId"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode == 0 and result.stdout.strip():
                app_id = result.stdout.strip()
                if os.path.exists(app_id):
                    return app_id
        except Exception:
            pass
        return None

    def _search_name(self, name: str):
        for start_dir in self.start_menu_dirs:
            if not start_dir.exists():
                continue
            for candidate in start_dir.rglob("*.lnk"):
                if name in candidate.stem.lower():
                    return str(candidate)
            for candidate in start_dir.rglob("*.exe"):
                if name in candidate.stem.lower():
                    return str(candidate)

        for common_dir in self.common_dirs:
            if not common_dir.exists():
                continue
            for candidate in common_dir.rglob("*.exe"):
                if name in candidate.stem.lower():
                    return str(candidate)

        path_exts = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(";")
        path_dirs = os.environ.get("PATH", "").split(";")
        for path_dir in path_dirs:
            if not path_dir:
                continue
            for ext in path_exts:
                candidate = Path(path_dir) / f"{name}{ext.lower()}"
                if candidate.exists():
                    return str(candidate)

        return None

    def launch(self, name: str, resolved_path: str = "") -> dict:
        name = name.strip().strip('"').strip("'")
        exe_path = resolved_path or self.find_app(name)

        if exe_path:
            try:
                os.startfile(exe_path)
                return {"success": True, "message": f"Opened {name}"}
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Failed to open {name}: {str(e)}",
                }

        return {
            "success": False,
            "message": f"App not found: {name}",
        }
