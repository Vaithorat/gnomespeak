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
from vt.procs import run_all
from vt.sources import ring as ring_source

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

_NIGHT_LIGHT_SCHEMA = "org.gnome.settings-daemon.plugins.color"
_NIGHT_LIGHT_KEY = "night-light-enabled"

_THEME_SCHEMA = "org.gnome.desktop.interface"
_THEME_KEY = "color-scheme"
_THEME_DARK = "prefer-dark"
_THEME_LIGHT = "default"

GSM_BUS = "org.gnome.SessionManager"
GSM_PATH = "/org/gnome/SessionManager"
GSM_IFACE = "org.gnome.SessionManager"
# Flag bits for Inhibit(); 8 = inhibit the idle/screensaver from firing.
_INHIBIT_IDLE = 8

# The cookie identifying our own inhibitor, so Uninhibit knows what to lift.
# Module-level and unpersisted: a server restart drops the inhibitor along
# with the process that would otherwise have to renew it anyway.
_awake_cookie: int | None = None


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


# Below this, and discharging, the phone is told once. The PC's own warning is
# on the screen the user has walked away from, which is the whole point.
LOW_BATTERY_PERCENT = 15


def battery_state() -> dict:
    """{percent, charging, present} for the PC's own battery, or {} when none."""
    props = _battery_properties()
    if not props.get("IsPresent"):
        return {}
    code = int(props.get("State", 0))
    return {
        "percent": int(round(float(props.get("Percentage", 0)))),
        "charging": code in (_STATE_CHARGING, 5),
        "present": True,
    }


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


def _read_setting(schema: str, key: str) -> str | None:
    """One `gsettings get`, or None when it could not be read."""
    return _read_settings([(schema, key)])[0]


def _read_settings(pairs: list) -> list:
    """Several `gsettings get` reads at once, in the order asked.

    Each one is a process that spends its whole life waiting, and the snapshot
    reads three of them every second. Run together they cost one wait rather
    than three.
    """
    results = run_all([["gsettings", "get", schema, key] for schema, key in pairs])
    return [out if code == 0 else None for code, out in results]


def _desktop_settings() -> tuple:
    """(banners shown, night light on, theme is dark). None where unreadable."""
    banners, night_light, theme = _read_settings([
        (_DND_SCHEMA, _DND_KEY),
        (_NIGHT_LIGHT_SCHEMA, _NIGHT_LIGHT_KEY),
        (_THEME_SCHEMA, _THEME_KEY),
    ])
    return (
        None if banners is None else banners.strip() == "true",
        None if night_light is None else night_light.strip() == "true",
        None if theme is None else _THEME_DARK in theme,
    )


def _banners_shown() -> bool | None:
    """True when notification banners are on, None when GSettings is unreadable."""
    value = _read_setting(_DND_SCHEMA, _DND_KEY)
    return None if value is None else value.strip() == "true"


def _night_light_on() -> bool | None:
    """True when night light is on, None when GSettings is unreadable."""
    value = _read_setting(_NIGHT_LIGHT_SCHEMA, _NIGHT_LIGHT_KEY)
    return None if value is None else value.strip() == "true"


def _theme_is_dark() -> bool | None:
    """True when the GNOME color scheme prefers dark, None when unreadable."""
    value = _read_setting(_THEME_SCHEMA, _THEME_KEY)
    return None if value is None else _THEME_DARK in value


# Offered as fixed choices rather than a number the phone types: a timer is
# set one-handed, and "30" and "300" are one keystroke apart.
SLEEP_MINUTES = (15, 30, 60)


def _timer_targets() -> list:
    """A row per pending timer, so nothing the PC will do later is invisible."""
    from vt.schedule import remaining_words, scheduler

    rows = []
    for job in scheduler().jobs():
        rows.append(Target(
            id=f"timer:{job['id']}",
            kind="system",
            title=job["label"],
            subtitle="Scheduled on the PC",
            icon="⏳",
            status=remaining_words(job["remaining"]),
            actions=[Action(id="cancel", label="Cancel")],
        ))
    return rows


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
            Action(id="awake_off" if _awake_cookie is not None else "awake_on",
                   label="Let it sleep" if _awake_cookie is not None else "Keep awake"),
            Action(id="suspend", label="Suspend"),
            *[Action(id=f"suspend_in_{m}", label=f"Suspend in {m} min")
              for m in SLEEP_MINUTES],
            Action(id="restart", label="Restart", kind="confirm"),
            Action(id="shutdown", label="Shut down", kind="confirm"),
        ],
    ))

    targets.extend(_timer_targets())

    noisy = ring_source.ringing()
    targets.append(Target(
        id="system:ring",
        kind="system",
        title="Ring this PC",
        subtitle="Play an alert and show a banner",
        icon="🔔",
        status="ringing" if noisy else "ready",
        # One button either way: a stop button that appears only while the PC
        # is ringing is the one that can never be pressed by mistake.
        actions=[Action(id="stop", label="Stop ringing")] if noisy
        else [Action(id="ring", label="Ring")],
    ))

    level = _brightness()
    banners, night_light, dark_theme = _desktop_settings()
    if level >= 0 or night_light is not None or dark_theme is not None:
        actions_list = []
        if level >= 0:
            actions_list.extend([
                Action(id="brightness", label=f"Brightness ({level}%)",
                       kind="slider", value=level / 100),
                Action(id="brightness_down", label="Dimmer"),
                Action(id="brightness_up", label="Brighter"),
            ])
        if night_light is not None:
            actions_list.append(Action(
                id="night_light_off" if night_light else "night_light_on",
                label="Night light off" if night_light else "Night light on",
            ))
        if dark_theme is not None:
            actions_list.append(Action(
                id="theme_light" if dark_theme else "theme_dark",
                label="Light theme" if dark_theme else "Dark theme",
            ))
        status_bits = [f"{level}%"] if level >= 0 else []
        if night_light:
            status_bits.append("night light")
        status_bits.append("dark" if dark_theme else "light" if dark_theme is not None else "")
        targets.append(Target(
            id="system:display",
            kind="system",
            title="Display",
            icon="☀",
            status=" · ".join(b for b in status_bits if b),
            actions=actions_list,
        ))

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


def _set_night_light(enabled: bool) -> dict:
    try:
        result = subprocess.run(
            ["gsettings", "set", _NIGHT_LIGHT_SCHEMA, _NIGHT_LIGHT_KEY,
             "true" if enabled else "false"],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0:
            return {"ok": False, "message": (result.stderr or "gsettings failed").strip()}
        return {"ok": True, "message": "Night light on" if enabled else "Night light off"}
    except FileNotFoundError:
        return {"ok": False, "message": "gsettings not found (install glib2 tools)"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def _set_theme(dark: bool) -> dict:
    try:
        result = subprocess.run(
            ["gsettings", "set", _THEME_SCHEMA, _THEME_KEY,
             _THEME_DARK if dark else _THEME_LIGHT],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode != 0:
            return {"ok": False, "message": (result.stderr or "gsettings failed").strip()}
        return {"ok": True, "message": "Dark theme" if dark else "Light theme"}
    except FileNotFoundError:
        return {"ok": False, "message": "gsettings not found (install glib2 tools)"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def _set_awake(enabled: bool) -> dict:
    """Toggle a GNOME SessionManager idle inhibitor.

    This is the same mechanism a video player uses to stop the screen locking
    mid-playback -- session-scoped, no polkit prompt, works identically under
    Wayland and X11 because it never touches input or the compositor.
    """
    global _awake_cookie
    if dbus is None:
        return {"ok": False, "message": "python-dbus is not importable; keep-awake is unavailable"}
    try:
        bus = dbus.SessionBus()
        obj = bus.get_object(GSM_BUS, GSM_PATH, introspect=False)
        manager = dbus.Interface(obj, GSM_IFACE)
        if enabled:
            if _awake_cookie is not None:
                return {"ok": True, "message": "Already keeping the screen awake"}
            cookie = manager.Inhibit(
                "gnomespeak", dbus.UInt32(0), "Remote session active",
                dbus.UInt32(_INHIBIT_IDLE), timeout=5,
            )
            _awake_cookie = int(cookie)
            return {"ok": True, "message": "Keeping the screen awake"}
        if _awake_cookie is None:
            return {"ok": True, "message": "Screen can sleep normally"}
        manager.Uninhibit(dbus.UInt32(_awake_cookie), timeout=5)
        _awake_cookie = None
        return {"ok": True, "message": "Screen can sleep normally"}
    except Exception as e:
        detail = str(e).strip().splitlines()[-1] if str(e).strip() else e.__class__.__name__
        return {"ok": False, "message": f"Keep-awake unavailable: {detail}"}


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
        return _execute_power(action_id)

    if target_spec == "ring":
        if action_id == "ring":
            return ring_source.ring()
        if action_id in ("stop", "silence"):
            return ring_source.stop()
        return {"ok": False, "message": f"Unknown ring action: {action_id}"}

    if target_spec == "display":
        return _execute_display(action_id, value)

    if target_spec == "notifications":
        return _execute_notifications(action_id)

    return {"ok": False, "message": f"Unknown system target: {target_spec}"}


def _execute_power(action_id: str) -> dict:
    if action_id.startswith("suspend_in_"):
        from vt.schedule import scheduler

        minutes = action_id[len("suspend_in_"):]
        if not minutes.isdigit():
            return {"ok": False, "message": f"Unknown power action: {action_id}"}
        return scheduler().add(
            "system:power", "suspend", int(minutes) * 60, label="Suspend"
        )
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
    if action_id == "awake_on":
        return _set_awake(True)
    if action_id == "awake_off":
        return _set_awake(False)
    return {"ok": False, "message": f"Unknown power action: {action_id}"}


def _execute_display(action_id: str, value: float | None) -> dict:
    if action_id == "brightness":
        if value is None:
            return {"ok": False, "message": "Brightness action requires a value"}
        return _set_brightness(value)
    if action_id == "brightness_up":
        return _step_brightness(True)
    if action_id == "brightness_down":
        return _step_brightness(False)
    if action_id == "night_light_on":
        return _set_night_light(True)
    if action_id == "night_light_off":
        return _set_night_light(False)
    if action_id == "theme_dark":
        return _set_theme(True)
    if action_id == "theme_light":
        return _set_theme(False)
    return {"ok": False, "message": f"Unknown display action: {action_id}"}


def _execute_notifications(action_id: str) -> dict:
    if action_id == "dnd_on":
        return _set_dnd(True)
    if action_id == "dnd_off":
        return _set_dnd(False)
    if action_id == "toggle":
        return _set_dnd(_banners_shown() is not False)
    return {"ok": False, "message": f"Unknown notifications action: {action_id}"}
