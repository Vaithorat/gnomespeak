"""Tests for choosing where sound goes.

The parsing is pinned against real `wpctl status` output, and the switch is
pinned against the case that matters most: wpctl exits 0 for a device
WirePlumber then declines to use, so an HDMI sink with no cable in it would
otherwise report success while the sound stayed in the speakers.
"""

from vt.actions import execute_action
from vt.sources import audio

STATUS = """PipeWire 'pipewire-0' [1.6.2]
 └─ Clients:
        33. WirePlumber                         [1.6.2]

Audio
 ├─ Devices:
 │      51. Alder Lake PCH-P High Definition Audio Controller [alsa]
 │
 ├─ Sinks:
 │      59. Alder Lake PCH-P HD Audio Controller HDMI / DisplayPort 3 Output [vol: 1.00]
 │  *   62. Alder Lake PCH-P HD Audio Controller Speaker [vol: 0.04]
 │
 ├─ Sources:
 │      63. Alder Lake PCH-P HD Audio Controller Headset Mono Microphone [vol: 1.00]
 │  *   64. Alder Lake PCH-P HD Audio Controller Digital Microphone [vol: 1.00]
 │
 ├─ Filters:
 │
 └─ Streams:
       131. Firefox
            132. output_FL       > Speaker:playback_FL	[init]

Video
 ├─ Sinks:
 │      70. Not an audio device [vol: 1.00]
"""


def test_sinks_and_sources_are_told_apart():
    devices = audio.audio_devices(STATUS)
    assert [d["id"] for d in devices if d["kind"] == "sink"] == ["59", "62"]
    assert [d["id"] for d in devices if d["kind"] == "source"] == ["63", "64"]


def test_the_current_device_is_the_starred_one():
    devices = audio.audio_devices(STATUS)
    assert [d["id"] for d in devices if d["default"]] == ["62", "64"]


def test_a_video_sink_is_not_an_audio_device():
    assert all(d["id"] != "70" for d in audio.audio_devices(STATUS))


def test_the_shared_part_of_every_name_is_dropped():
    """Every sink here is an "Alder Lake PCH-P ..."; the tail is the choice."""
    assert audio.short_names([
        "Alder Lake PCH-P HD Audio Controller Speaker",
        "Alder Lake PCH-P HD Audio Controller HDMI / DisplayPort 3 Output",
    ]) == ["Speaker", "HDMI / DisplayPort 3 Output"]


def test_one_name_is_left_alone():
    assert audio.short_names(["Speaker"]) == ["Speaker"]


def test_names_with_nothing_in_common_are_left_alone():
    assert audio.short_names(["Speaker", "Headphones"]) == ["Speaker", "Headphones"]


def test_the_row_offers_the_devices_that_are_not_current():
    targets = {t.id: t for t in audio.get_device_targets(STATUS)}
    sink = targets["audio:sink"]
    assert sink.status == "Speaker"
    assert [a.id for a in sink.actions] == ["use_59"]


def test_one_device_is_not_a_choice(monkeypatch):
    """A machine with a single output has nothing to offer, so no row."""
    single = STATUS.replace(
        " │      59. Alder Lake PCH-P HD Audio Controller HDMI / DisplayPort 3 Output [vol: 1.00]\n", ""
    )
    assert [t.id for t in audio.get_device_targets(single)] == ["audio:source"]


def test_switching_reads_the_default_back(monkeypatch):
    """wpctl exits 0 for a device WirePlumber then declines to use."""
    monkeypatch.setattr(audio, "audio_devices", lambda status_text=None: [
        {"id": "59", "name": "HDMI", "kind": "sink", "default": False},
        {"id": "62", "name": "Speaker", "kind": "sink", "default": True},
    ])

    class Result:
        returncode, stderr = 0, ""

    monkeypatch.setattr(audio.subprocess, "run", lambda argv, **kw: Result())
    result = audio.set_default_device("59")

    assert result["ok"] is False
    assert "unplugged" in result["message"]


def test_a_switch_that_stuck_is_reported_as_done(monkeypatch):
    state = {"default": "62"}

    def devices(status_text=None):
        return [
            {"id": "59", "name": "HDMI", "kind": "sink", "default": state["default"] == "59"},
            {"id": "62", "name": "Speaker", "kind": "sink", "default": state["default"] == "62"},
        ]

    class Result:
        returncode, stderr = 0, ""

    def run(argv, **kw):
        state["default"] = argv[-1]
        return Result()

    monkeypatch.setattr(audio, "audio_devices", devices)
    monkeypatch.setattr(audio.subprocess, "run", run)

    assert audio.set_default_device("59") == {"ok": True, "message": "Now using HDMI"}


def test_a_device_that_vanished_never_reaches_wpctl(monkeypatch):
    monkeypatch.setattr(audio, "audio_devices", lambda status_text=None: [])
    monkeypatch.setattr(audio.subprocess, "run", _must_not_run)
    assert audio.set_default_device("59")["ok"] is False


def test_a_node_that_is_not_a_number_never_reaches_wpctl(monkeypatch):
    monkeypatch.setattr(audio.subprocess, "run", _must_not_run)
    assert audio.set_default_device("62; rm -rf ~")["ok"] is False


def _must_not_run(*args, **kwargs):
    raise AssertionError("wpctl was called with something it should never see")


def test_the_dispatcher_routes_the_device_rows(monkeypatch):
    monkeypatch.setattr(audio, "set_default_device", lambda node: {"ok": True, "message": node})
    assert execute_action("audio:sink", "use_59")["message"] == "59"
    assert execute_action("audio:source", "use_63")["message"] == "63"


def test_the_dispatcher_refuses_an_unknown_direction():
    assert execute_action("audio:middle", "use_59")["ok"] is False
