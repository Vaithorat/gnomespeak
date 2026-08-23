"""System audio control via PipeWire/ALSA (wpctl)."""

import re
import subprocess
from vt.model import Target, Action


def get_audio_targets() -> list[Target]:
    """Get the system audio control as a single target with volume slider and mute toggle.

    Uses wpctl (part of PipeWire) to read and control the default audio sink.
    """
    try:
        # Get current volume
        result = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0:
            return []

        output = result.stdout.strip()
        # Example output: "Volume: 0.88" or "Volume: 0.88 [MUTED]"
        match = re.match(r"Volume:\s+([\d.]+)", output)
        if not match:
            return []

        volume = float(match.group(1))
        is_muted = "[MUTED]" in output

        # Build actions
        actions = [
            Action(
                id="volume",
                label=f"Volume ({int(volume * 100)}%)",
                kind="slider",
                value=volume,
            ),
            Action(
                id="mute",
                label="Unmute" if is_muted else "Mute",
            ),
        ]

        # Status indicator
        status = "muted" if is_muted else "active"
        status_icon = "🔊" if not is_muted else "🔇"

        target = Target(
            id="system:audio",
            kind="system",
            title="System Audio",
            icon=status_icon,
            status=status,
            actions=actions,
        )
        return [target]

    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        # wpctl not installed
        return []
    except Exception:
        return []
