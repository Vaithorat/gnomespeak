"""Installed Steam games, read from Steam's own library manifests.

Steam only writes .desktop files for games the user explicitly asks for a
shortcut to, so the ordinary application index (sources/apps.py) sees almost
none of them. The library manifests are the real list, and they are plain VDF
text sitting next to the games themselves.

Launching goes through the steam://rungameid/ URL rather than a Steam
command line, because that is the one entry point that behaves identically for
native builds, Proton builds, and a Steam client that is not running yet.
"""

import re
import subprocess
import time
from pathlib import Path

from vt.model import Target, Action

# Where the Steam client keeps its root, in the order worth trying: the
# traditional symlink, the flatpak sandbox, then the raw data directory.
_STEAM_ROOTS = (
    "~/.steam/steam",
    "~/.local/share/Steam",
    "~/.var/app/com.valvesoftware.Steam/data/Steam",
    "~/.steam/debian-installation",
)

# VDF is a nested key/value format. Every field this module needs is a flat
# "key" "value" pair on its own line, so a full parser buys nothing.
_KV = re.compile(r'^\s*"([^"]+)"\s+"([^"]*)"\s*$')

# StateFlags is a bitfield; bit 2 (value 4) is "fully installed". Without this
# a half-downloaded game shows up as launchable and fails on tap.
_STATE_FULLY_INSTALLED = 4

# Runtimes and redistributables are installed like games and are not games.
_NOT_GAMES = (
    "steam linux runtime",
    "proton",
    "steamworks common redistributables",
    "steam controller configs",
)

_INDEX_TTL = 60.0
_cache: dict = {"at": -1.0, "value": []}


def _parse_kv(path: Path) -> dict:
    """Every flat "key" "value" pair in a VDF file. Later keys win."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return values
    for line in text.splitlines():
        match = _KV.match(line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def steam_root() -> Path | None:
    """The Steam installation directory, or None when Steam is not installed."""
    for candidate in _STEAM_ROOTS:
        path = Path(candidate).expanduser()
        if (path / "steamapps").is_dir():
            return path
    return None


def _library_dirs(root: Path) -> list[Path]:
    """Every steamapps directory Steam knows about, including extra drives.

    libraryfolders.vdf lists one "path" per library. Its own steamapps is
    always a library and is not always listed, so it goes in unconditionally.
    """
    dirs = [root / "steamapps"]

    manifest = root / "steamapps" / "libraryfolders.vdf"
    try:
        text = manifest.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return dirs

    for line in text.splitlines():
        match = _KV.match(line)
        if not match or match.group(1) != "path":
            continue
        library = Path(match.group(2)) / "steamapps"
        if library.is_dir() and library not in dirs:
            dirs.append(library)
    return dirs


def _is_game(name: str) -> bool:
    lowered = name.casefold()
    return not any(lowered.startswith(prefix) for prefix in _NOT_GAMES)


def installed_games() -> list[dict]:
    """Installed games as {"id", "name"}, sorted by name.

    Cached: a library scan is a handful of small file reads, but the app search
    that calls this runs on every keystroke the user types on their phone.
    """
    now = time.monotonic()
    if _cache["at"] >= 0 and (now - _cache["at"]) < _INDEX_TTL:
        return _cache["value"]

    games: dict[str, dict] = {}
    root = steam_root()
    if root is not None:
        for library in _library_dirs(root):
            try:
                manifests = sorted(library.glob("appmanifest_*.acf"))
            except OSError:
                continue
            for manifest in manifests:
                fields = _parse_kv(manifest)
                appid = fields.get("appid", "").strip()
                name = fields.get("name", "").strip()
                if not appid or not name or not _is_game(name):
                    continue
                try:
                    if not int(fields.get("StateFlags", 0)) & _STATE_FULLY_INSTALLED:
                        continue
                except ValueError:
                    pass
                games[appid] = {"id": appid, "name": name}

    value = sorted(games.values(), key=lambda g: g["name"].casefold())
    _cache["at"] = now
    _cache["value"] = value
    return value


def reset_cache() -> None:
    """Drop the memoised library, so the next read rescans."""
    _cache["at"] = -1.0
    _cache["value"] = []


def get_steam_targets(query: str = "") -> list[Target]:
    """Installed games as launchable targets, optionally filtered by `query`.

    Deliberately absent from the 1 Hz snapshot for the same reason installed
    apps are: a large library would dwarf the state that actually changes.
    The server serves these through /api/apps alongside everything else.
    """
    tokens = [tok for tok in query.casefold().split() if tok]

    targets = []
    for game in installed_games():
        if tokens:
            haystack = f"{game['name']} steam".casefold()
            if not all(tok in haystack for tok in tokens):
                continue
        targets.append(Target(
            id=f"steam:{game['id']}",
            kind="steam",
            title=game["name"],
            subtitle="Steam",
            icon="🎮",
            status="installed",
            actions=[Action(id="launch", label="Launch")],
        ))
    return targets


def launch_game(appid: str) -> dict:
    """Start a game through Steam's own URL handler."""
    if not appid.isdigit():
        return {"ok": False, "message": f"Invalid Steam app id: {appid}"}

    name = next((g["name"] for g in installed_games() if g["id"] == appid), "")

    try:
        subprocess.run(
            ["xdg-open", f"steam://rungameid/{appid}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except FileNotFoundError:
        return {"ok": False, "message": "xdg-open not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Timed out handing the game to Steam"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}

    label = name or f"app {appid}"
    # Steam may still be starting, and it shows its own progress; claiming the
    # game is running would be a guess about something the user can see.
    return {"ok": True, "message": f"Asked Steam to launch {label}"}
