"""Tests for the shared action dispatcher.

The CLI and the HTTP server both route through `execute_action`, so these cover
both entry points at once -- `vt do` previously handled only audio and MPRIS.
"""

import pytest

from vt import actions
from vt.actions import execute_action


@pytest.fixture
def routed(monkeypatch):
    """Record which handler execute_action picked, without touching the system."""
    seen = {}

    def record(name):
        def handler(*args):
            seen["handler"] = name
            seen["args"] = args
            return {"ok": True, "message": name}
        return handler

    for name in ("audio", "mpris", "command", "window", "app", "launcher"):
        monkeypatch.setattr(actions, f"execute_{name}_action", record(name))
    return seen


@pytest.mark.parametrize(
    "target_id,action_id,expected",
    [
        ("system:audio", "mute", "audio"),
        ("mpris:org.mpris.MediaPlayer2.firefox", "play_pause", "mpris"),
        ("command:lock", "run", "command"),
        ("window:42", "focus", "window"),
        ("app:firefox", "focus", "app"),
        ("launcher:firefox", "launch", "launcher"),
    ],
)
def test_every_target_kind_is_reachable(routed, target_id, action_id, expected):
    """All six kinds dispatch -- the CLI reached only the first two before."""
    assert execute_action(target_id, action_id)["ok"] is True
    assert routed["handler"] == expected


def test_unknown_kind_is_rejected():
    result = execute_action("bogus:x", "run")
    assert result["ok"] is False
    assert "Unknown target kind" in result["message"]


def test_target_without_a_kind_is_rejected():
    assert execute_action("nokind", "run")["ok"] is False


def test_mpris_target_id_is_not_double_prefixed(routed):
    """The id already carries the full bus name."""
    execute_action("mpris:org.mpris.MediaPlayer2.vlc", "next")
    assert routed["args"][0] == "org.mpris.MediaPlayer2.vlc"


def test_volume_requires_a_value():
    assert actions.execute_audio_action("volume", None)["ok"] is False


def test_volume_is_clamped(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        actions.subprocess, "run", lambda argv, **kw: seen.update(argv=argv)
    )
    actions.execute_audio_action("volume", 4.2)
    assert seen["argv"][-1] == "1.0"
    actions.execute_audio_action("volume", -3)
    assert seen["argv"][-1] == "0.0"


def test_non_numeric_window_id_is_rejected():
    if not actions.HAS_DBUS:
        pytest.skip("python-dbus is required to reach the id check")
    result = actions.execute_window_action("not-a-number", "focus")
    assert result["ok"] is False
    assert "Invalid window id" in result["message"]


def test_missing_command_is_reported():
    result = actions.execute_command_action("definitely-not-configured")
    assert result["ok"] is False
    assert "not found" in result["message"].lower()


# --- launching installed apps ----------------------------------------------

def _entry(tmp_path, argv, name="Test App"):
    return {
        "id": "test-app",
        "path": str(tmp_path / "test-app.desktop"),
        "name": name,
        "icon": "",
        "binary": argv[0],
        "argv": argv,
        "subtitle": "",
        "terminal": False,
    }


def test_launch_reports_an_unknown_app(monkeypatch):
    monkeypatch.setattr("vt.sources.apps.get_installed_index", lambda: {})
    result = actions.execute_launcher_action("nope", "launch")
    assert result["ok"] is False
    assert "No installed app" in result["message"]


def test_launch_rejects_other_actions():
    assert actions.execute_launcher_action("firefox", "quit")["ok"] is False


def test_launch_runs_the_entry(tmp_path, monkeypatch):
    """A process still alive after the grace period counts as launched."""
    monkeypatch.setattr(actions.shutil, "which", lambda name: None)
    result = actions.launch_entry(_entry(tmp_path, ["sleep", "5"]))
    assert result["ok"] is True
    assert "Launched Test App" in result["message"]


def test_launch_detaches_from_the_server(tmp_path, monkeypatch):
    """start_new_session, or Ctrl+C on `vt serve` takes the browser with it."""
    seen = {}

    class FakeProc:
        def wait(self, timeout=None):
            raise actions.subprocess.TimeoutExpired("cmd", timeout)

    def fake_popen(argv, **kwargs):
        seen.update(argv=argv, kwargs=kwargs)
        return FakeProc()

    monkeypatch.setattr(actions.shutil, "which", lambda name: None)
    monkeypatch.setattr(actions.subprocess, "Popen", fake_popen)
    actions.launch_entry(_entry(tmp_path, ["firefox"]))

    assert seen["kwargs"]["start_new_session"] is True
    assert seen["argv"] == ["firefox"]


def test_launch_prefers_gio_when_available(tmp_path, monkeypatch):
    """gio applies the .desktop file's own semantics; argv only approximates them."""
    seen = {}

    class FakeResult:
        returncode = 0
        stderr = b""

    monkeypatch.setattr(actions.shutil, "which", lambda name: "/usr/bin/gio")
    monkeypatch.setattr(
        actions.subprocess, "run", lambda argv, **kw: seen.update(argv=argv) or FakeResult()
    )
    entry = _entry(tmp_path, ["flatpak", "run", "com.example.App"])
    assert actions.launch_entry(entry)["ok"] is True
    assert seen["argv"] == ["gio", "launch", entry["path"]]


def test_launch_reports_an_immediate_failure(tmp_path, monkeypatch):
    """Exiting non-zero right away must not read as a successful launch."""
    monkeypatch.setattr(actions.shutil, "which", lambda name: None)
    result = actions.launch_entry(_entry(tmp_path, ["false"]))
    assert result["ok"] is False
    assert "exit" in result["message"].lower() or "failed" in result["message"].lower()


def test_launch_reports_a_missing_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(actions.shutil, "which", lambda name: None)
    result = actions.launch_entry(_entry(tmp_path, ["definitely-not-a-real-binary-xyz"]))
    assert result["ok"] is False
    assert "Not found" in result["message"]


def test_launch_reports_gio_stderr(tmp_path, monkeypatch):
    """When gio fails, we extract and show its error message."""
    class FakeResult:
        returncode = 1
        stderr = b"gio: error opening file: No such file or directory"

    monkeypatch.setattr(actions.shutil, "which", lambda name: "/usr/bin/gio")
    monkeypatch.setattr(actions.subprocess, "run", lambda *a, **kw: FakeResult())
    result = actions.launch_entry(_entry(tmp_path, ["something"]))
    assert result["ok"] is False
    assert "No such file or directory" in result["message"]


# --- AppArmor / snap confinement diagnostics --------------------------------

def test_confinement_label_reads_unconfined_as_empty(monkeypatch, tmp_path):
    proc = tmp_path / "current"
    proc.write_text("unconfined\n")
    monkeypatch.setattr(actions, "Path", lambda p: proc)
    assert actions.confinement_label() == ""


def test_confinement_label_strips_the_mode(monkeypatch, tmp_path):
    proc = tmp_path / "current"
    proc.write_text("snap.code.code (complain)\n")
    monkeypatch.setattr(actions, "Path", lambda p: proc)
    assert actions.confinement_label() == "snap.code.code"


def test_denied_message_names_the_snap(monkeypatch):
    monkeypatch.setattr(actions, "confinement_label", lambda: "snap.code.code")
    msg = actions.dbus_denied_message()
    assert "snap.code.code" in msg
    assert "normal terminal" in msg


# --- YouTube playback control -----------------------------------------------

def test_youtube_player_action_dispatch():
    result = actions.execute_youtube_action("player", "play_pause")
    assert "ok" in result and "message" in result


def test_keystroke_control_is_refused_on_wayland(monkeypatch):
    """xdotool cannot drive a Wayland client, so the buttons must not pretend.

    Shipping them anyway meant every tap reported success while nothing moved.
    """
    from vt.sources import youtube_player

    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    assert youtube_player.get_youtube_player_target() is None

    result = actions.execute_youtube_player_action("play_pause")
    assert result["ok"] is False
    assert "MPRIS" in result["message"]


def test_keystroke_control_focuses_before_typing(monkeypatch):
    """Keys land in the focused window; without wmctrl -a they hit the wrong one."""
    from vt.sources import youtube_player

    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(youtube_player.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        youtube_player, "find_youtube_window", lambda: {"id": "0x1", "name": "YouTube"}
    )

    calls = []
    monkeypatch.setattr(
        youtube_player.subprocess, "run",
        lambda argv, **kw: calls.append(argv) or type("R", (), {"returncode": 0})()
    )

    assert youtube_player.send_keys("play_pause")["ok"] is True
    assert calls[0][:2] == ["wmctrl", "-ia"]
    assert calls[1] == ["xdotool", "key", "space"]


def test_youtube_player_close_window(monkeypatch):
    """Closing YouTube requires a window to exist."""
    from vt.sources import youtube_player

    monkeypatch.setattr(youtube_player.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(youtube_player, "find_youtube_window", lambda: None)
    result = actions.execute_youtube_player_action("close")
    assert result["ok"] is False
    assert "window" in result["message"].lower()
