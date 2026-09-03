"""Set the desktop background to a picture the phone just sent.

The share sheet already lands a photo in the transfer folder, and one more tap
is the difference between "the picture is on the PC somewhere" and "the picture
is on the PC". GNOME keeps the background in GSettings, so this is two keys --
the light one and the dark one, because setting only one leaves the wallpaper
changing back when the theme does.

The path is checked twice over: it must be a file the transfer folder resolved,
and its first bytes must be an actual image. GSettings would happily accept a
URI pointing at anything at all, and a background that silently fails to load
looks exactly like the feature not working.
"""

import subprocess
from pathlib import Path

from vt.sources.art import sniff

SCHEMA = "org.gnome.desktop.background"
KEYS = ("picture-uri", "picture-uri-dark")

_TIMEOUT = 3


def current() -> str:
    """The wallpaper URI GNOME is using, or "" when it cannot be read."""
    try:
        result = subprocess.run(
            ["gsettings", "get", SCHEMA, KEYS[0]],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip().strip("'")


def is_image(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return bool(sniff(handle.read(16)))
    except OSError:
        return False


def set_from(path) -> dict:
    """Use `path` as the desktop background. Returns the usual result dict."""
    path = Path(path)
    if not path.is_file():
        return {"ok": False, "message": "That file is not there any more"}
    if not is_image(path):
        return {"ok": False, "message": f"{path.name} is not an image"}

    uri = path.resolve().as_uri()
    for key in KEYS:
        try:
            result = subprocess.run(
                ["gsettings", "set", SCHEMA, key, uri],
                capture_output=True, text=True, timeout=_TIMEOUT,
            )
        except FileNotFoundError:
            return {"ok": False, "message": "gsettings not found (install glib2 tools)"}
        except Exception as e:
            return {"ok": False, "message": f"Error: {e}"}
        if result.returncode != 0:
            return {"ok": False, "message": (result.stderr or "gsettings refused it").strip()}
    return {"ok": True, "message": f"Wallpaper set to {path.name}"}
