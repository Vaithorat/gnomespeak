"""Pointer, typing and keyboard control -- the phone as a trackpad.

Everything here goes through the GNOME extension. Under Wayland only the
compositor may synthesize input, so xdotool is not a fallback, it is a no-op:
the keystroke is accepted, nothing receives it, and the failure is silent. The
extension runs inside the compositor, which is why it is the only route.

Nothing in this module produces a Target. A trackpad is not a thing to act on
once, it is a surface the phone streams gestures into at 20 Hz, so it has its
own endpoint (/api/input) rather than a row in the 1 Hz snapshot.
"""

from vt.shell import interface

try:
    import dbus
except ImportError:
    dbus = None

UNKNOWN_METHOD = "org.freedesktop.DBus.Error.UnknownMethod"
_NO_SERVICE = {
    "org.freedesktop.DBus.Error.ServiceUnknown",
    "org.freedesktop.DBus.Error.NameHasNoOwner",
}

# One pointer step is capped well below a screen width. A phone that loses a
# touchmove reports the whole missed distance in the next event, and without a
# cap that arrives as the pointer teleporting into a corner.
MAX_STEP = 400
MAX_TEXT = 2000

BUTTONS = {"left": 1, "middle": 2, "right": 3}

# Mirrors the extension's own table. Validating here rather than there is what
# turns "nothing happened, check the shell journal" into a message on the phone.
NAMED_KEYS = {
    "tab", "page_up", "page_down", "home", "end", "escape", "return", "space",
    "up", "down", "left", "right", "backspace", "delete",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
}
MODIFIERS = {"alt", "ctrl", "control", "shift", "super"}

_MISSING = (
    "Pointer and typing control need the current GNOME extension. Run "
    "`vt install-extension`, then log out and back in to reload it."
)


def _clamp(value, limit=MAX_STEP) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(-limit, min(limit, number))


def valid_chord(chord: str) -> bool:
    """Whether a chord like "ctrl+shift+t" names keys the extension knows."""
    parts = [p.strip().lower() for p in str(chord).split("+")]
    if not parts or not all(parts):
        return False
    key = parts.pop()
    if len(key) != 1 and key not in NAMED_KEYS:
        return False
    return all(part in MODIFIERS for part in parts)


def _call(method: str, *args) -> dict:
    """Invoke one extension method, translating D-Bus failures into messages."""
    if dbus is None:
        return {"ok": False, "message": "python-dbus is not importable; remote input is unavailable"}
    try:
        getattr(interface(), method)(*args)
        return {"ok": True, "message": ""}
    except dbus.DBusException as e:
        try:
            name = e.get_dbus_name() or ""
        except Exception:
            name = ""
        if name in _NO_SERVICE:
            return {"ok": False, "message": "GNOME extension not available. Run `vt install-extension`."}
        if name == UNKNOWN_METHOD:
            return {"ok": False, "message": _MISSING}
        detail = str(e).strip().splitlines()[-1] if str(e).strip() else name
        return {"ok": False, "message": f"GNOME extension error: {detail}"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def _i32(value):
    """dbus-python guesses int32 from a bare int, but only with introspection
    off does that guess have to be right -- so say so explicitly."""
    return dbus.Int32(value) if dbus else value


def move(dx, dy) -> dict:
    """Move the pointer by a delta, trackpad style."""
    dx, dy = _clamp(dx), _clamp(dy)
    if not dx and not dy:
        return {"ok": True, "message": ""}
    return _call("Pointer", _i32(dx), _i32(dy))


def click(button="left", double=False) -> dict:
    """Click a mouse button where the pointer already is."""
    code = BUTTONS.get(str(button).lower())
    if code is None:
        return {"ok": False, "message": f"Unknown button: {button}"}
    if dbus is None:
        return _call("Click", code, bool(double))
    result = _call("Click", dbus.UInt32(code), dbus.Boolean(bool(double)))
    if result["ok"]:
        result["message"] = f"{'Double-' if double else ''}{str(button).capitalize()} click"
    return result


def scroll(dx, dy) -> dict:
    """Scroll by a pixel delta of thumb travel."""
    dx, dy = _clamp(dx), _clamp(dy)
    if not dx and not dy:
        return {"ok": True, "message": ""}
    return _call("Scroll", _i32(dx), _i32(dy))


def type_text(text: str) -> dict:
    """Type a literal string into whatever has focus."""
    text = str(text or "")[:MAX_TEXT]
    if not text:
        return {"ok": False, "message": "Nothing to type"}
    result = _call("TypeText", text)
    if result["ok"]:
        result["message"] = f"Typed {len(text)} character{'s' if len(text) != 1 else ''}"
    return result


def send_keys(chords: str) -> dict:
    """Send one or more comma-separated chords to the focused window."""
    parts = [c.strip() for c in str(chords or "").split(",") if c.strip()]
    if not parts:
        return {"ok": False, "message": "No keys given"}
    for chord in parts:
        if not valid_chord(chord):
            return {"ok": False, "message": f"Unknown key combination: {chord}"}
    result = _call("Keys", ",".join(parts))
    if result["ok"]:
        result["message"] = "Sent " + ", ".join(parts)
    return result


def execute(op: str, payload: dict) -> dict:
    """Dispatch one input operation from /api/input."""
    if op == "move":
        return move(payload.get("dx"), payload.get("dy"))
    if op == "click":
        return click(payload.get("button", "left"), bool(payload.get("double")))
    if op == "scroll":
        return scroll(payload.get("dx"), payload.get("dy"))
    if op == "type":
        return type_text(payload.get("text", ""))
    if op == "keys":
        return send_keys(payload.get("keys", ""))
    return {"ok": False, "message": f"Unknown input op: {op}"}
