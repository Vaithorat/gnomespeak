"""System audio control via PipeWire/ALSA (wpctl)."""

import re
import subprocess
from vt.model import Target, Action
from vt.procs import run_all

_VOLUME_RE = re.compile(r"Volume:\s+([\d.]+)")
# A stream row in `wpctl status`: an id, a dot, and the application's name.
_STREAM_RE = re.compile(r"^\s*(\d+)\.\s+(\S.*?)\s*$")
# Its ports, which are rows in the same shape and are not streams.
_PORT_RE = re.compile(r"^\s*\d+\.\s+(output|input|monitor)_")


def _status_text() -> str:
    """`wpctl status`, or "" when PipeWire is not answering."""
    try:
        result = subprocess.run(
            ["wpctl", "status"], capture_output=True, text=True, timeout=2
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def _parse_volume(returncode: int, output: str) -> tuple[float, bool] | None:
    """One `wpctl get-volume` result, or None when it said nothing usable."""
    if returncode != 0:
        return None
    output = output.strip()
    # Example output: "Volume: 0.88" or "Volume: 0.88 [MUTED]"
    match = _VOLUME_RE.match(output)
    if not match:
        return None
    return float(match.group(1)), "[MUTED]" in output


def get_volumes(nodes: list) -> list:
    """Volume and mute for several nodes at once, in the order asked.

    Each `wpctl get-volume` is a process that spends its life waiting, and a
    machine with a few streams was paying a tenth of a second for the queue.
    They are independent reads, so they wait together.
    """
    if not nodes:
        return []
    results = run_all([["wpctl", "get-volume", node] for node in nodes])
    return [_parse_volume(code, out) for code, out in results]


def audio_streams(status_text: str = None) -> list[tuple[str, str]]:
    """(node id, application name) for each playback stream, newest last.

    "Turn the game down, not the call" is the one thing a single system slider
    cannot do, and PipeWire has modelled it all along. `wpctl status` is the
    cheap way to ask: one process, versus a pw-dump of the entire graph.
    """
    if status_text is None:
        status_text = _status_text()

    streams = []
    section = ""          # "Audio" | "Video" | ...
    in_streams = False
    for line in status_text.splitlines():
        bare = line.strip()
        if bare in ("Audio", "Video", "Settings"):
            section = bare
            in_streams = False
            continue
        if bare.endswith("Streams:"):
            # Video has a Streams block too, and a webcam has no volume.
            in_streams = section == "Audio"
            continue
        if not in_streams:
            continue
        if not bare or bare.rstrip("│ ").endswith(":"):
            in_streams = False
            continue
        if _PORT_RE.match(line) or ">" in line:
            continue
        match = _STREAM_RE.match(line.replace("│", " ").replace("├─", " ").replace("└─", " "))
        if match:
            streams.append((match.group(1), match.group(2)))
    return streams


# A sink or source row in `wpctl status`: an optional "*" for the default one,
# an id, and a name that ends in the volume wpctl prints for it.
_DEVICE_RE = re.compile(r"^\s*(\*)?\s*(\d+)\.\s+(\S.*?)\s*(?:\[vol:.*\])?\s*$")


def audio_devices(status_text: str = None) -> list[dict]:
    """Every output and input device, as {id, name, kind, default}.

    "Play through the headphones, not the speakers" is one `wpctl set-default`
    away, and the list it needs is in the status output already being read for
    the streams.
    """
    if status_text is None:
        status_text = _status_text()
    devices = []
    section = ""
    block = ""
    for line in status_text.splitlines():
        # The tree characters wpctl draws are decoration on every line; strip
        # them once, here, rather than in each pattern below.
        plain = line.replace("│", " ").replace("├─", " ").replace("└─", " ")
        bare = plain.strip()
        if bare in ("Audio", "Video", "Settings"):
            section = bare
            block = ""
            continue
        if bare.endswith(":"):
            block = bare[:-1].strip().lower() if section == "Audio" else ""
            continue
        if block not in ("sinks", "sources") or not bare:
            continue
        match = _DEVICE_RE.match(plain)
        if not match:
            continue
        devices.append({
            "id": match.group(2),
            "name": match.group(3).strip(),
            "kind": "sink" if block == "sinks" else "source",
            "default": bool(match.group(1)),
        })
    return devices


def short_names(names: list) -> list:
    """Device names with the part they all share removed.

    Every sink on this machine is called "Alder Lake PCH-P High Definition
    Audio Controller <something>", and the something is the only part anyone
    is choosing between.
    """
    if len(names) < 2:
        return list(names)
    words = [name.split() for name in names]
    shared = 0
    while all(len(w) > shared + 1 for w in words) and \
            len({w[shared] for w in words}) == 1:
        shared += 1
    return [" ".join(w[shared:]) or " ".join(w) for w in words]


def get_device_targets(status_text: str = None) -> list[Target]:
    """One row per direction, offering the devices that are not current.

    The device in use is the row's status rather than a button: pressing
    "Speaker" while the sound is already coming out of the speaker is a button
    that does nothing, and this list is short enough to read.
    """
    devices = audio_devices(status_text)
    targets = []
    for kind, title, icon in (("sink", "Output device", "🔈"),
                              ("source", "Input device", "🎙")):
        rows = [d for d in devices if d["kind"] == kind]
        if len(rows) < 2:
            # One device is not a choice, and zero is a machine with no sound.
            continue
        labels = short_names([d["name"] for d in rows])
        current = next((label for label, d in zip(labels, rows) if d["default"]), "")
        targets.append(Target(
            id=f"audio:{kind}",
            kind="system",
            title=title,
            subtitle="Where sound goes" if kind == "sink" else "Where sound comes from",
            icon=icon,
            status=current or "unset",
            actions=[
                Action(id=f"use_{d['id']}", label=label)
                for label, d in zip(labels, rows) if not d["default"]
            ],
        ))
    return targets


def set_default_device(node: str) -> dict:
    """Make one sink or source the default. `node` is a wpctl id."""
    if not node.isdigit():
        return {"ok": False, "message": f"Invalid device: {node}"}
    known = {d["id"]: d for d in audio_devices()}
    device = known.get(node)
    if device is None:
        # The device list is a second old at most, but a headset unplugged in
        # between is exactly the case that must not reach wpctl as a stale id.
        return {"ok": False, "message": "That device is not there any more"}
    try:
        result = subprocess.run(
            ["wpctl", "set-default", node], capture_output=True, text=True, timeout=2
        )
    except FileNotFoundError:
        return {"ok": False, "message": "wpctl not found (PipeWire is required)"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}
    if result.returncode != 0:
        return {"ok": False, "message": (result.stderr or "wpctl refused it").strip()}

    names = [d["name"] for d in known.values() if d["kind"] == device["kind"]]
    labels = short_names(names)
    short = labels[names.index(device["name"])] if device["name"] in names else device["name"]

    # wpctl exits 0 for a device WirePlumber then declines to use -- an HDMI
    # sink with no cable in it is accepted and reverted a moment later. The
    # phone would otherwise be told the sound moved when it did not, so the
    # answer comes from reading the default back rather than from the exit code.
    landed = next((d for d in audio_devices()
                   if d["kind"] == device["kind"] and d["default"]), None)
    if landed is None or landed["id"] != node:
        return {
            "ok": False,
            "message": f"The PC would not switch to {short} — it may be unplugged",
        }
    return {"ok": True, "message": f"Now using {short}"}


def execute_device_action(kind: str, action_id: str) -> dict:
    """Run one action on the output or input device row."""
    if kind not in ("sink", "source"):
        return {"ok": False, "message": f"Unknown audio device: {kind}"}
    if not action_id.startswith("use_"):
        return {"ok": False, "message": f"Unknown device action: {action_id}"}
    return set_default_device(action_id[len("use_"):])


def get_stream_targets(status_text: str = None) -> list[Target]:
    """One slider per application that is making sound."""
    streams = audio_streams(status_text)
    seen = {}
    for _, name in streams:
        seen[name] = seen.get(name, 0) + 1

    targets = []
    counted = {}
    volumes = get_volumes([node for node, _ in streams])
    for (node, name), state in zip(streams, volumes):
        if state is None:
            # The stream ended between listing it and reading it. Common, and
            # not worth a row that says nothing.
            continue
        volume, is_muted = state
        counted[name] = counted.get(name, 0) + 1
        # Two Firefox tabs are two streams with one name; the id is the only
        # thing that tells them apart, so it is only shown when it has to be.
        subtitle = f"Stream {node}" if seen.get(name, 0) > 1 else "Application volume"
        targets.append(Target(
            id=f"stream:{node}",
            kind="system",
            title=name,
            subtitle=subtitle,
            icon="🔇" if is_muted else "🎚",
            status="muted" if is_muted else "playing",
            actions=[
                Action(id="volume", label=f"Volume ({int(volume * 100)}%)",
                       kind="slider", value=volume),
                Action(id="mute", label="Unmute" if is_muted else "Mute"),
            ],
        ))
    return targets


def get_audio_targets() -> list[Target]:
    """System output (sink) and input (mic) volume, each its own target.

    Uses wpctl (part of PipeWire). The mic row is omitted entirely on a
    machine with no default source, rather than showing a dead slider.
    """
    targets = []

    # The stream list and the two default volumes are three processes that
    # know nothing about each other, so they wait together rather than in a
    # queue -- the per-stream volumes are the only reads that have to come
    # after, because until the list arrives there is nothing to ask about.
    status, sink_out, source_out = run_all([
        ["wpctl", "status"],
        ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
        ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
    ])
    status_text = status[1] if status[0] == 0 else ""
    sink = _parse_volume(*sink_out)
    source = _parse_volume(*source_out)
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

    targets.extend(get_device_targets(status_text))
    targets.extend(get_stream_targets(status_text))
    return targets
