"""Bluetooth control through BlueZ.

BlueZ is a system-bus service, so none of this needs the GNOME extension or any
input synthesis: it works the same under Wayland and X11. Pairing a *new*
device is deliberately absent -- that needs an agent to answer the PIN or
confirmation prompt, and answering it from a phone with no way to read the
number off the screen is how people pair the wrong device. Devices already
paired through the desktop's own dialog connect and disconnect fine.
"""

from vt.model import Target, Action

try:
    import dbus
except ImportError:
    dbus = None

BLUEZ = "org.bluez"
ADAPTER_IFACE = "org.bluez.Adapter1"
DEVICE_IFACE = "org.bluez.Device1"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

# Connecting negotiates with the device over the air; a headset that is asleep
# takes several seconds to answer, and BlueZ waits before giving up.
CONNECT_TIMEOUT = 25

# BlueZ reports a freedesktop icon name per device. Mapping the handful that
# actually turn up beats showing the same dot for a headset and a keyboard.
_ICONS = {
    "audio-headphones": "🎧",
    "audio-headset": "🎧",
    "audio-card": "🔊",
    "phone": "📱",
    "computer": "💻",
    "input-keyboard": "⌨",
    "input-mouse": "🖱",
    "input-gaming": "🎮",
}


def _managed_objects() -> dict:
    """Every object BlueZ knows about, or {} when BlueZ is not reachable."""
    if dbus is None:
        return {}
    try:
        bus = dbus.SystemBus()
        obj = bus.get_object(BLUEZ, "/", introspect=False)
        manager = dbus.Interface(obj, "org.freedesktop.DBus.ObjectManager")
        return manager.GetManagedObjects(timeout=5)
    except Exception:
        return {}


def _adapter_path(objects: dict | None = None) -> str:
    """The first Bluetooth adapter's object path, or "" when there is none."""
    objects = _managed_objects() if objects is None else objects
    for path, interfaces in objects.items():
        if ADAPTER_IFACE in interfaces:
            return str(path)
    return ""


def _device_label(props: dict) -> str:
    for key in ("Alias", "Name", "Address"):
        value = props.get(key)
        if value:
            return str(value)
    return "Unknown device"


def _set_powered(path: str, on: bool) -> dict:
    if dbus is None:
        return {"ok": False, "message": "python-dbus is not importable; Bluetooth is unavailable"}
    try:
        bus = dbus.SystemBus()
        obj = bus.get_object(BLUEZ, path, introspect=False)
        props = dbus.Interface(obj, PROPS_IFACE)
        props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(on), timeout=10)
        return {"ok": True, "message": "Bluetooth on" if on else "Bluetooth off"}
    except Exception as e:
        return {"ok": False, "message": f"Bluetooth error: {e}"}


def get_bluetooth_targets() -> list[Target]:
    """The adapter, plus one target per paired device while the radio is on."""
    objects = _managed_objects()
    if not objects:
        return []

    path = _adapter_path(objects)
    if not path:
        return []

    adapter = objects[path].get(ADAPTER_IFACE, {})
    powered = bool(adapter.get("Powered", False))

    # One action, not a toggle: "turn Bluetooth on" and "turn it off" are
    # different requests, and a toggle answers neither of them reliably when
    # the phone's view of the state is a second old.
    targets = [Target(
        id="bluetooth:adapter",
        kind="bluetooth",
        title="Bluetooth",
        subtitle=str(adapter.get("Alias") or adapter.get("Name") or ""),
        icon="🔵" if powered else "⚪",
        status="on" if powered else "off",
        actions=[
            Action(id="power_off", label="Turn off", kind="confirm")
            if powered
            else Action(id="power_on", label="Turn on")
        ],
    )]

    # With the radio off every device is unreachable, so listing them would be
    # a screen of buttons that all fail.
    if not powered:
        return targets

    devices = []
    for dev_path, interfaces in objects.items():
        props = interfaces.get(DEVICE_IFACE)
        if not props or not props.get("Paired"):
            continue
        connected = bool(props.get("Connected", False))
        devices.append(Target(
            id=f"bluetooth:{dev_path}",
            kind="bluetooth",
            title=_device_label(props),
            subtitle=str(props.get("Address") or ""),
            icon=_ICONS.get(str(props.get("Icon") or ""), "🔷"),
            status="connected" if connected else "paired",
            actions=[
                Action(id="disconnect", label="Disconnect")
                if connected
                else Action(id="connect", label="Connect")
            ],
        ))

    # Connected devices first: they are the ones with something to act on.
    devices.sort(key=lambda t: (t.status != "connected", t.title.casefold()))
    return targets + devices


def execute(target_spec: str, action_id: str) -> dict:
    """Run one Bluetooth action. `target_spec` is "adapter" or a device path."""
    if dbus is None:
        return {"ok": False, "message": "python-dbus is not importable; Bluetooth is unavailable"}

    try:
        if target_spec == "adapter":
            path = _adapter_path()
            if not path:
                return {"ok": False, "message": "No Bluetooth adapter found"}
            if action_id == "power_on":
                return _set_powered(path, True)
            if action_id == "power_off":
                return _set_powered(path, False)
            if action_id == "toggle":
                objects = _managed_objects()
                powered = bool(objects.get(path, {}).get(ADAPTER_IFACE, {}).get("Powered"))
                return _set_powered(path, not powered)
            return {"ok": False, "message": f"Unknown Bluetooth action: {action_id}"}

        if not target_spec.startswith("/org/bluez/"):
            return {"ok": False, "message": f"Invalid Bluetooth target: {target_spec}"}

        bus = dbus.SystemBus()
        obj = bus.get_object(BLUEZ, target_spec, introspect=False)
        device = dbus.Interface(obj, DEVICE_IFACE)

        if action_id == "connect":
            device.Connect(timeout=CONNECT_TIMEOUT)
            return {"ok": True, "message": "Connected"}
        if action_id == "disconnect":
            device.Disconnect(timeout=CONNECT_TIMEOUT)
            return {"ok": True, "message": "Disconnected"}
        return {"ok": False, "message": f"Unknown Bluetooth action: {action_id}"}

    except dbus.DBusException as e:
        name = ""
        try:
            name = e.get_dbus_name() or ""
        except Exception:
            pass
        if name in ("org.freedesktop.DBus.Error.ServiceUnknown",
                    "org.freedesktop.DBus.Error.NameHasNoOwner"):
            return {"ok": False, "message": "BlueZ is not running (systemctl start bluetooth)"}
        if name == "org.bluez.Error.Blocked":
            return {"ok": False, "message": "Bluetooth is blocked by rfkill (rfkill unblock bluetooth)"}
        if name == "org.bluez.Error.NotReady":
            return {"ok": False, "message": "Bluetooth adapter is not ready; turn the radio on first"}
        detail = str(e).strip().splitlines()[-1] if str(e).strip() else name
        return {"ok": False, "message": f"Bluetooth error: {detail}"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}
