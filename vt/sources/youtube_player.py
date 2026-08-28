"""Keystroke-based playback control for a YouTube tab.

Two delivery routes, tried in that order:

1. The VoiceTalk GNOME extension. Under Wayland only the compositor may
   synthesise input, and an extension runs inside it -- so this is the only
   route that works there. It works under GNOME on X11 too, which is why it is
   tried first regardless of session type.
2. xdotool/wmctrl. The fallback for non-GNOME X11 sessions, where there is no
   extension to talk to. Silently ignored by Wayland, so it is never offered
   there.

This complements MPRIS (`sources/mpris.py`) rather than replacing it. MPRIS is
better for play/pause and track changes -- it reports its own capabilities and
needs no window focus -- but the protocol has no concept of fullscreen, volume
within the page, or YouTube's 10-second seek, so those can only be reached by
typing YouTube's own shortcuts at the page.
"""

import os
import shutil
import subprocess

from vt.model import Target, Action
from vt.sources.firefox import get_firefox_windows
from vt.sources.windows import (
    _is_browser,
    _match_session_window,
    _strip_browser_suffix,
    _tab_chord,
    list_windows,
    shell_interface,
)

try:
    import dbus
except ImportError:
    dbus = None

# YouTube's own keyboard shortcuts, which the page handles once it has focus.
# j/l are YouTube's 10-second seek; the arrow keys move by 5s and change volume.
_TAB_KEYS = {
    "play_pause": "k",
    "seek_back": "j",
    "seek_fwd": "l",
    "volume_down": "down",
    "volume_up": "up",
    "mute": "m",
    "fullscreen": "f",
}

# The same actions as xdotool key names, for the X11 fallback.
_KEYS = {
    "play_pause": ["space"],
    "seek_back": ["Left", "Left"],    # YouTube seeks 5s per arrow
    "seek_fwd": ["Right", "Right"],
    "volume_down": ["Down"],
    "volume_up": ["Up"],
    "mute": ["m"],
    "fullscreen": ["f"],
}

_LABELS = [
    ("play_pause", "Play/Pause"),
    ("seek_back", "<- 10s"),
    ("seek_fwd", "10s ->"),
    ("volume_down", "Volume -"),
    ("volume_up", "Volume +"),
    ("mute", "Mute"),
    ("fullscreen", "Fullscreen"),
]


def is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def missing_tools() -> list[str]:
    """Which of the X11 tools the fallback needs are absent."""
    return [tool for tool in ("xdotool", "wmctrl") if not shutil.which(tool)]


# --- route 1: the GNOME extension -------------------------------------------

def find_youtube_tab() -> dict | None:
    """Locate a YouTube tab and the keys that select it, through the extension.

    Returns {"wid", "chord", "title"} or None. An empty chord means the tab is
    already the window's active one and the shortcut can go straight in.
    """
    if dbus is None:
        return None

    windows = list_windows()
    if not windows:
        return None

    # A window titled "... - YouTube" is showing YouTube in its *active* tab,
    # which is the common case and needs no tab switch at all. Preferring it
    # also covers Chrome and the other browsers, whose tabs cannot be
    # enumerated the way Firefox's can.
    #
    # The window class is checked as well as the title, because plenty of
    # windows mention YouTube without being able to play it: an editor holding
    # youtube.py, a terminal running yt-dlp, a chat about a video. Typing "f"
    # at one of those is a stray keystroke in someone's source file.
    for w in windows:
        title = str(w.get("title") or "")
        if _is_browser(str(w.get("wm_class") or "")) and "youtube" in title.casefold():
            return {
                "wid": int(w.get("id")),
                "chord": "",
                "title": _strip_browser_suffix(title).strip() or "YouTube",
            }

    # Otherwise the video is parked in a background tab. Only Firefox exposes
    # its tab list (see sources/firefox.py), so only Firefox can be searched.
    try:
        sessions = get_firefox_windows()
    except Exception:
        sessions = []
    if not sessions:
        return None

    used: set = set()
    for w in windows:
        if "firefox" not in str(w.get("wm_class") or "").casefold():
            continue
        session = _match_session_window(str(w.get("title") or ""), sessions, used)
        if not session:
            continue
        tabs = session["tabs"]
        for i, tab in enumerate(tabs):
            if "youtube.com" in (tab.get("url") or "").casefold():
                return {
                    "wid": int(w.get("id")),
                    "chord": _tab_chord(i, len(tabs)),
                    "title": tab.get("title") or "YouTube",
                }
    return None


def _chord_for(entry: dict, keys: str) -> str:
    """The full chord list: select the tab if needed, then type the shortcut.

    Alt+1..9 is not reserved by Firefox, so a web app is free to claim it.
    Ctrl+L is reserved -- no page can swallow it -- so parking focus in the
    address bar first takes the page out of the keyboard path, and Escape hands
    focus back to the content before the shortcut is typed.
    """
    if entry["chord"]:
        return f"ctrl+l,{entry['chord']},escape,{keys}"
    return keys


def _send_shell_keys(entry: dict, keys: str) -> dict:
    try:
        shell_interface().SendKeys(dbus.UInt32(entry["wid"]), _chord_for(entry, keys))
        return {"ok": True, "message": ""}
    except Exception as e:
        detail = str(e).strip().splitlines()[-1] if str(e).strip() else e.__class__.__name__
        return {"ok": False, "message": f"GNOME extension error: {detail}"}


# --- route 2: xdotool -------------------------------------------------------

def x11_unavailable_reason() -> str:
    """Why the xdotool fallback is not on offer, or "" when it is available."""
    if is_wayland():
        return (
            "Keystroke control through xdotool needs X11; this is a Wayland "
            "session, where only the GNOME extension can send keys."
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


def _send_x11_keys(window: dict, keys: list[str]) -> dict:
    """Focus the YouTube window, then send the keys for one action.

    Focusing first matters: xdotool sends to whatever holds focus, so without
    this the keystrokes land in whichever window the user last touched.
    """
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


# --- what the remote sees ---------------------------------------------------

def _no_target_message() -> str:
    """Why no keystroke can be delivered right now, in terms that can be acted on."""
    if dbus is None and is_wayland():
        return (
            "No YouTube tab found, and python-dbus is not importable, so the "
            "GNOME extension cannot be reached either. Install it with "
            "'apt install python3-dbus'."
        )
    if is_wayland():
        return (
            "No YouTube tab found. Open a video, and make sure the window "
            "extension is installed and enabled ('vt install-extension', then "
            "log out and back in) -- under Wayland it is the only way to send "
            "keys. Play/pause is also available on the MPRIS player."
        )
    reason = x11_unavailable_reason()
    if reason:
        return reason
    return "No YouTube window found. Open a video first."


def get_youtube_player_target() -> Target | None:
    """Keystroke controls for a YouTube tab, when one can be reached."""
    entry = find_youtube_tab()
    if entry:
        actions = [Action(id=a, label=label) for a, label in _LABELS]
        actions.append(Action(id="close", label="Close tab", kind="confirm"))
        return Target(
            id="youtube:player",
            kind="youtube_player",
            title="YouTube (keys)",
            subtitle=entry["title"][:50],
            icon="|>",
            status="playing",
            actions=actions,
        )

    if x11_unavailable_reason():
        return None
    window = find_youtube_window()
    if not window:
        return None

    actions = [Action(id=a, label=label) for a, label in _LABELS if a in _KEYS]
    actions.append(Action(id="close", label="Close", kind="confirm"))
    return Target(
        id="youtube:player",
        kind="youtube_player",
        title="YouTube (keys)",
        subtitle=window["name"][:50],
        icon="|>",
        status="playing",
        actions=actions,
    )


def send_keys(action_id: str) -> dict:
    """Deliver one playback shortcut to the YouTube tab."""
    entry = find_youtube_tab()
    if entry:
        keys = _TAB_KEYS.get(action_id)
        if not keys:
            return {"ok": False, "message": f"Unknown player action: {action_id}"}
        result = _send_shell_keys(entry, keys)
        if result["ok"]:
            result["message"] = f"Sent {action_id.replace('_', ' ')}"
        return result

    keys = _KEYS.get(action_id)
    if not keys:
        return {"ok": False, "message": f"Unknown player action: {action_id}"}

    # No tab the extension can reach and no xdotool either: say what would
    # make this work rather than restating that it does not.
    if x11_unavailable_reason():
        return {"ok": False, "message": _no_target_message()}
    window = find_youtube_window()
    if not window:
        return {"ok": False, "message": _no_target_message()}
    return _send_x11_keys(window, keys)


def close_youtube_window() -> dict:
    """Close the YouTube tab (extension) or its window (xdotool fallback)."""
    entry = find_youtube_tab()
    if entry:
        result = _send_shell_keys(entry, "ctrl+w")
        if result["ok"]:
            result["message"] = "Closed the YouTube tab"
        return result

    if not shutil.which("wmctrl"):
        return {"ok": False, "message": _no_target_message()}

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
