"""Wi-Fi radio control through NetworkManager.

Mirrors bluetooth.py's adapter target: one on/off switch, no scanning or
connecting to new networks. Picking a network from a phone with no way to
enter its passphrase is how people end up locked off their own Wi-Fi, so this
only ever touches the radio switch -- the same one the desktop's own quick
settings offers.
"""

from vt.model import Target, Action

try:
    import dbus
except ImportError:
    dbus = None

NM = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_IFACE = "org.freedesktop.NetworkManager"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

# NMConnectivityState: 4 means the connection actually reaches the internet,
# not just that a link is up.
_CONNECTIVITY_FULL = 4

_NO_SERVICE = {
    "org.freedesktop.DBus.Error.ServiceUnknown",
    "org.freedesktop.DBus.Error.NameHasNoOwner",
}


def _properties():
    """All of NetworkManager's top-level properties, or None if unreachable."""
    if dbus is None:
        return None
    try:
        bus = dbus.SystemBus()
        obj = bus.get_object(NM, NM_PATH, introspect=False)
        return dbus.Interface(obj, PROPS_IFACE).GetAll(NM_IFACE, timeout=5)
    except Exception:
        return None


def get_network_targets() -> list[Target]:
    """The Wi-Fi radio as a single on/off target, absent when NM is unreachable."""
    props = _properties()
    if props is None:
        return []

    enabled = bool(props.get("WirelessEnabled", False))
    connected = enabled and int(props.get("Connectivity", 0)) == _CONNECTIVITY_FULL

    return [Target(
        id="network:wifi",
        kind="system",
        title="Wi-Fi",
        icon="📶" if connected else ("📡" if enabled else "⚪"),
        status="connected" if connected else ("on" if enabled else "off"),
        actions=[
            Action(id="wifi_off", label="Turn off") if enabled
            else Action(id="wifi_on", label="Turn on")
        ],
    )]


def execute(target_spec: str, action_id: str) -> dict:
    """Run one network action. `target_spec` is always "wifi" for now."""
    if dbus is None:
        return {"ok": False, "message": "python-dbus is not importable; Wi-Fi control is unavailable"}
    if target_spec != "wifi":
        return {"ok": False, "message": f"Unknown network target: {target_spec}"}
    if action_id not in ("wifi_on", "wifi_off"):
        return {"ok": False, "message": f"Unknown network action: {action_id}"}

    try:
        bus = dbus.SystemBus()
        obj = bus.get_object(NM, NM_PATH, introspect=False)
        props = dbus.Interface(obj, PROPS_IFACE)
        enable = action_id == "wifi_on"
        props.Set(NM_IFACE, "WirelessEnabled", dbus.Boolean(enable), timeout=10)
        return {"ok": True, "message": "Wi-Fi on" if enable else "Wi-Fi off"}
    except dbus.DBusException as e:
        name = ""
        try:
            name = e.get_dbus_name() or ""
        except Exception:
            pass
        if name in _NO_SERVICE:
            return {"ok": False, "message": "NetworkManager is not running"}
        detail = str(e).strip().splitlines()[-1] if str(e).strip() else name
        return {"ok": False, "message": f"Wi-Fi error: {detail}"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}
