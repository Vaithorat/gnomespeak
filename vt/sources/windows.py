"""Window management via GNOME Shell extension."""

import json
from urllib.parse import urlparse

from vt.model import Target, Action
from vt.sources.firefox import get_firefox_windows

try:
    import dbus
except ImportError:
    dbus = None

SHELL_BUS_NAME = "org.gnome.Shell.Extensions.VoiceTalk"
SHELL_OBJECT_PATH = "/org/gnome/Shell/Extensions/VoiceTalk"

BROWSERS = {"firefox", "chrome", "chromium", "brave", "edge", "opera"}

# Offering to send a window to any of a dozen workspaces turns a two-button row
# into a menu; the first few cover what anyone actually does by voice.
_MAX_MOVE_TARGETS = 4

# Firefox binds Alt+1..8 to "jump to tab N" and Alt+9 to "jump to last tab".
# There is no shortcut for tabs 9..n-1, so those are reached by landing on tab 8
# and walking forward -- see _tab_chord.
_DIRECT_TAB_LIMIT = 8


def shell_interface():
    """The GNOME extension's D-Bus interface. Raises if it is not running."""
    if dbus is None:
        raise RuntimeError("python-dbus is not available")
    bus = dbus.SessionBus()
    # introspect=False: the interface is named explicitly on the next line, so
    # the Introspect round trip is pure cost -- once per second, forever.
    obj = bus.get_object(SHELL_BUS_NAME, SHELL_OBJECT_PATH, introspect=False)
    return dbus.Interface(obj, SHELL_BUS_NAME)


def list_windows() -> list[dict]:
    """Windows on the active workspace, or [] when nothing can report them.

    Tries the GNOME extension first. When that is not there -- no D-Bus, the
    extension not installed, or a different compositor entirely -- falls back
    to sources/cosmic_windows.py, which speaks COSMIC's own Wayland protocols
    directly. That backend has no concept of "active workspace" (the protocol
    it uses doesn't filter by one), so on COSMIC this returns every window on
    every workspace.
    """
    if dbus:
        try:
            windows = json.loads(shell_interface().List())
            if windows:
                return windows
        except Exception:
            pass

    from vt.sources.cosmic_windows import list_windows as cosmic_list_windows
    return cosmic_list_windows()


def workspace_info() -> dict:
    """{"count", "active"} from the extension, or {} when it cannot be reached.

    Older builds of the extension have no Workspaces method, so an absent
    result means "do not offer workspace actions", not "something is broken".
    """
    if not dbus:
        return {}
    try:
        return json.loads(shell_interface().Workspaces())
    except Exception:
        return {}


def _is_browser(wm_class: str) -> bool:
    """Check if a window belongs to a browser."""
    wm_class_lower = (wm_class or "").lower()
    return any(browser in wm_class_lower for browser in BROWSERS)


def _strip_browser_suffix(title: str) -> str:
    """Drop the " - Mozilla Firefox" tail the window manager sees."""
    for sep in (" — Mozilla Firefox", " - Mozilla Firefox", " – Mozilla Firefox"):
        if title.endswith(sep):
            return title[: -len(sep)]
    return title


def _tab_chord(index: int, total: int) -> str:
    """The key sequence that lands Firefox on tab `index` (0-based).

    Always absolute, never relative to the current tab: the remote has no idea
    which tab is focused right now, and a relative walk would drift every time
    the user touched the keyboard themselves.
    """
    if index < _DIRECT_TAB_LIMIT:
        return f"alt+{index + 1}"
    if index == total - 1:
        return "alt+9"
    # Land on tab 8, then step forward. Absolute, if not elegant.
    steps = index - (_DIRECT_TAB_LIMIT - 1)
    return ",".join([f"alt+{_DIRECT_TAB_LIMIT}"] + ["ctrl+page_down"] * steps)


def _match_session_window(wm_title: str, sessions: list[dict], used: set) -> dict | None:
    """Pair a window-manager window with a session-store window.

    The window title is the active tab's title, so matching on it is exact for
    the common case. Session order is not window-manager order, hence the search
    rather than an index lookup; `used` keeps two Firefox windows showing the
    same tab from claiming the same session entry.
    """
    stripped = _strip_browser_suffix(wm_title).strip()

    for i, sess in enumerate(sessions):
        if i in used:
            continue
        selected = sess["tabs"][sess["selected"]]["title"].strip()
        if selected and selected == stripped:
            used.add(i)
            return sess

    # Firefox decorates titles ("(1) Calendar", "* unsaved"), so fall back to a
    # containment test before giving up.
    for i, sess in enumerate(sessions):
        if i in used:
            continue
        selected = sess["tabs"][sess["selected"]]["title"].strip()
        if selected and (selected in stripped or stripped in selected):
            used.add(i)
            return sess

    # One window, one session: take it. Any mismatch here is a stale title.
    if len(sessions) == 1 and not used:
        used.add(0)
        return sessions[0]

    return None


def _tab_targets(window: dict, session: dict) -> list[Target]:
    """One target per tab of a single Firefox window."""
    wid = window.get("id")
    tabs = session["tabs"]
    selected = session["selected"]
    minimized = window.get("minimized")

    targets = []
    for i, tab in enumerate(tabs):
        chord = _tab_chord(i, len(tabs))
        host = ""
        try:
            host = urlparse(tab.get("url", "")).hostname or ""
        except ValueError:
            host = ""
        if host.startswith("www."):
            host = host[4:]

        if minimized:
            status = "minimized"
        elif i == selected:
            status = "active"
        else:
            status = "running"

        targets.append(Target(
            # The chord travels in the id so the action handler needs no second
            # look at the session store, which may have changed underneath it.
            id=f"window:{wid}#tab={i}&keys={chord}",
            kind="window",
            title=tab["title"],
            subtitle=f"Firefox · {host}" if host else "Firefox",
            icon="▭",
            status=status,
            actions=[
                Action(id="focus", label="Focus"),
                Action(id="close", label="Close tab", kind="confirm"),
            ],
        ))
    return targets


def get_window_targets() -> list[Target]:
    """Get open windows via the GNOME extension D-Bus interface.

    Firefox windows expand into one target per tab, read from the browser's
    session store -- the window manager only ever reports the active tab. See
    vt/sources/firefox.py for why that file is the only tab list available.

    The extension is optional and may not be present or enabled -- and on a
    non-GNOME compositor, list_windows() falls back to sources/cosmic_windows.py
    instead, which needs no D-Bus at all. This function returns [] gracefully
    if neither backend can report anything.
    """
    windows = list_windows()
    if not windows:
        return []

    try:
        sessions = get_firefox_windows()
    except Exception:
        sessions = []
    used: set = set()

    # List() only ever reports the active workspace, so every window here is on
    # it -- the only moves worth offering are to the *other* workspaces.
    spaces = workspace_info()
    move_actions = []
    for index in range(min(int(spaces.get("count", 0) or 0), _MAX_MOVE_TARGETS)):
        if index == int(spaces.get("active", -1)):
            continue
        move_actions.append(
            Action(id=f"move_ws_{index}", label=f"To workspace {index + 1}")
        )

    targets = []
    for w in windows:
        wm_class = w.get("wm_class", "")

        if "firefox" in wm_class.lower() and sessions:
            session = _match_session_window(w.get("title", ""), sessions, used)
            # A single-tab window is its own best representation; expanding it
            # would just duplicate the window entry under a different id.
            if session and len(session["tabs"]) > 1:
                targets.extend(_tab_targets(w, session))
                continue

        # Frame-level actions only. Playback belongs to the player that owns
        # the media, not to the window around it: a YouTube tab is controlled
        # through Firefox's MPRIS player, which reports its own capabilities,
        # and through sources/youtube_player.py for what MPRIS cannot express.
        actions = [Action(id="focus", label="Focus")]

        if w.get("minimized"):
            actions.append(Action(id="unminimize", label="Restore"))
        else:
            actions.append(Action(id="minimize", label="Minimize"))
        if w.get("maximized"):
            actions.append(Action(id="unmaximize", label="Unmaximize"))
        else:
            actions.append(Action(id="maximize", label="Maximize"))
        actions.extend(move_actions)

        if _is_browser(wm_class):
            actions.append(Action(id="close_tab", label="Close tab", kind="confirm"))
            actions.append(Action(id="close_window", label="Close window", kind="confirm"))
        else:
            actions.append(Action(id="close", label="Close", kind="confirm"))

        targets.append(Target(
            id=f"window:{w.get('id')}",
            kind="window",
            title=w.get("title", "Unknown"),
            icon="▭",
            status="running" if not w.get("minimized") else "minimized",
            actions=actions,
        ))

    return targets
