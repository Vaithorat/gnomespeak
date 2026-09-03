"""Wi-Fi radio control through NetworkManager.

Mirrors bluetooth.py's adapter target: one on/off switch, no scanning or
connecting to new networks. Picking a network from a phone with no way to
enter its passphrase is how people end up locked off their own Wi-Fi, so this
only ever touches the radio switch -- the same one the desktop's own quick
settings offers.
"""

import subprocess
import time

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


# Saved networks change about once a month and cost a subprocess to read, so
# the list is cached; the snapshot runs once a second and the answer does not.
NETWORKS_TTL = 30.0
_networks = ([], 0.0)

# A phone screen has room for a handful of buttons, not a year of hotel Wi-Fi.
MAX_NETWORKS = 8


def saved_networks(force: bool = False) -> list:
    """Saved Wi-Fi connections as [{name, active}], nearest thing first.

    NetworkManager's own list, in its own order: the one in use first, then
    whatever `nmcli` reports, which is roughly how recently they were used.
    """
    global _networks
    cached, taken = _networks
    if not force and taken and time.monotonic() - taken < NETWORKS_TTL:
        return cached

    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE,ACTIVE", "connection", "show"],
            capture_output=True, text=True, timeout=3,
        )
    except Exception:
        _networks = ([], time.monotonic())
        return []
    if result.returncode != 0:
        _networks = ([], time.monotonic())
        return []

    networks = []
    for line in result.stdout.splitlines():
        # NAME may contain a colon, so split from the right: the last two
        # fields are the ones with a fixed shape.
        parts = line.rsplit(":", 2)
        if len(parts) != 3:
            continue
        name, kind, active = parts
        if "wireless" not in kind or not name:
            continue
        networks.append({"name": name, "active": active == "yes"})

    networks.sort(key=lambda n: (not n["active"],))
    _networks = (networks, time.monotonic())
    return networks


def connect_network(name: str) -> dict:
    """Bring up a saved Wi-Fi connection by name."""
    known = {n["name"] for n in saved_networks(force=True)}
    if name not in known:
        # The name comes from a snapshot the phone may have been holding for a
        # while, and `nmcli connection up` would happily take anything.
        return {"ok": False, "message": "That network is not saved on this PC"}
    try:
        result = subprocess.run(
            ["nmcli", "connection", "up", "id", name],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        return {"ok": False, "message": "nmcli not found (NetworkManager is required)"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": f"Connecting to {name} timed out"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}

    saved_networks(force=True)
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        return {"ok": False, "message": detail[-1] if detail else f"Could not join {name}"}
    return {"ok": True, "message": f"Joined {name}"}


def get_network_targets() -> list[Target]:
    """The Wi-Fi radio as a single on/off target, absent when NM is unreachable."""
    props = _properties()
    if props is None:
        return []

    enabled = bool(props.get("WirelessEnabled", False))
    connected = enabled and int(props.get("Connectivity", 0)) == _CONNECTIVITY_FULL

    networks = saved_networks() if enabled else []
    current = next((n["name"] for n in networks if n["active"]), "")
    actions = [
        Action(id="wifi_off", label="Turn off") if enabled
        else Action(id="wifi_on", label="Turn on")
    ]
    # Only the ones that are not already in use: joining the network you are on
    # is a button that does nothing.
    actions.extend(
        Action(id=f"join_{index}", label=f"Join {n['name']}")
        for index, n in enumerate(networks[:MAX_NETWORKS]) if not n["active"]
    )

    return [Target(
        id="network:wifi",
        kind="system",
        title="Wi-Fi",
        subtitle=current,
        icon="📶" if connected else ("📡" if enabled else "⚪"),
        status=(current or "connected") if connected else ("on" if enabled else "off"),
        actions=actions,
    )]


def _join(action_id: str) -> dict:
    """Join the saved network at the position this action names."""
    index = action_id[len("join_"):]
    if not index.isdigit():
        return {"ok": False, "message": f"Unknown network action: {action_id}"}
    networks = saved_networks()[:MAX_NETWORKS]
    if int(index) >= len(networks):
        # The phone was holding a snapshot from before the list changed.
        return {"ok": False, "message": "That network is not there any more"}
    return connect_network(networks[int(index)]["name"])


def execute(target_spec: str, action_id: str) -> dict:
    """Run one network action. `target_spec` is always "wifi" for now."""
    if target_spec != "wifi":
        return {"ok": False, "message": f"Unknown network target: {target_spec}"}
    if action_id.startswith("join_"):
        return _join(action_id)
    if dbus is None:
        return {"ok": False, "message": "python-dbus is not importable; Wi-Fi control is unavailable"}
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
