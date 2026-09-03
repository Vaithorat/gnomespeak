"""One still frame of the screen, on request, through the desktop portal.

Not a stream: no timer, no auto-refresh, and the file is deleted the moment it
has been read. Under Wayland there is no scrot equivalent -- and GNOME 45+
refuses `org.gnome.Shell.Screenshot` to callers that are not the Shell's own
tools -- so the portal is the only door, and the portal prompts. That prompt is
the honest cost of the feature and is stated on the button.
"""

import os
import secrets
from pathlib import Path
from urllib.parse import unquote, urlparse

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SCREENSHOT_IFACE = "org.freedesktop.portal.Screenshot"
REQUEST_IFACE = "org.freedesktop.portal.Request"

try:
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    HAS_GI = True
except Exception:  # pragma: no cover - exercised on machines without PyGObject
    HAS_GI = False


def unavailable_message() -> str:
    if not HAS_GI:
        return "python3-gi is not installed, so vt cannot talk to the screenshot portal"
    return "xdg-desktop-portal is not running, so there is nothing to ask for a screenshot"


def available() -> bool:
    """Whether a portal that can take a screenshot is on the bus."""
    if not HAS_GI:
        return False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(
            "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
            "NameHasOwner", GLib.Variant("(s)", (PORTAL_BUS,)),
            GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, 2000, None,
        )
        return bool(reply.unpack()[0])
    except Exception:
        return False


def _request_path(bus, token: str) -> str:
    sender = bus.get_unique_name().lstrip(":").replace(".", "_")
    return f"{PORTAL_PATH}/request/{sender}/{token}"


def capture(timeout: float = 60.0) -> dict:
    """Take one screenshot. Returns {"ok", "path"|"message"}.

    The prompt runs on the PC, so the phone waits: the timeout is generous
    because someone has to walk over and answer it the first time.
    """
    if not HAS_GI:
        return {"ok": False, "message": unavailable_message()}

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception as e:
        return {"ok": False, "message": f"No session bus: {e}"}

    token = "vt" + secrets.token_hex(8)
    loop = GLib.MainLoop()
    outcome = {}

    def on_response(_conn, _sender, _path, _iface, _signal, params):
        code, results = params.unpack()
        outcome["code"] = code
        outcome["uri"] = results.get("uri", "")
        loop.quit()

    subscription = bus.signal_subscribe(
        PORTAL_BUS, REQUEST_IFACE, "Response", _request_path(bus, token), None,
        Gio.DBusSignalFlags.NONE, on_response,
    )

    def give_up():
        outcome.setdefault("code", -1)
        loop.quit()
        return False

    timer = GLib.timeout_add(int(timeout * 1000), give_up)
    try:
        bus.call_sync(
            PORTAL_BUS, PORTAL_PATH, SCREENSHOT_IFACE, "Screenshot",
            GLib.Variant("(sa{sv})", ("", {
                "handle_token": GLib.Variant("s", token),
                "interactive": GLib.Variant("b", False),
                "modal": GLib.Variant("b", True),
            })),
            GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, 5000, None,
        )
        loop.run()
    except Exception as e:
        return {"ok": False, "message": f"The screenshot portal refused: {e}"}
    finally:
        try:
            GLib.source_remove(timer)
        except Exception:
            pass
        bus.signal_unsubscribe(subscription)

    code = outcome.get("code")
    if code == 1:
        return {"ok": False, "message": "You declined the screenshot on the PC"}
    if code == -1:
        return {"ok": False, "message": "The prompt on the PC went unanswered"}
    if code != 0 or not outcome.get("uri"):
        return {"ok": False, "message": "The portal returned no image"}

    path = Path(unquote(urlparse(outcome["uri"]).path))
    if not path.exists():
        return {"ok": False, "message": "The portal named a file that is not there"}
    return {"ok": True, "path": str(path)}


def read_and_remove(path: str) -> bytes:
    """The image, and then no image: nothing is kept on disk after serving."""
    data = Path(path).read_bytes()
    try:
        os.unlink(path)
    except OSError:
        pass
    return data
