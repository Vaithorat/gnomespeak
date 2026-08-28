"""One-tap shortcuts to streaming services.

App first, browser second. Several of these ship a desktop app on some
machines and nothing at all on others, and which one a given machine has is
not something the person on the couch should have to remember -- so the target
resolves it at snapshot time and says which route it will take.

The default list is overridable from ~/.config/gnomespeak/streaming.toml:

    [[service]]
    id = "jellyfin"
    label = "Jellyfin"
    url = "http://nas.local:8096"
    app = "jellyfinmediaplayer"    # optional

    [[service]]
    id = "twitch"
    enabled = false                # hide one of the defaults
"""

import os
import shutil
import subprocess
from pathlib import Path

from vt.model import Target, Action

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python < 3.11

# `app` holds the fragments that identify the service's desktop app: a .desktop
# id, or an executable name. Matched case-insensitively against both.
_DEFAULTS = [
    {"id": "netflix", "label": "Netflix", "url": "https://www.netflix.com", "app": ["netflix"], "icon": "🍿"},
    {"id": "youtube", "label": "YouTube", "url": "https://www.youtube.com", "app": [], "icon": "▶"},
    {"id": "spotify", "label": "Spotify", "url": "https://open.spotify.com", "app": ["spotify"], "icon": "🎵"},
    {"id": "primevideo", "label": "Prime Video", "url": "https://www.primevideo.com", "app": [], "icon": "📺"},
    {"id": "disneyplus", "label": "Disney+", "url": "https://www.disneyplus.com", "app": ["disney"], "icon": "🏰"},
    {"id": "hotstar", "label": "JioHotstar", "url": "https://www.hotstar.com", "app": [], "icon": "⭐"},
    {"id": "twitch", "label": "Twitch", "url": "https://www.twitch.tv", "app": ["twitch"], "icon": "🎮"},
    {"id": "max", "label": "Max", "url": "https://play.max.com", "app": [], "icon": "🎬"},
]


def _config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "gnomespeak" / "streaming.toml"


def services() -> list[dict]:
    """The service list: defaults, with the config file layered over them.

    A config entry sharing an id with a default replaces it, so a URL can be
    pointed at a regional domain without redefining everything else.
    """
    merged = {s["id"]: dict(s) for s in _DEFAULTS}

    path = _config_path()
    if path.exists():
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            data = {}
        for entry in data.get("service", []):
            sid = str(entry.get("id") or "").strip()
            if not sid:
                continue
            base = merged.get(sid, {"id": sid, "label": sid.title(), "url": "", "app": [], "icon": "📺"})
            if entry.get("enabled") is False:
                merged.pop(sid, None)
                continue
            app = entry.get("app", base.get("app") or [])
            base.update({
                "label": str(entry.get("label") or base.get("label") or sid.title()),
                "url": str(entry.get("url") or base.get("url") or ""),
                "app": [app] if isinstance(app, str) else list(app),
                "icon": str(entry.get("icon") or base.get("icon") or "📺"),
            })
            merged[sid] = base

    return [s for s in merged.values() if s.get("url") or s.get("app")]


def _find_app(service: dict) -> dict | None:
    """The installed desktop entry for a service, or None.

    Reuses the application index rather than scanning .desktop files again --
    it is already built and TTL-cached for the app search.
    """
    fragments = [f.casefold() for f in service.get("app") or []]
    if not fragments:
        return None

    try:
        from vt.sources.apps import get_installed_index
        index = get_installed_index()
    except Exception:
        return None

    for entry in index.values():
        haystack = f"{entry.get('id', '')} {entry.get('binary', '')} {entry.get('name', '')}".casefold()
        if any(fragment in haystack for fragment in fragments):
            return entry
    return None


def _find_binary(service: dict) -> str:
    for fragment in service.get("app") or []:
        found = shutil.which(fragment)
        if found:
            return found
    return ""


def get_streaming_targets() -> list[Target]:
    """One target per streaming service, labelled with how it will open."""
    targets = []
    for service in services():
        has_app = _find_app(service) is not None or bool(_find_binary(service))
        if not has_app and not service.get("url"):
            continue
        targets.append(Target(
            id=f"streaming:{service['id']}",
            kind="streaming",
            title=service["label"],
            subtitle="app" if has_app else "browser",
            icon=service.get("icon") or "📺",
            status="installed" if has_app else "web",
            actions=[Action(id="launch", label="Open")],
        ))
    return targets


def _open_url(url: str, label: str) -> dict:
    try:
        subprocess.run(
            ["xdg-open", url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return {"ok": True, "message": f"Opened {label} in the browser"}
    except FileNotFoundError:
        return {"ok": False, "message": "xdg-open not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Timeout opening browser"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def execute(service_id: str, action_id: str) -> dict:
    """Open a streaming service, preferring its desktop app over the web."""
    if action_id not in ("launch", "open"):
        return {"ok": False, "message": f"Unknown streaming action: {action_id}"}

    service = next((s for s in services() if s["id"] == service_id), None)
    if service is None:
        return {"ok": False, "message": f"No streaming service named {service_id}"}

    entry = _find_app(service)
    if entry is not None:
        # launch_entry applies the desktop file's own semantics; re-implementing
        # them here is how Terminal=true and DBusActivatable entries break.
        from vt.actions import launch_entry
        result = launch_entry(entry)
        if result["ok"]:
            return result
        # A desktop entry that refuses to start is not a reason to give up when
        # the same thing is one URL away.

    binary = _find_binary(service)
    if binary:
        try:
            subprocess.Popen(
                [binary],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                cwd=str(Path.home()),
            )
            return {"ok": True, "message": f"Launched {service['label']}"}
        except Exception:
            pass

    if service.get("url"):
        return _open_url(service["url"], service["label"])
    return {"ok": False, "message": f"{service['label']} is not installed and has no URL"}
