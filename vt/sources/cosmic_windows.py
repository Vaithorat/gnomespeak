"""Window management on COSMIC (System76's Smithay-based compositor).

COSMIC has no GNOME-Shell-style in-process extension to talk D-Bus to (its
own D-Bus surface, `com.system76.CosmicComp`, exposes only input-emulation
for the remote-desktop portal -- verified by hand, nothing for window
listing or control). Instead it implements its own Wayland protocols:

- `ext-foreign-toplevel-list-v1` (upstream-standard) for enumeration: each
  open window gets a `title`, an `app_id`, and an `identifier` -- a string
  the protocol guarantees stays the same for the same window across
  *separate* client connections, which is exactly what lets `vt do` (a fresh
  process) address a window a previous `vt status` reported.
- `cosmic-toplevel-info-unstable-v1` bridges that generic handle to a COSMIC
  one (`get_cosmic_toplevel`) that adds `state` -- minimized/maximized/
  activated/fullscreen/sticky, as a packed array of 4-byte LE uint32 enum
  values (the wlr/ext convention; see _decode_state).
- `cosmic-toplevel-management-unstable-v1` for control: activate, close,
  set/unset maximized, set/unset minimized. move_to_workspace exists in the
  protocol but is deliberately not wired up here -- see
  _cosmic_wayland/__init__.py.

This module keeps exactly one Wayland connection open for the life of the
process and never makes a second one. That is a hard constraint, not a style
choice: creating a second pywayland Display() in the same interpreter after
a prior one connected and disconnected reliably crashed the process (SIGSEGV,
reproduced repeatedly against cosmic-comp 1.7.0) even with nothing else going
on. A single long-lived connection, reused for every call, is safe -- dozens
of consecutive roundtrips on it were exercised with no issue. So unlike the
GNOME extension (a D-Bus call per action, stateless from vt's side), this
module is *not* stateless: the first call connects and binds; every call
after that reuses the same connection and the same live toplevel map, kept
current by the ordinary flow of Wayland events.

Every public function here still follows the source-module contract of never
raising: connection failure or a missing/older compositor is cached after
the first attempt (there is nothing to gain by retrying every second --
COSMIC's globals don't appear mid-session) and turned into [] / a failure
dict from then on.

**Keystrokes.** `zwp_virtual_keyboard_manager_v1` -- a standard wlroots-family
protocol, not COSMIC-specific -- lets this module type chords into whatever
window it has just activated, the same shape as the GNOME extension's
SendKeys. See sources/cosmic_input.py for the keymap/keycode/chord-parsing
half of that; unlike the toplevel protocols above, it is optional here: a
compositor without it still gets window listing and control, just not
send_keys(). See COSMIC_INPUT_PARITY.md for the design and the Phase 0 spike
that established an ordinary client is allowed to do this on COSMIC.
"""

import atexit
import re
from typing import Optional

from vt.sources import cosmic_input

try:
    from pywayland.client import Display
    HAS_PYWAYLAND = True
except ImportError:
    Display = None
    HAS_PYWAYLAND = False


_REQUIRED_GLOBALS = (
    "wl_seat",
    "ext_foreign_toplevel_list_v1",
    "zcosmic_toplevel_info_v1",
    "zcosmic_toplevel_manager_v1",
)

# Not in _REQUIRED_GLOBALS: window listing/control must keep working on a
# wlroots-family compositor that has this bound to a security context and
# refuses it to ordinary clients (see COSMIC_INPUT_PARITY.md's Phase 0).
# Only send_keys() needs it, and fails on its own when it's missing.
_KEYBOARD_GLOBAL = "zwp_virtual_keyboard_manager_v1"

# zcosmic_toplevel_handle_v1.state enum (cosmic-toplevel-info-unstable-v1.xml).
_MAXIMIZED, _MINIMIZED, _ACTIVATED, _FULLSCREEN, _STICKY = range(5)


def _decode_state(raw: bytes) -> set:
    """Unpack a `state` event's array arg: packed 4-byte LE uint32s."""
    n = len(raw) // 4
    import struct
    return set(struct.unpack(f"<{n}I", raw[: n * 4]))


def available() -> bool:
    """Whether this module could plausibly do anything at all."""
    return HAS_PYWAYLAND


class _Toplevel:
    __slots__ = ("identifier", "title", "app_id", "state", "cosmic_handle")

    def __init__(self):
        self.identifier: Optional[str] = None
        self.title: str = ""
        self.app_id: str = ""
        self.state: set = set()
        self.cosmic_handle = None


class _NotCosmic(Exception):
    """Raised internally when the compositor doesn't speak these protocols."""


class _NoVirtualKeyboard(Exception):
    """Raised internally when zwp_virtual_keyboard_manager_v1 isn't bound."""


class _Connection:
    """The one Wayland connection this process will ever open. See module docstring."""

    def __init__(self):
        self.display = None
        self.seat = None
        self.manager = None
        self.toplevels: dict = {}  # ext_foreign_handle -> _Toplevel
        self.unavailable_reason: Optional[str] = None
        self.keyboard_manager = None  # bound only if the global is present
        self.vkbd = None  # created lazily, once, on first send_keys()

    def _bind(self):
        from pywayland.protocol.wayland import WlSeat
        from vt.sources._cosmic_wayland.ext_foreign_toplevel_list_v1 import (
            ExtForeignToplevelListV1,
        )
        from vt.sources._cosmic_wayland.cosmic_toplevel_info_unstable_v1 import (
            ZcosmicToplevelInfoV1,
        )
        from vt.sources._cosmic_wayland.cosmic_toplevel_management_unstable_v1 import (
            ZcosmicToplevelManagerV1,
        )
        from vt.sources._cosmic_wayland.virtual_keyboard_unstable_v1 import (
            ZwpVirtualKeyboardManagerV1,
        )

        found: dict = {}
        display = Display()
        display.connect()
        registry = display.get_registry()
        registry.dispatcher["global"] = lambda r, id_, iface, ver: found.__setitem__(iface, (id_, ver))
        display.roundtrip()

        missing = [name for name in _REQUIRED_GLOBALS if name not in found]
        if missing:
            display.disconnect()
            raise _NotCosmic(f"missing globals: {missing}")

        seat_id, seat_ver = found["wl_seat"]
        self.seat = registry.bind(seat_id, WlSeat, seat_ver)

        ftl_id, ftl_ver = found["ext_foreign_toplevel_list_v1"]
        ftl = registry.bind(ftl_id, ExtForeignToplevelListV1, ftl_ver)

        info_id, info_ver = found["zcosmic_toplevel_info_v1"]
        info = registry.bind(info_id, ZcosmicToplevelInfoV1, min(info_ver, 3))

        mgr_id, mgr_ver = found["zcosmic_toplevel_manager_v1"]
        self.manager = registry.bind(mgr_id, ZcosmicToplevelManagerV1, min(mgr_ver, 4))

        if _KEYBOARD_GLOBAL in found:
            vkm_id, vkm_ver = found[_KEYBOARD_GLOBAL]
            self.keyboard_manager = registry.bind(vkm_id, ZwpVirtualKeyboardManagerV1, vkm_ver)

        ftl.dispatcher["toplevel"] = self._on_toplevel
        ftl.dispatcher["finished"] = lambda _ftl: None
        info.dispatcher["done"] = lambda _info: None
        self._info = info

        self.display = display
        # A live pywayland Display left for the garbage collector to finalize
        # at interpreter shutdown segfaults reliably (reproduced repeatedly);
        # an explicit disconnect() before then does not. atexit runs ahead of
        # GC-driven finalization, so this is the fix, not a nicety.
        atexit.register(self.disconnect)

    def disconnect(self):
        if self.display is not None:
            try:
                self.display.disconnect()
            except Exception:
                pass
            self.display = None

    def _on_toplevel(self, _ftl, ext_handle):
        tl = _Toplevel()
        self.toplevels[ext_handle] = tl

        ext_handle.dispatcher["identifier"] = lambda h, v: setattr(tl, "identifier", v)
        ext_handle.dispatcher["title"] = lambda h, v: setattr(tl, "title", v)
        ext_handle.dispatcher["app_id"] = lambda h, v: setattr(tl, "app_id", v)
        ext_handle.dispatcher["done"] = lambda h: None
        ext_handle.dispatcher["closed"] = lambda h: self.toplevels.pop(ext_handle, None)

        cosmic_handle = self._info.get_cosmic_toplevel(ext_handle)
        tl.cosmic_handle = cosmic_handle
        cosmic_handle.dispatcher["state"] = lambda h, raw: setattr(tl, "state", _decode_state(raw))
        cosmic_handle.dispatcher["geometry"] = lambda *a: None
        cosmic_handle.dispatcher["output_enter"] = lambda *a: None
        cosmic_handle.dispatcher["output_leave"] = lambda *a: None
        cosmic_handle.dispatcher["closed"] = lambda h: None

    def ensure_ready(self):
        """Connect and bind on first use. Raises _NotCosmic once, then forever."""
        if self.unavailable_reason is not None:
            raise _NotCosmic(self.unavailable_reason)
        if self.display is not None:
            return
        try:
            self._bind()
        except _NotCosmic as e:
            self.unavailable_reason = str(e)
            raise
        # A real connection error (no WAYLAND_DISPLAY, socket refused, ...) is
        # not cached: it's cheap to notice again next time, and unlike a
        # missing protocol it is not guaranteed to still be true later.

    def refresh(self):
        """Pull in whatever the compositor has queued -- new/closed/changed windows."""
        self.display.roundtrip()

    def find(self, identifier: str) -> Optional[_Toplevel]:
        return next((tl for tl in self.toplevels.values() if tl.identifier == identifier), None)

    def ensure_keyboard(self):
        """Lazily create the one virtual keyboard this connection will ever have.

        Deferred to first use rather than done in _bind(): most calls into
        this module (list_windows(), plain window actions) never need it, and
        there is no reason to upload a keymap nobody asked for.
        """
        if self.vkbd is not None:
            return self.vkbd
        if self.keyboard_manager is None:
            raise _NoVirtualKeyboard(
                "zwp_virtual_keyboard_manager_v1 not available on this compositor"
            )
        vkbd = self.keyboard_manager.create_virtual_keyboard(self.seat)
        cosmic_input.upload_keymap(vkbd)
        self.refresh()
        self.vkbd = vkbd
        return vkbd


_conn = _Connection()

PREFIX = "cosmic:"


def list_windows() -> list[dict]:
    """Open windows, shaped like sources/windows.py's GNOME List() output.

    Returns [] whenever COSMIC's protocols are unavailable -- wrong or too
    old a compositor, pywayland not installed, or any connection error.
    `id` carries the "cosmic:" prefix so windows.py/actions.py can route an
    action back to this module without guessing from the id's shape.
    """
    if not HAS_PYWAYLAND:
        return []
    try:
        _conn.ensure_ready()
        _conn.refresh()
    except Exception:
        return []

    return [
        {
            "id": f"{PREFIX}{tl.identifier}",
            "title": tl.title or "Unknown",
            "wm_class": tl.app_id or "",
            "minimized": _MINIMIZED in tl.state,
            "maximized": _MAXIMIZED in tl.state,
            # windows.py uses this to route ids back to this module rather
            # than the GNOME extension's D-Bus path -- see execute() below.
            "backend": "cosmic",
        }
        for tl in _conn.toplevels.values()
        if tl.identifier
    ]


_ACTIONS = {
    "focus": ("activate", "Window focused"),
    "close": ("close", "Window closed"),
    "close_window": ("close", "Window closed"),
    "minimize": ("set_minimized", "Window minimized"),
    "unminimize": ("unset_minimized", "Window restored"),
    "maximize": ("set_maximized", "Window maximized"),
    "unmaximize": ("unset_maximized", "Window unmaximized"),
}

# Tab targets carry their key chord in the id fragment, same shape as
# actions.py's _TAB_ID -- but the wid half is an opaque ext-foreign
# identifier string here, not a Mutter integer, so this can't reuse that
# regex. See windows.py's _tab_targets(), which builds these ids generically
# from whatever id a backend already gave a window.
_TAB_ID = re.compile(r"^(?P<wid>.+)#tab=(?P<tab>\d+)&keys=(?P<keys>.+)$")


def _guarded(chord: str) -> str:
    """Wrap a tab-selection chord so the focused page cannot intercept it.

    Same reasoning as actions.py's _guarded for the GNOME path: Alt+1..9 is
    not reserved by Firefox, so a web app is free to claim it, but Ctrl+L
    always focuses the address bar, taking the page out of the keyboard path
    until Escape hands focus back to the content.
    """
    return f"ctrl+l,{chord},escape"


def _execute_tab_action(wid: str, tab: "re.Match", action_id: str) -> dict:
    """Act on one browser tab, addressed by the chord that selects it."""
    chord = tab.group("keys")
    number = int(tab.group("tab")) + 1

    if action_id == "focus":
        result = send_keys(wid, _guarded(chord))
        if result["ok"]:
            result["message"] = f"Switched to tab {number}"
        return result
    if action_id in ("close", "close_tab"):
        result = send_keys(wid, f"{_guarded(chord)},ctrl+w")
        if result["ok"]:
            result["message"] = f"Closed tab {number}"
        return result
    if action_id == "close_window":
        return execute(wid, "close")
    return {"ok": False, "message": f"Unknown tab action: {action_id}"}


def send_keys(identifier: str, chord: str) -> dict:
    """Activate a window, then type a chord into it via the virtual keyboard.

    The COSMIC-side equivalent of the GNOME extension's SendKeys(id, chord):
    used for Firefox tab-switching/close and YouTube playback keys, none of
    which are a structured toplevel-management request. See
    sources/cosmic_input.py for the keymap/keycode/chord half of this.
    """
    if not HAS_PYWAYLAND:
        return {"ok": False, "message": "pywayland is not installed (pip install gnomespeak[wayland])"}

    try:
        _conn.ensure_ready()
    except _NotCosmic:
        return {"ok": False, "message": "COSMIC window protocols not available"}
    except Exception as e:
        return {"ok": False, "message": f"Wayland connection error: {e}"}

    try:
        _conn.refresh()
        match = _conn.find(identifier)
        if match is None:
            return {"ok": False, "message": "Window not found (it may have closed)"}

        _conn.manager.activate(match.cosmic_handle, _conn.seat)
        _conn.refresh()

        vkbd = _conn.ensure_keyboard()
        cosmic_input.send_chord(vkbd, chord)
        _conn.refresh()
        return {"ok": True, "message": ""}
    except _NoVirtualKeyboard as e:
        return {"ok": False, "message": str(e)}
    except cosmic_input.UnknownKey as e:
        return {"ok": False, "message": str(e)}
    except Exception as e:
        return {"ok": False, "message": f"Wayland error: {e}"}


def execute(identifier: str, action_id: str) -> dict:
    """Act on one window, addressed by its ext-foreign-toplevel identifier."""
    if not HAS_PYWAYLAND:
        return {"ok": False, "message": "pywayland is not installed (pip install gnomespeak[wayland])"}

    tab = _TAB_ID.match(identifier)
    if tab:
        return _execute_tab_action(tab.group("wid"), tab, action_id)

    if action_id == "close_tab":
        # A single-tab (unexpanded) browser window: no tab to select, just
        # the Ctrl+W the GNOME path also uses for this case.
        result = send_keys(identifier, "ctrl+w")
        if result["ok"]:
            result["message"] = "Tab closed"
        return result

    if action_id not in _ACTIONS:
        return {"ok": False, "message": f"Unknown window action: {action_id}"}
    method, message = _ACTIONS[action_id]

    try:
        _conn.ensure_ready()
    except _NotCosmic:
        return {"ok": False, "message": "COSMIC window protocols not available"}
    except Exception as e:
        return {"ok": False, "message": f"Wayland connection error: {e}"}

    try:
        _conn.refresh()
        match = _conn.find(identifier)
        if match is None:
            return {"ok": False, "message": "Window not found (it may have closed)"}

        if method == "activate":
            _conn.manager.activate(match.cosmic_handle, _conn.seat)
        else:
            getattr(_conn.manager, method)(match.cosmic_handle)
        _conn.refresh()
        return {"ok": True, "message": message}
    except Exception as e:
        return {"ok": False, "message": f"Wayland error: {e}"}
