"""Data models for targets and actions."""

import time
from dataclasses import dataclass, field, asdict
from typing import Optional, Any


@dataclass
class Action:
    """An action the user can invoke on a target."""
    id: str                              # e.g. "play_pause"
    label: str                           # e.g. "Pause" (reflects current state)
    kind: str = "button"                 # "button" | "slider" | "confirm"
    value: Optional[float] = None        # for sliders: current value [0..1]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Target:
    """A controllable entity: media player, window, app, system control, command,
    an installed-but-not-running app (kind "launcher"), a YouTube search or
    a YouTube playback session (kind "youtube" or "youtube_player")."""
    id: str                              # "mpris:org.mpris.MediaPlayer2.firefox"
    kind: str                            # "player" | "window" | "app" | "system" | "command" | "launcher" | "youtube" | "youtube_player"
    title: str                           # "Cars 2"
    subtitle: str = ""                   # "Firefox · zstream.mov"
    icon: str = ""                       # .desktop Icon name or emoji
    status: str = ""                     # "playing" | "paused" | "running"
    position: Optional[float] = None     # seconds
    length: Optional[float] = None       # seconds
    note: str = ""                       # why a capability is missing, shown in the detail view
    art: str = ""                        # cache key for album art; "" when the player offers none
    actions: list[Action] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["actions"] = [a.to_dict() for a in self.actions]
        return d


@dataclass
class Snapshot:
    """The complete state at a point in time."""
    targets: list[Target] = field(default_factory=list)
    ts: float = field(default_factory=time.time)  # unix timestamp

    def to_dict(self) -> dict[str, Any]:
        return {
            "targets": [t.to_dict() for t in self.targets],
            "ts": self.ts,
        }
