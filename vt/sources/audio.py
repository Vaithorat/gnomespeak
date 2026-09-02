"""System audio control via PipeWire/ALSA (wpctl)."""

import re
import subprocess
from vt.model import Target, Action

_VOLUME_RE = re.compile(r"Volume:\s+([\d.]+)")


def _get_volume(node: str) -> tuple[float, bool] | None:
    """Current volume and mute state of a wpctl node, or None if unreadable."""
    try:
        result = subprocess.run(
            ["wpctl", "get-volume", node],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        # Example output: "Volume: 0.88" or "Volume: 0.88 [MUTED]"
        match = _VOLUME_RE.match(output)
        if not match:
            return None
        return float(match.group(1)), "[MUTED]" in output
    except Exception:
        return None


def get_audio_targets() -> list[Target]:
    """System output (sink) and input (mic) volume, each its own target.

    Uses wpctl (part of PipeWire). The mic row is omitted entirely on a
    machine with no default source, rather than showing a dead slider.
    """
    targets = []

    sink = _get_volume("@DEFAULT_AUDIO_SINK@")
    if sink is not None:
        volume, is_muted = sink
        targets.append(Target(
            id="system:audio",
            kind="system",
            title="System Audio",
            icon="🔇" if is_muted else "🔊",
            status="muted" if is_muted else "active",
            actions=[
                Action(id="volume", label=f"Volume ({int(volume * 100)}%)",
                       kind="slider", value=volume),
                Action(id="mute", label="Unmute" if is_muted else "Mute"),
            ],
        ))

    source = _get_volume("@DEFAULT_AUDIO_SOURCE@")
    if source is not None:
        volume, is_muted = source
        targets.append(Target(
            id="system:mic",
            kind="system",
            title="Microphone",
            icon="🔇" if is_muted else "🎙",
            status="muted" if is_muted else "active",
            actions=[
                Action(id="volume", label=f"Volume ({int(volume * 100)}%)",
                       kind="slider", value=volume),
                Action(id="mute", label="Unmute" if is_muted else "Mute"),
            ],
        ))

    return targets
