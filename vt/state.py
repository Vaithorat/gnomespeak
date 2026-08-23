"""Assemble the complete state snapshot from all sources."""

import time
from vt.model import Snapshot, Target, Action
from vt.sources.mpris import get_mpris_targets
from vt.sources.audio import get_audio_targets
from vt.sources.apps import get_app_targets
from vt.sources.windows import get_window_targets
from vt.sources.youtube import get_youtube_target
from vt.sources.youtube_player import get_youtube_player_target
from vt.commands import CommandsConfig


def get_snapshot() -> Snapshot:
    """Gather all targets from all sources into a single snapshot.

    Gathers: MPRIS players, windows, apps, system audio, and configured commands.
    Sources are gathered in order of importance and sorted by kind.
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

    # Running apps
    targets.extend(get_app_targets())

    # YouTube (if available)
    yt = get_youtube_target()
    if yt.actions:
        targets.append(yt)

    # System audio (always useful)
    targets.extend(get_audio_targets())

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
    kind_order = {"player": 0, "window": 1, "app": 2, "system": 3, "command": 4}
    targets.sort(key=lambda t: (kind_order.get(t.kind, 99), t.title))

    snapshot = Snapshot(targets=targets, ts=time.time())
    return snapshot
