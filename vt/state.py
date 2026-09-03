"""Assemble the complete state snapshot from all sources."""

import time
from concurrent.futures import ThreadPoolExecutor
from vt.model import Snapshot, Target, Action
from vt.sources.mpris import get_mpris_targets
from vt.sources.audio import get_audio_targets
from vt.sources.apps import get_app_targets
from vt.sources.windows import get_extension_targets, get_window_targets, list_windows
from vt.sources.youtube import get_youtube_target
from vt.sources.youtube_player import get_youtube_player_target
from vt.sources.bluetooth import get_bluetooth_targets
from vt.sources.network import get_network_targets
from vt.sources.streaming import get_streaming_targets
from vt.sources.keypads import get_keypad_targets
from vt.sources.disks import get_disk_targets
from vt.sources.monitor import get_monitor_targets
from vt.sources.system import get_system_targets
from vt.sources.workspaces import get_workspace_targets
from vt.commands import CommandsConfig


def _refresh_windows():
    """Windows and the focused application's key pad, from one window list."""
    windows = list_windows()
    return get_window_targets(windows) + get_keypad_targets(windows)


# Which source owns which targets. After an action the phone is waiting on one
# row, and collecting every source to answer for one of them is most of the
# latency the live channel has: this is the fast path, and the ordinary
# once-a-second collection right behind it is what corrects anything a source
# changed that nobody asked about.
_REFRESH_SOURCES = (
    (("player:", "youtube_player:"), lambda: get_mpris_targets()),
    (("system:audio", "system:mic", "audio:", "stream:"), lambda: get_audio_targets()),
    (("window:", "keys:"), _refresh_windows),
    (("workspace:",), lambda: get_workspace_targets()),
    (("bluetooth:",), lambda: get_bluetooth_targets()),
    (("network:",), lambda: get_network_targets()),
    (("app:",), lambda: get_app_targets()),
    (("disk:",), lambda: get_disk_targets()),
    (("system:machine",), lambda: get_monitor_targets()),
    # Everything else on the system kind: power, display, notifications, ring,
    # and the timer rows that live with them.
    (("system:", "timer:"), lambda: get_system_targets()),
)


def refresh_for(target_id: str):
    """(prefixes, fresh targets) for the source that owns a target, or None.

    The prefixes say what the caller may replace: a source answers for all of
    its own rows, so a stream that ended is removed rather than left behind.
    """
    for prefixes, collect in _REFRESH_SOURCES:
        if any(target_id.startswith(prefix) for prefix in prefixes):
            try:
                return prefixes, list(collect())
            except Exception:
                return None
    return None


# Players first, then the things that come and go, then the fixtures. A
# partial refresh sorts by the same key, so a fast answer never hands the phone
# a different order for a second.
_KIND_ORDER = {
    "player": 0, "youtube_player": 0, "window": 1, "workspace": 2, "app": 3,
    "streaming": 4, "bluetooth": 5, "system": 6, "youtube": 7, "command": 8,
}


def snapshot_order(target):
    return (_KIND_ORDER.get(target.kind, 99), target.title)


def get_snapshot() -> Snapshot:
    """Gather all targets from all sources into a single snapshot.

    Gathers: MPRIS players, windows, workspaces, apps, streaming shortcuts,
    Bluetooth, system controls and configured commands. Sources are gathered in
    order of importance and sorted by kind.

    Installed apps and Steam games are deliberately absent: there are hundreds
    of them and they change about once a week, so they are served from
    /api/apps on demand instead of pushed to every phone every second.
    """
    targets = []

    # Two sources that touch no D-Bus: the app scan reads /proc, and the audio
    # rows are `wpctl` processes that spend their lives waiting. They start
    # first and run while the D-Bus sources -- which must stay on this thread,
    # because they share one connection -- take their turn. Both are spliced
    # back at their own positions, so the snapshot reads as it always did.
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="vt-collect") as pool:
        apps = pool.submit(get_app_targets)
        audio = pool.submit(get_audio_targets)

        # MPRIS players (highest value)
        targets.extend(get_mpris_targets())

        # YouTube player (if a video is playing in browser)
        yt_player = get_youtube_player_target()
        if yt_player:
            targets.append(yt_player)

        # Windows (GNOME extension; optional)
        window_list = list_windows()
        targets.extend(get_window_targets(window_list))

        # The keys the focused application answers to, read from the same
        # window list rather than asking the extension a second time.
        targets.extend(get_keypad_targets(window_list))

        # Workspaces (same extension; only when there is more than one)
        targets.extend(get_workspace_targets())

        # Where the running apps go once the scan finishes. Collecting them
        # here would put this thread back to waiting with the slowest sources
        # still ahead of it; the rows are spliced in below instead, so the
        # snapshot reads the same as it always did.
        apps_at = len(targets)

        # YouTube (if available)
        yt = get_youtube_target()
        if yt.actions:
            targets.append(yt)

        # Streaming shortcuts (a fixed, short list)
        targets.extend(get_streaming_targets())

        # Bluetooth radio and paired devices
        targets.extend(get_bluetooth_targets())

        # System audio (always useful), collected below with the apps
        audio_at = len(targets)

        # Wi-Fi radio
        targets.extend(get_network_targets())

        # Power, brightness and do-not-disturb
        targets.extend(get_system_targets())

        # Removable drives, when there are any.
        targets.extend(get_disk_targets())

        # What the machine itself is doing. All reads, and the row is left out
        # entirely on the first tick, when the CPU figure would be a lie.
        targets.extend(get_monitor_targets())

        # Says so once when the GNOME extension is missing, rather than letting
        # every feature that needs it fail on its own.
        targets.extend(get_extension_targets())

        # Later position first: splicing the earlier one would move the later.
        targets[audio_at:audio_at] = audio.result()
        targets[apps_at:apps_at] = apps.result()

    # Configured commands
    config = CommandsConfig()
    for cmd in config.get_commands():
        target = Target(
            id=f"command:{cmd['id']}",
            kind="command",
            title=cmd["label"],
            icon=cmd.get("icon", "⚙"),
            status="configured",
            actions=[
                Action(
                    id="run",
                    label="Run",
                    kind="confirm" if cmd.get("confirm") else "button",
                )
            ],
        )
        targets.append(target)

    targets.sort(key=snapshot_order)

    snapshot = Snapshot(targets=targets, ts=time.time())
    return snapshot
