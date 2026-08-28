"""Session and power control: lock, suspend, brightness, do-not-disturb.

All of it goes through services that are already part of the desktop --
logind for power, gnome-settings-daemon for backlight, GSettings for
notifications -- so nothing here needs the GNOME extension or input synthesis,
and it behaves identically under Wayland and X11.

Reboot and shutdown are `confirm` actions: a mis-heard word should not be able
to take the machine down mid-sentence.
"""

import subprocess

from vt.model import Target, Action

try:
    import dbus
except ImportError:
    dbus = None

LOGIN1 = "org.freedesktop.login1"
LOGIN1_PATH = "/org/freedesktop/login1"
LOGIN1_MANAGER = "org.freedesktop.login1.Manager"

UPOWER = "org.freedesktop.UPower"
UPOWER_DISPLAY_DEVICE = "/org/freedesktop/UPower/devices/DisplayDevice"
UPOWER_DEVICE_IFACE = "org.freedesktop.UPower.Device"

GSD_POWER = "org.gnome.SettingsDaemon.Power"
GSD_POWER_PATH = "/org/gnome/SettingsDaemon/Power"
GSD_SCREEN_IFACE = "org.gnome.SettingsDaemon.Power.Screen"

PROPS_IFACE = "org.freedesktop.DBus.Properties"

# UPower's BatteryState enum, for the states worth naming.
_STATE_CHARGING = 1
_STATE_DISCHARGING = 2
_BATTERY_STATE = {
    _STATE_CHARGING: "charging",
    _STATE_DISCHARGING: "discharging",
    3: "empty",
    4: "full",
    5: "charging",
    6: "discharging",
}

_DND_SCHEMA = "org.gnome.desktop.notifications"
_DND_KEY = "show-banners"


def _session_property(bus_name, path, iface, prop, default=None):
    """Read one D-Bus property, returning `default` if anything goes wrong."""
    if dbus is None:
        return default
    try:
        bus = dbus.SystemBus() if bus_name == UPOWER else dbus.SessionBus()
        obj = bus.get_object(bus_name, path, introspect=False)
        return dbus.Interface(obj, PROPS_IFACE).Get(iface, prop, timeout=5)
    except Exception:
        return default


def _format_duration(seconds: int) -> str:
    hours, minutes = divmod(int(seconds) // 60, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


def _battery_properties() -> dict:
    """Every property of UPower's aggregate battery, or {} when there is none."""
    if dbus is None:
        return {}
    try:
        bus = dbus.SystemBus()
        obj = bus.get_object(UPOWER, UPOWER_DISPLAY_DEVICE, introspect=False)
        return dbus.Interface(obj, PROPS_IFACE).GetAll(UPOWER_DEVICE_IFACE, timeout=5)
    except Exception:
        return {}


def battery_summary() -> str:
    """Charge, state and time remaining, or "" when there is no battery.

    UPower's DisplayDevice is the aggregate the desktop's own indicator uses,
    so it already accounts for machines with two batteries or none.
    """
    props = _battery_properties()
    if not props.get("IsPresent"):
        return ""

    percent = int(round(float(props.get("Percentage", 0))))
    code = int(props.get("State", 0))
    parts = [f"{percent}%"]
    state = _BATTERY_STATE.get(code, "")
    if state:
        parts.append(state)

    # Only a battery that is actively charging or draining has a countdown.
    # A full one still reports a TimeToEmpty, and it is nonsense: this machine
    # says 8391600 seconds, which rendered as "2331h left".
    if code == _STATE_CHARGING:
        remaining, suffix = int(props.get("TimeToFull", 0) or 0), " to full"
    elif code == _STATE_DISCHARGING:
        remaining, suffix = int(props.get("TimeToEmpty", 0) or 0), " left"
    else:
        remaining, suffix = 0, ""
    if remaining > 0:
        parts.append(_format_duration(remaining) + suffix)

    return " · ".join(parts)


def _brightness() -> int:
    """Backlight percentage, or -1 when this machine has no controllable backlight."""
    value = _session_property(GSD_POWER, GSD_POWER_PATH, GSD_SCREEN_IFACE, "Brightness", -1)
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _banners_shown() -> bool | None:
    """True when notification banners are on, None when GSettings is unreadable."""
    try:
        result = subprocess.run(
            ["gsettings", "get", _DND_SCHEMA, _DND_KEY],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() == "true"
    except Exception:
        return None


def get_system_targets() -> list[Target]:
    """Power, backlight and do-not-disturb controls."""
    targets = []

    battery = battery_summary()
    targets.append(Target(
        id="system:power",
        kind="system",
        title="Power",
        subtitle=battery,
        icon="⏻",
        status=battery.split(" · ")[0] if battery else "ready",
        actions=[
            Action(id="lock", label="Lock screen"),
            Action(id="suspend", label="Suspend"),
            Action(id="restart", label="Restart", kind="confirm"),
            Action(id="shutdown", label="Shut down", kind="confirm"),
        ],
    ))

    level = _brightness()
    if level >= 0:
        targets.append(Target(
            id="system:display",
            kind="system",
            title="Display",
            icon="☀",
            status=f"{level}%",
            actions=[
                Action(id="brightness", label=f"Brightness ({level}%)",
                       kind="slider", value=level / 100),
                Action(id="brightness_down", label="Dimmer"),
                Action(id="brightness_up", label="Brighter"),
            ],
        ))

    banners = _banners_shown()
    if banners is not None:
        targets.append(Target(
            id="system:notifications",
            kind="system",
            title="Notifications",
            icon="🔔" if banners else "🔕",
            status="on" if banners else "do not disturb",
            actions=[Action(
                id="dnd_on" if banners else "dnd_off",
                label="Do not disturb" if banners else "Allow notifications",
            )],
        ))

    return targets


def _login1_call(method: str, message: str) -> dict:
    if dbus is None:
        return {"ok": False, "message": "python-dbus is not importable; power control is unavailable"}
    try:
        bus = dbus.SystemBus()
        obj = bus.get_object(LOGIN1, LOGIN1_PATH, introspect=False)
        manager = dbus.Interface(obj, LOGIN1_MANAGER)
        # interactive=True lets logind raise a polkit prompt on the desktop
        # rather than refusing outright when a second user is logged in.
        getattr(manager, method)(dbus.Boolean(True), timeout=10)
        return {"ok": True, "message": message}
    except Exception as e:
        detail = str(e).strip().splitlines()[-1] if str(e).strip() else e.__class__.__name__
        return {"ok": False, "message": f"{method} failed: {detail}"}


def _lock() -> dict:
    """Lock the screen, preferring the screensaver the session actually runs."""
    if dbus is not None:
        try:
            bus = dbus.SessionBus()
            obj = bus.get_object("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", introspect=False)
            dbus.Interface(obj, "org.gnome.ScreenSaver").Lock(timeout=5)
            return {"ok": True, "message": "Screen locked"}
        except Exception:
            pass
    try:
        result = subprocess.run(["loginctl", "lock-session"], capture_output=True, timeout=5)
        if result.returncode == 0:
            return {"ok": True, "message": "Screen locked"}
        return {"ok": False, "message": "loginctl could not lock the session"}
    except FileNotFoundError:
        return {"ok": False, "message": "No screensaver on the bus and loginctl is not installed"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def _step_brightness(up: bool) -> dict:
    if dbus is None:
        return {"ok": False, "message": "python-dbus is not importable; brightness is unavailable"}
    try:
        bus = dbus.SessionBus()
        obj = bus.get_object(GSD_POWER, GSD_POWER_PATH, introspect=False)
        screen = dbus.Interface(obj, GSD_SCREEN_IFACE)
        # StepUp/StepDown use the same increment as the keyboard's own
        # brightness keys, and return the level they landed on.
        level = screen.StepUp(timeout=5) if up else screen.StepDown(timeout=5)
        return {"ok": True, "message": f"Brightness {int(level)}%"}
    except Exception as e:
        detail = str(e).strip().splitlines()[-1] if str(e).strip() else e.__class__.__name__
        return {"ok": False, "message": f"Brightness unavailable: {detail}"}


def _set_brightness(value: float) -> dict:
    if dbus is None:
        return {"ok": False, "message": "python-dbus is not importable; brightness is unavailable"}
    percent = max(1, min(100, int(round(value * 100))))
    try:
        bus = dbus.SessionBus()
        obj = bus.get_object(GSD_POWER, GSD_POWER_PATH, introspect=False)
        dbus.Interface(obj, PROPS_IFACE).Set(
            GSD_SCREEN_IFACE, "Brightness", dbus.Int32(percent), timeout=5
        )
        return {"ok": True, "message": f"Brightness {percent}%"}
    except Exception as e:
        detail = str(e).strip().splitlines()[-1] if str(e).strip() else e.__class__.__name__
        return {"ok": False, "message": f"Brightness unavailable: {detail}"}


def _set_dnd(enabled: bool) -> dict:
    """Do-not-disturb is the absence of banners, which is a GSettings key."""
    try:
        result = subprocess.run(
            ["gsettings", "set", _DND_SCHEMA, _DND_KEY, "false" if enabled else "true"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0:
            return {"ok": False, "message": (result.stderr or "gsettings failed").strip()}
        return {"ok": True, "message": "Do not disturb on" if enabled else "Notifications on"}
    except FileNotFoundError:
        return {"ok": False, "message": "gsettings not found (install glib2 tools)"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def execute(target_spec: str, action_id: str, value: float | None = None) -> dict:
    """Run one system action. `target_spec` is "power", "display" or "notifications"."""
    if target_spec == "power":
        if action_id == "lock":
            return _lock()
        if action_id == "suspend":
            return _login1_call("Suspend", "Suspending")
        if action_id == "restart":
            return _login1_call("Reboot", "Restarting")
        if action_id == "shutdown":
            return _login1_call("PowerOff", "Shutting down")
        if action_id == "battery":
            summary = battery_summary()
            return {"ok": bool(summary), "message": summary or "No battery on this machine"}
        return {"ok": False, "message": f"Unknown power action: {action_id}"}

    if target_spec == "display":
        if action_id == "brightness":
            if value is None:
                return {"ok": False, "message": "Brightness action requires a value"}
            return _set_brightness(value)
        if action_id == "brightness_up":
            return _step_brightness(True)
        if action_id == "brightness_down":
            return _step_brightness(False)
        return {"ok": False, "message": f"Unknown display action: {action_id}"}

    if target_spec == "notifications":
        if action_id == "dnd_on":
            return _set_dnd(True)
        if action_id == "dnd_off":
            return _set_dnd(False)
        if action_id == "toggle":
            return _set_dnd(_banners_shown() is not False)
        return {"ok": False, "message": f"Unknown notifications action: {action_id}"}

    return {"ok": False, "message": f"Unknown system target: {target_spec}"}
