"""Window management via GNOME Shell extension."""

import json
from vt.model import Target, Action

try:
    import dbus
except ImportError:
    dbus = None


def get_window_targets() -> list[Target]:
    """Get open windows via the GNOME extension D-Bus interface.

    The extension is optional and may not be present or enabled.
    This function returns [] gracefully if it is absent.
    """
    if not dbus:
        return []

    try:
        bus = dbus.SessionBus()
        # introspect=False: the interface is named explicitly on the next line,
        # so the Introspect round trip is pure cost -- once per second, forever.
        obj = bus.get_object(
            "org.gnome.Shell.Extensions.VoiceTalk",
            "/org/gnome/Shell/Extensions/VoiceTalk",
            introspect=False,
        )
        interface = dbus.Interface(obj, "org.gnome.Shell.Extensions.VoiceTalk")
        windows_json = interface.List()
        windows = json.loads(windows_json)

        targets = []
        for w in windows:
            # Windows carry Focus and Close and nothing else. Playback belongs
            # to the player that owns the media, not to the window frame around
            # it: a YouTube tab is controlled through Firefox's MPRIS player,
            # which reports its own capabilities and works under Wayland.
            actions = [
                Action(id="focus", label="Focus"),
                Action(id="close", label="Close", kind="confirm"),
            ]
            target = Target(
                id=f"window:{w.get('id')}",
                kind="window",
                title=w.get("title", "Unknown"),
                icon="▭",
                status="running" if not w.get("minimized") else "minimized",
                actions=actions,
            )
            targets.append(target)
        return targets

    except dbus.DBusException:
        # Extension not present or not activated
        return []
    except Exception:
        return []
