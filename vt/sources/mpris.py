"""MPRIS (Media Player Remote Interfacing Specification) player detection and control."""

import re
from typing import Any, Optional
from vt.actions import ACCESS_DENIED, dbus_denied_message, dbus_error_name
from vt.model import Target, Action
from vt.sources.art import key_for as art_key

try:
    import dbus
except ImportError:
    dbus = None

ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"

# Players whose CanSeek is not to be believed.
#
# Firefox sets CanSeek=true but implements neither Seek nor SetPosition. The
# call returns without error and playback does not move; worse, it resets the
# player's reported Position to 0 and drops mpris:length from Metadata for the
# rest of the track, so the progress readout never comes back. A button that
# silently breaks the display it sits next to is worse than no button, so seek
# is withheld here and `seek_unavailable` says why. Firefox forks ship the same
# media backend and inherit the bug.
SEEK_LIARS = ("firefox", "librewolf", "waterfox", "floorp")

SEEK_UNAVAILABLE_REASON = (
    "This player reports it can seek but does not implement it; "
    "seeking would freeze its progress display. Seek in the page instead."
)


def _seek_is_trustworthy(bus_name: str, identity: str) -> bool:
    """False for players known to advertise CanSeek and not implement it."""
    probe = f"{bus_name} {identity}".lower()
    return not any(liar in probe for liar in SEEK_LIARS)

# Set the first time a player refuses to answer. A denial is indistinguishable
# from "no players are running" in the UI, so it has to be said out loud.
_denied_hint: Optional[str] = None


def access_denied_hint() -> Optional[str]:
    """Why players are missing, when the reason is a refused D-Bus call."""
    return _denied_hint


def reset_access_denied_hint() -> None:
    global _denied_hint
    _denied_hint = None


def _note_denial(e: Exception) -> None:
    """Record (and announce, once) a player refusing our property reads."""
    global _denied_hint
    if _denied_hint is not None or dbus_error_name(e) != ACCESS_DENIED:
        return
    _denied_hint = dbus_denied_message()
    print(f"  WARNING: {_denied_hint}")


def seconds_to_hms(seconds: float) -> str:
    """Convert seconds to H:MM:SS or M:SS format."""
    if seconds < 0:
        return "0:00"
    total = int(seconds)
    hours, minutes, secs = total // 3600, (total % 3600) // 60, total % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _get(props, iface: str, prop: str, default: Any = None) -> Any:
    """Read one property, returning `default` if the player does not expose it.

    Players vary in which optional properties they implement (Firefox has no
    Player.CanRaise, some have no Position). A single missing property must not
    discard the whole player.
    """
    try:
        return props.Get(iface, prop)
    except Exception as e:
        _note_denial(e)
        return default


def _clean_identity(identity: str) -> str:
    """Tidy the free-form Identity string players report.

    Firefox reports "Mozilla firefox_firefox"; snap/flatpak wrappers repeat the
    name with underscores. Collapse to the first distinct word, title-cased.
    """
    words: list[str] = []
    for chunk in identity.replace("_", " ").split():
        low = chunk.lower()
        if low not in [w.lower() for w in words]:
            words.append(chunk)
    if len(words) > 1 and words[0].lower() in ("mozilla", "the"):
        words = words[1:]
    return " ".join(words).title() if words else identity


def _first_artist(metadata) -> str:
    """xesam:artist is an array that may be absent, empty, or hold empty strings."""
    try:
        artists = metadata.get("xesam:artist") or []
        for a in artists:
            if str(a).strip():
                return str(a)
    except Exception:
        pass
    return ""


def get_mpris_targets() -> list[Target]:
    """Enumerate MPRIS media players on the session bus as Targets.

    Actions are derived from each player's capability flags, so a player that
    reports CanGoNext=0 (e.g. Firefox) never shows a Next button.
    """
    if not dbus:
        return []

    try:
        bus = dbus.SessionBus()
        names = [str(n) for n in bus.list_names()]
    except Exception:
        return []

    targets: list[Target] = []

    for name in names:
        if not name.startswith("org.mpris.MediaPlayer2."):
            continue

        try:
            # introspect=False: the Properties interface is named explicitly
            # below, so the extra Introspect call buys nothing -- and a
            # snap-confined player refuses it, which made dbus-python log an
            # "Introspect error" for every player on every 1 Hz refresh.
            obj = bus.get_object(name, "/org/mpris/MediaPlayer2", introspect=False)
            props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")

            # PlaybackStatus is the one property a real player must have.
            status_raw = _get(props, PLAYER_IFACE, "PlaybackStatus")
            if status_raw is None:
                continue

            metadata = _get(props, PLAYER_IFACE, "Metadata", {}) or {}
            app_name = _clean_identity(str(_get(props, ROOT_IFACE, "Identity", "") or ""))

            # Capabilities. CanRaise is on the ROOT interface, not Player.
            can_play = bool(_get(props, PLAYER_IFACE, "CanPlay", False))
            can_pause = bool(_get(props, PLAYER_IFACE, "CanPause", False))
            can_next = bool(_get(props, PLAYER_IFACE, "CanGoNext", False))
            can_prev = bool(_get(props, PLAYER_IFACE, "CanGoPrevious", False))
            can_seek = bool(_get(props, PLAYER_IFACE, "CanSeek", False))
            seek_trusted = _seek_is_trustworthy(name, app_name)
            seek_unavailable = can_seek and not seek_trusted
            can_seek = can_seek and seek_trusted
            can_raise = bool(_get(props, ROOT_IFACE, "CanRaise", False))

            # MPRIS reports time in microseconds; convert at the boundary.
            position_us = _get(props, PLAYER_IFACE, "Position", 0) or 0
            length_us = metadata.get("mpris:length", 0) or 0
            position_sec = float(position_us) / 1e6
            length_sec = float(length_us) / 1e6

            art_url = str(metadata.get("mpris:artUrl") or "")
            title = str(metadata.get("xesam:title") or "Unknown")
            artist = _first_artist(metadata)
            url = str(metadata.get("xesam:url") or "")

            # Subtitle: "Firefox · youtube.com" or "Spotify · Daft Punk"
            parts = []
            if app_name:
                parts.append(app_name)
            if artist:
                parts.append(artist)
            elif url:
                m = re.search(r"(?:https?://)?(?:www\.)?([^/]+)", url)
                if m:
                    parts.append(m.group(1))
            subtitle = " · ".join(parts)

            status = {"Playing": "playing", "Paused": "paused", "Stopped": "stopped"}.get(
                str(status_raw), str(status_raw).lower()
            )

            actions: list[Action] = []
            if can_play or can_pause:
                actions.append(
                    Action(id="play_pause", label="Pause" if status == "playing" else "Play")
                )
            if can_prev:
                actions.append(Action(id="prev", label="Previous"))
            if can_next:
                actions.append(Action(id="next", label="Next"))
            if can_seek:
                actions.append(Action(id="seek_back", label="<- 10s"))
                actions.append(Action(id="seek_fwd", label="10s ->"))
            if can_play or can_pause:
                actions.append(Action(id="stop", label="Stop"))
            if can_raise:
                actions.append(Action(id="raise", label="Show window"))

            icon = {"playing": "|>", "paused": "||", "stopped": "[]"}.get(status, "~")

            targets.append(
                Target(
                    id=f"mpris:{name}",
                    kind="player",
                    title=title,
                    subtitle=subtitle,
                    icon=icon,
                    status=status,
                    position=position_sec if length_sec > 0 else None,
                    length=length_sec if length_sec > 0 else None,
                    note=SEEK_UNAVAILABLE_REASON if seek_unavailable else "",
                    art=art_key(art_url),
                    actions=actions,
                )
            )

        except Exception:
            # A player can vanish mid-iteration; skip only that one.
            continue

    return targets
