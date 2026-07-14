import asyncio
import os
import time
from pathlib import Path




class EnvironmentModel:
    def __init__(self):
        self.desktop_files: dict[str, dict] = {}
        self.installed_apps: dict[str, str] = {}
        self.recent_folders: dict[str, dict] = {}
        self._last_full_refresh: float = 0
        self._refresh_interval: float = 900
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        await self._full_refresh()
        self._initialized = True

    async def refresh_if_stale(self):
        if time.time() - self._last_full_refresh > self._refresh_interval:
            asyncio.create_task(self._full_refresh())

    async def _full_refresh(self):
        async with self._lock:
            await self._scan_desktop()
            await self._scan_installed_apps()
            self._last_full_refresh = time.time()

    async def refresh_folder(self, path: str):
        async with self._lock:
            try:
                p = Path(path)
                if not p.exists():
                    return
                info = self._folder_info(p)
                self.recent_folders[str(p)] = info
                if len(self.recent_folders) > 10:
                    oldest = list(self.recent_folders.keys())[0]
                    del self.recent_folders[oldest]
            except Exception:
                pass

    async def _scan_desktop(self):
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
        if not desktop.exists():
            return
        self.desktop_files = {}
        try:
            for item in desktop.iterdir():
                if item.name.startswith("."):
                    continue
                self.desktop_files[item.name] = {
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "extension": item.suffix.lower(),
                }
                if len(self.desktop_files) >= 200:
                    break
        except PermissionError:
            pass

    async def _scan_installed_apps(self):
        self.installed_apps = {}
        try:
            loop = asyncio.get_event_loop()
            apps = await loop.run_in_executor(None, self._get_start_apps)
            self.installed_apps = apps
        except Exception:
            await self._scan_apps_fallback()

    def _get_start_apps(self) -> dict[str, str]:
        apps = {}
        start_menu_dirs = []
        progdata = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
        appdata = os.environ.get("APPDATA", "")
        start_menu_dirs.append(
            Path(progdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        )
        if appdata:
            start_menu_dirs.append(
                Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            )

        for menu_dir in start_menu_dirs:
            if not menu_dir.exists():
                continue
            for link in menu_dir.rglob("*.lnk"):
                name = link.stem.lower()
                apps[name] = str(link)
            for exe in menu_dir.rglob("*.exe"):
                name = exe.stem.lower()
                if name not in apps:
                    apps[name] = str(exe)

        for cmd_name in ["notepad", "calc", "mspaint", "explorer", "cmd", "powershell"]:
            if cmd_name not in apps:
                apps[cmd_name] = cmd_name

        return apps

    async def _scan_apps_fallback(self):
        start_menu_dirs = []
        progdata = os.environ.get("PROGRAMDATA", "C:\\ProgramData")
        appdata = os.environ.get("APPDATA", "")
        start_menu_dirs.append(
            Path(progdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        )
        if appdata:
            start_menu_dirs.append(
                Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            )

        for menu_dir in start_menu_dirs:
            if not menu_dir.exists():
                continue
            try:
                for link in menu_dir.rglob("*.lnk"):
                    name = link.stem.lower()
                    self.installed_apps[name] = str(link)
                    if len(self.installed_apps) >= 500:
                        return
            except PermissionError:
                continue

    def _folder_info(self, path: Path) -> dict:
        items = []
        try:
            for item in path.iterdir():
                items.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                })
                if len(items) >= 100:
                    break
        except PermissionError:
            pass
        return {"path": str(path), "items": items}

    def get_app_path(self, name: str) -> str | None:
        name_lower = name.lower().strip()
        if name_lower in self.installed_apps:
            return self.installed_apps[name_lower]
        for app_name, path in self.installed_apps.items():
            if name_lower in app_name:
                return path
        return None

    def build_context_prompt(self) -> str:
        lines = ["## Current Environment"]

        if self.desktop_files:
            lines.append("\nDesktop files:")
            for name, info in list(self.desktop_files.items())[:30]:
                kind = "folder" if info["is_dir"] else info.get("extension", "file")
                lines.append(f"  - {name} ({kind})")

        if self.installed_apps:
            lines.append("\nInstalled apps (partial list):")
            sorted_apps = sorted(self.installed_apps.keys())
            for name in sorted_apps[:50]:
                lines.append(f"  - {name}")

        if self.recent_folders:
            lines.append("\nRecently accessed folders:")
            for path, info in self.recent_folders.items():
                item_count = len(info.get("items", []))
                lines.append(f"  - {path} ({item_count} items)")

        return "\n".join(lines)
