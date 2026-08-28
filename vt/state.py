"""Assemble the complete state snapshot from all sources."""

import time
from vt.model import Snapshot, Target, Action
from vt.sources.mpris import get_mpris_targets
from vt.sources.audio import get_audio_targets
from vt.sources.apps import get_app_targets
from vt.sources.windows import get_window_targets
from vt.sources.youtube import get_youtube_target
from vt.sources.youtube_player import get_youtube_player_target
from vt.sources.bluetooth import get_bluetooth_targets
from vt.sources.streaming import get_streaming_targets
from vt.sources.system import get_system_targets
from vt.sources.workspaces import get_workspace_targets
from vt.commands import CommandsConfig


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

    # MPRIS players (highest value)
    targets.extend(get_mpris_targets())

    # YouTube player (if a video is playing in browser)
    yt_player = get_youtube_player_target()
    if yt_player:
        targets.append(yt_player)

    # Windows (GNOME extension; optional)
    targets.extend(get_window_targets())

    # Workspaces (same extension; only when there is more than one)
    targets.extend(get_workspace_targets())

    # Running apps
    targets.extend(get_app_targets())

    # YouTube (if available)
    yt = get_youtube_target()
    if yt.actions:
        targets.append(yt)

    # Streaming shortcuts (a fixed, short list)
    targets.extend(get_streaming_targets())

    # Bluetooth radio and paired devices
    targets.extend(get_bluetooth_targets())

    # System audio (always useful)
    targets.extend(get_audio_targets())

    # Power, brightness and do-not-disturb
    targets.extend(get_system_targets())

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

    # Sort by kind, then by title
    kind_order = {
        "player": 0, "youtube_player": 0, "window": 1, "workspace": 2, "app": 3,
        "streaming": 4, "bluetooth": 5, "system": 6, "youtube": 7, "command": 8,
    }
    targets.sort(key=lambda t: (kind_order.get(t.kind, 99), t.title))

    snapshot = Snapshot(targets=targets, ts=time.time())
    return snapshot
