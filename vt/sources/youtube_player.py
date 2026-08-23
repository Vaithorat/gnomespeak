"""Keystroke-based playback control, for X11 sessions only.

This is a fallback, not the main path. Media playing in a browser is controlled
through MPRIS (`sources/mpris.py`): Firefox publishes a player for a YouTube tab
that reports its own capabilities, needs no extra tools, and works under
Wayland. Prefer it.

Keystroke injection exists for X11 sessions where a player publishes no MPRIS
interface at all. It cannot work on Wayland -- the compositor does not let one
client synthesise input for another, and xdotool is an X11 client. Offering
these buttons on a Wayland session would mean shipping controls that silently
do nothing, so `get_youtube_player_target()` returns None there.
"""

import os
import shutil
import subprocess
from vt.model import Target, Action

# YouTube's own keyboard shortcuts, which the page handles once it has focus.
_KEYS = {
    "play_pause": ["space"],
    "seek_back": ["Left", "Left"],    # YouTube seeks 5s per arrow
    "seek_fwd": ["Right", "Right"],
    "volume_down": ["Down"],
    "volume_up": ["Up"],
    "fullscreen": ["f"],
}


def is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def missing_tools() -> list[str]:
    """Which of the X11 tools this path needs are absent."""
    return [tool for tool in ("xdotool", "wmctrl") if not shutil.which(tool)]


def unavailable_reason() -> str:
    """Why keystroke control is not on offer, or "" when it is available."""
    if is_wayland():
        return (
            "Keystroke control needs X11; this is a Wayland session. Control "
            "browser playback through the MPRIS player instead -- it appears "
            "under Players while the tab is playing."
        )
    missing = missing_tools()
    if missing:
        return f"Keystroke control needs {' and '.join(missing)} (apt install {' '.join(missing)})."
    return ""


def find_youtube_window() -> dict | None:
    """Find a YouTube window through wmctrl, or None."""
    if not shutil.which("wmctrl"):
        return None
    try:
        result = subprocess.run(
            ["wmctrl", "-l"], capture_output=True, text=True, timeout=2
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            # "0x03400007  0 host Title of the window"
            parts = line.split(None, 3)
            if len(parts) < 4:
                continue
            title = parts[3]
            if "youtube" in title.lower():
                return {"id": parts[0], "name": title}
        return None
    except Exception:
        return None


def get_youtube_player_target() -> Target | None:
    """Keystroke controls for a YouTube window, when this session can deliver them."""
    if unavailable_reason():
        return None

    window = find_youtube_window()
    if not window:
        return None

    return Target(
        id="youtube:player",
        kind="youtube_player",
        title="YouTube (keys)",
        subtitle=window["name"][:50],
        icon="|>",
        status="playing",
        actions=[
            Action(id="play_pause", label="Play/Pause"),
            Action(id="seek_back", label="<- 10s"),
            Action(id="seek_fwd", label="10s ->"),
            Action(id="volume_down", label="Volume -"),
            Action(id="volume_up", label="Volume +"),
            Action(id="fullscreen", label="Fullscreen"),
            Action(id="close", label="Close", kind="confirm"),
        ],
    )


def send_keys(action_id: str) -> dict:
    """Focus the YouTube window, then send the keys for one action.

    Focusing first matters: xdotool sends to whatever holds focus, so without
    this the keystrokes land in whichever window the user last touched.
    """
    reason = unavailable_reason()
    if reason:
        return {"ok": False, "message": reason}

    keys = _KEYS.get(action_id)
    if not keys:
        return {"ok": False, "message": f"Unknown player action: {action_id}"}

    window = find_youtube_window()
    if not window:
        return {"ok": False, "message": "No YouTube window found"}

    try:
        subprocess.run(["wmctrl", "-ia", window["id"]], timeout=2, capture_output=True)
        for key in keys:
            subprocess.run(["xdotool", "key", key], timeout=2, capture_output=True)
        return {"ok": True, "message": f"Sent {' '.join(keys)}"}
    except FileNotFoundError as e:
        return {"ok": False, "message": f"Not found: {e.filename}"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Command timed out"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def close_youtube_window() -> dict:
    """Close the YouTube window through wmctrl."""
    if not shutil.which("wmctrl"):
        return {"ok": False, "message": "wmctrl not found (apt install wmctrl)"}

    window = find_youtube_window()
    if not window:
        return {"ok": False, "message": "No YouTube window found"}

    try:
        subprocess.run(["wmctrl", "-ic", window["id"]], timeout=2, capture_output=True)
        return {"ok": True, "message": "Closed YouTube"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Command timed out"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}
