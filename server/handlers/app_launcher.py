import subprocess
import os
from pathlib import Path


class AppLauncher:
    def __init__(self):
        self.start_menu_dirs = self._get_start_menu_dirs()
        self.common_dirs = [
            Path("C:\\Program Files"),
            Path("C:\\Program Files (x86)"),
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
        ]

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
        name_lower = name.lower()

        for start_dir in self.start_menu_dirs:
            if not start_dir.exists():
                continue
            for candidate in start_dir.rglob("*.lnk"):
                if name_lower in candidate.stem.lower():
                    return str(candidate)
            for candidate in start_dir.rglob("*.exe"):
                if name_lower in candidate.stem.lower():
                    return str(candidate)

        for common_dir in self.common_dirs:
            if not common_dir.exists():
                continue
            for candidate in common_dir.rglob("*.exe"):
                if name_lower in candidate.stem.lower():
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

    def launch(self, name: str) -> dict:
        name = name.strip().strip('"').strip("'")
        exe_path = self.find_app(name)

        if exe_path:
            try:
                subprocess.Popen([exe_path], shell=False)
                return {"success": True, "message": f"Opened {name}"}
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Failed to open {name}: {str(e)}",
                }

        try:
            subprocess.Popen(["cmd", "/c", "start", "", name], shell=True)
            return {"success": True, "message": f"Attempted to open {name}"}
        except Exception as e:
            return {
                "success": False,
                "message": f"Could not open {name}: {str(e)}",
            }
