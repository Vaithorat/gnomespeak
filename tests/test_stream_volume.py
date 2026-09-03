"""Tests for per-application volume: parsing wpctl, and acting on one stream."""

import pytest

from vt.actions import execute_action
from vt.sources import audio

WPCTL_STATUS = """PipeWire 'pipewire-0' [1.2.7, vaibhav@box, cookie:123]

Audio
 ├─ Devices:
 │      45. Alder Lake PCH-P                    [alsa]
 │
 ├─ Sinks:
 │  *  109. Stone 350 Pro                       [vol: 0.88]
 │
 ├─ Sources:
 │  *   81. Built-in Microphone                 [vol: 0.40]
 │
 └─ Streams:
        95. Firefox
             91. output_FL       > Stone 350 Pro:playback_FL\t[active]
             96. output_FR       > Stone 350 Pro:playback_FR\t[active]
       120. Steam
            121. output_FL       > Stone 350 Pro:playback_FL\t[active]

Video
 ├─ Devices:
 │      52. Integrated_Webcam_FHD               [v4l2]
 │
 └─ Streams:
        77. Cheese

Settings
 └─ Default Configured Devices:
        0. Audio/Sink    alsa_output.pci
"""


def test_streams_are_read_from_wpctl_status():
    assert audio.audio_streams(WPCTL_STATUS) == [("95", "Firefox"), ("120", "Steam")]


def test_ports_are_not_mistaken_for_streams():
    """Every port is a numbered row in the same shape as a stream."""
    ids = [node for node, _ in audio.audio_streams(WPCTL_STATUS)]
    assert "91" not in ids and "121" not in ids


def test_a_webcam_is_not_an_audio_stream():
    """Video has a Streams block of its own, and none of it has a volume."""
    assert "77" not in [node for node, _ in audio.audio_streams(WPCTL_STATUS)]


def test_no_streams_when_wpctl_is_missing(monkeypatch):
    monkeypatch.setattr(audio.subprocess, "run", _raise_missing)
    assert audio.audio_streams() == []


def test_each_stream_becomes_a_slider(monkeypatch):
    monkeypatch.setattr(audio, "audio_streams", lambda status_text=None: [("95", "Firefox"), ("120", "Steam")])
    monkeypatch.setattr(audio, "get_volumes",
                        lambda nodes: [(0.5, node == "120") for node in nodes])

    targets = audio.get_stream_targets()

    assert [t.id for t in targets] == ["stream:95", "stream:120"]
    assert [a.kind for a in targets[0].actions] == ["slider", "button"]
    assert targets[1].actions[1].label == "Unmute"


def test_two_streams_of_one_app_are_told_apart(monkeypatch):
    monkeypatch.setattr(audio, "audio_streams", lambda status_text=None: [("95", "Firefox"), ("101", "Firefox")])
    monkeypatch.setattr(audio, "get_volumes", lambda nodes: [(1.0, False)] * len(nodes))

    subtitles = [t.subtitle for t in audio.get_stream_targets()]

    assert subtitles == ["Stream 95", "Stream 101"]


def test_a_stream_that_ended_mid_read_is_dropped(monkeypatch):
    """Streams disappear between listing and reading; that is not an error."""
    monkeypatch.setattr(audio, "audio_streams", lambda status_text=None: [("95", "Firefox")])
    monkeypatch.setattr(audio, "get_volumes", lambda nodes: [None] * len(nodes))

    assert audio.get_stream_targets() == []


def test_a_stream_action_reaches_wpctl(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return _Ok()

    monkeypatch.setattr("vt.actions.subprocess.run", fake_run)

    result = execute_action("stream:95", "volume", 0.4)

    assert result["ok"]
    assert calls[0] == ["wpctl", "set-volume", "95", "0.4"]


@pytest.mark.parametrize("bad", ["stream:../etc", "stream:@DEFAULT_AUDIO_SINK@", "stream:"])
def test_only_a_node_number_is_accepted(bad, monkeypatch):
    """The id is the one part of this that comes from the phone."""
    monkeypatch.setattr("vt.actions.subprocess.run", _must_not_run)
    assert execute_action(bad, "mute")["ok"] is False


class _Ok:
    returncode = 0
    stdout = ""
    stderr = ""


def _raise_missing(*args, **kwargs):
    raise FileNotFoundError("wpctl")


def _must_not_run(*args, **kwargs):
    raise AssertionError("a rejected id must never reach wpctl")
