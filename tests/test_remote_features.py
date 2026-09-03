"""Tests for the phone-to-PC features: clipboard, input, files, notifications.

None of these touch the real desktop. Every subprocess is faked, the transfer
directory is redirected at an environment variable, and the notification mirror
is fed the text a real dbus-monitor would have printed -- so the suite says the
same thing on a headless CI box as it does on a GNOME session.
"""

import subprocess
from types import SimpleNamespace

import pytest

from vt import shell
from vt.sources import clipboard, remote_input, transfer
from vt.sources.notifications_mirror import NotificationMirror


# --- clipboard --------------------------------------------------------------

class FakeRun:
    """Stand-in for subprocess.run that records what it was asked to do."""

    def __init__(self, returncode=0, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return self


@pytest.fixture
def wayland(monkeypatch):
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: f"/usr/bin/{name}")


def test_clipboard_prefers_wayland_tool_on_wayland(wayland):
    assert clipboard.backend()["name"] == "wl-clipboard"


def test_clipboard_prefers_x11_tool_on_x11(monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert clipboard.backend()["name"] == "xclip"


def test_clipboard_reports_missing_tool(monkeypatch):
    monkeypatch.setattr(clipboard.shutil, "which", lambda name: None)
    result = clipboard.read_text()
    assert result["ok"] is False
    assert "install" in result["message"].lower()


def test_clipboard_read_returns_text(wayland, monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRun(stdout="hello phone".encode()))
    result = clipboard.read_text()
    assert result["ok"] is True
    assert result["text"] == "hello phone"


def test_empty_clipboard_is_not_an_error(wayland, monkeypatch):
    # wl-paste exits non-zero when nothing is copied. Reporting that as a
    # failure is what sent the first person to see it looking for a bad install.
    monkeypatch.setattr(
        subprocess, "run", FakeRun(returncode=1, stderr=b"Nothing is copied")
    )
    result = clipboard.read_text()
    assert result["ok"] is True
    assert result["text"] == ""


def test_clipboard_read_truncates(wayland, monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", FakeRun(stdout=b"x" * (clipboard.MAX_BYTES + 500))
    )
    result = clipboard.read_text()
    assert len(result["text"]) == clipboard.MAX_BYTES
    assert result["truncated"] is True


def test_clipboard_write_sends_text(wayland, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)
    result = clipboard.write_text("copy me")
    assert result["ok"] is True
    argv, kwargs = fake.calls[0]
    assert argv == ["wl-copy"]
    assert kwargs["input"] == b"copy me"


def test_clipboard_write_refuses_empty(wayland):
    assert clipboard.write_text("")["ok"] is False


def test_clipboard_write_does_not_hand_the_daemon_a_pipe(wayland, monkeypatch):
    """wl-copy forks a process that owns the selection until it is replaced.

    That child inherits stderr, so a pipe there is never closed and every
    successful copy was reported as a three-second timeout.
    """
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)
    clipboard.write_text("copy me")
    _, kwargs = fake.calls[0]
    assert kwargs["stderr"] is not subprocess.PIPE
    assert kwargs["stdout"] is subprocess.DEVNULL


# --- remote input -----------------------------------------------------------

@pytest.fixture
def calls(monkeypatch):
    """Capture extension calls instead of making them."""
    recorded = []

    def fake_call(method, *args):
        recorded.append((method, args))
        return {"ok": True, "message": ""}

    monkeypatch.setattr(remote_input, "_call", fake_call)
    return recorded


def test_move_clamps_a_runaway_delta(calls):
    remote_input.move(99999, -99999)
    method, args = calls[0]
    assert method == "Pointer"
    assert [int(a) for a in args] == [remote_input.MAX_STEP, -remote_input.MAX_STEP]


def test_move_of_zero_makes_no_call(calls):
    assert remote_input.move(0, 0)["ok"] is True
    assert calls == []


def test_click_rejects_an_unknown_button(calls):
    result = remote_input.click("scroll-wheel-of-doom")
    assert result["ok"] is False
    assert calls == []


def test_type_text_is_capped(calls):
    remote_input.type_text("a" * (remote_input.MAX_TEXT + 100))
    method, args = calls[0]
    assert method == "TypeText"
    assert len(args[0]) == remote_input.MAX_TEXT


@pytest.mark.parametrize("chord", ["ctrl+c", "alt+shift+tab", "f5", "escape", "a"])
def test_valid_chords(chord):
    assert remote_input.valid_chord(chord)


@pytest.mark.parametrize("chord", ["", "ctrl+", "hyper+c", "ctrl+nosuchkey", "+"])
def test_invalid_chords(chord):
    assert not remote_input.valid_chord(chord)


def test_send_keys_rejects_a_bad_chord_before_calling(calls):
    # Validated here rather than in the extension: an unknown key logged to the
    # shell journal is a silent failure from the phone's point of view.
    result = remote_input.send_keys("ctrl+c,hyper+x")
    assert result["ok"] is False
    assert "hyper+x" in result["message"]
    assert calls == []


def test_execute_dispatches_and_rejects(calls):
    assert remote_input.execute("scroll", {"dx": 0, "dy": 10})["ok"] is True
    assert calls[0][0] == "Scroll"
    assert remote_input.execute("teleport", {})["ok"] is False


# --- file transfer ----------------------------------------------------------

@pytest.fixture
def transfer_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GNOMESPEAK_TRANSFER_DIR", str(tmp_path / "incoming"))
    return transfer.transfer_dir()


@pytest.mark.parametrize("name,expected", [
    # The leading dot goes too: a received file that lands hidden is a file the
    # user cannot find in their own Downloads folder.
    ("../../.bashrc", "bashrc"),
    ("/etc/passwd", "passwd"),
    ("..\\..\\windows", "windows"),
    ("", "upload"),
    ("holiday photo (1).jpg", "holiday photo (1).jpg"),
])
def test_safe_name_cannot_express_a_path(name, expected):
    assert transfer.safe_name(name) == expected


def test_unique_path_does_not_overwrite(transfer_dir):
    first = transfer.unique_path("notes.txt")
    first.write_text("one")
    second = transfer.unique_path("notes.txt")
    assert second != first
    assert second.name == "notes-1.txt"


def test_resolve_only_finds_files_in_the_transfer_dir(transfer_dir, tmp_path):
    (transfer_dir / "shared.txt").write_text("hi")
    assert transfer.resolve("shared.txt") is not None
    assert transfer.resolve("../secret.txt") is None
    assert transfer.resolve("missing.txt") is None


def test_resolve_refuses_a_symlink_out_of_the_directory(transfer_dir, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("ssh key")
    (transfer_dir / "innocent.txt").symlink_to(secret)
    assert transfer.resolve("innocent.txt") is None


def test_list_files_is_newest_first(transfer_dir):
    import os
    import time

    for index, name in enumerate(["old.txt", "new.txt"]):
        path = transfer_dir / name
        path.write_text(name)
        os.utime(path, (time.time() + index * 100,) * 2)
    assert [f["name"] for f in transfer.list_files()] == ["new.txt", "old.txt"]


def test_list_files_skips_symlinks(transfer_dir, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    (transfer_dir / "link.txt").symlink_to(secret)
    assert transfer.list_files() == []


# --- notification mirror ----------------------------------------------------

NOTIFY_TRAFFIC = """\
method call time=1730000000.1 sender=:1.42 -> destination=org.freedesktop.Notifications \
serial=7 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify
   string "Firefox"
   uint32 0
   string "firefox-icon"
   string "Download finished"
   string "gnomespeak-3.1.0.tar.gz"
   array [
   ]
   array [
      dict entry(
         string "urgency"
         variant             byte 1
      )
   ]
   int32 -1
method call time=1730000001.2 sender=:1.9 -> destination=org.freedesktop.Notifications \
serial=8 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify
   string "Calendar"
   uint32 0
   string ""
   string "Standup"
   string "in 5 minutes"
   array [
   ]
   array [
   ]
   int32 5000
"""


class FakeProc:
    """A dbus-monitor that has already printed everything it is going to."""

    def __init__(self, text):
        self.stdout = iter(text.splitlines(keepends=True))
        self.stderr = None

    def poll(self):
        return 0


def test_mirror_parses_notify_calls():
    feed = NotificationMirror()
    feed._proc = FakeProc(NOTIFY_TRAFFIC)
    feed._read_loop()

    entries = feed.entries()
    assert [e["app"] for e in entries] == ["Firefox", "Calendar"]
    assert entries[0]["summary"] == "Download finished"
    assert entries[0]["body"] == "gnomespeak-3.1.0.tar.gz"
    assert entries[1]["summary"] == "Standup"


def test_mirror_ignores_nested_hint_strings():
    # The urgency hint's "urgency" is a string too. Reading it as a fifth
    # argument would put a dictionary key in the notification body.
    feed = NotificationMirror()
    feed._proc = FakeProc(NOTIFY_TRAFFIC)
    feed._read_loop()
    assert all("urgency" not in e["body"] for e in feed.entries())


def test_mirror_since_returns_only_newer_entries():
    feed = NotificationMirror()
    feed._proc = FakeProc(NOTIFY_TRAFFIC)
    feed._read_loop()
    first = feed.entries()[0]
    later = feed.entries(since=first["seq"])
    assert [e["summary"] for e in later] == ["Standup"]


# --- notification ids and dismissal -----------------------------------------

DAEMON = ":1.32"

TRAFFIC_WITH_REPLY = """method call time=1730000000.1 sender=:1.9 -> destination=:1.32 \
serial=7 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify
   string "Firefox"
   uint32 0
   string ""
   string "Download finished"
   string "gnomespeak-3.1.0.tar.gz"
   array [
   ]
   int32 -1
method return time=1730000000.2 sender=:1.32 -> destination=:1.9 serial=99 reply_serial=7
   uint32 42
method call time=1730000000.3 sender=:1.32 -> destination=:1.23 \
serial=101 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify
   string "Firefox"
   uint32 0
   string ""
   string "Download finished"
   string "gnomespeak-3.1.0.tar.gz"
   array [
   ]
   int32 -1
"""


def test_the_id_from_the_daemons_reply_is_kept():
    """Dismissal is impossible without it: the id is only in the reply."""
    feed = NotificationMirror(daemon=DAEMON)
    feed._proc = FakeProc(TRAFFIC_WITH_REPLY)
    feed._read_loop()
    assert [e["id"] for e in feed.entries()] == [42]


def test_a_notification_the_shell_forwards_is_not_a_second_row():
    """GNOME Shell re-sends each Notify; only the original is the event."""
    feed = NotificationMirror(daemon=DAEMON)
    feed._proc = FakeProc(TRAFFIC_WITH_REPLY)
    feed._read_loop()
    assert len(feed.entries()) == 1


def test_an_entry_with_no_reply_has_no_id():
    """It shows without a dismiss button rather than with one that fails."""
    feed = NotificationMirror(daemon=DAEMON)
    feed._proc = FakeProc(TRAFFIC_WITH_REPLY.split("method return")[0])
    feed._read_loop()
    assert feed.entries()[0]["id"] == 0


def test_the_monitor_watches_the_daemons_replies():
    feed = NotificationMirror(daemon=DAEMON)
    command = feed._build_command()
    assert "member='Notify'" in command[2]
    assert f"sender='{DAEMON}'" in command[3]


def test_mirror_reports_a_missing_dbus_monitor(monkeypatch):
    feed = NotificationMirror(command=["definitely-not-installed"])
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert feed.start() is False
    assert "dbus-monitor" in feed.error


# --- extension identity -----------------------------------------------------

INTROSPECTION = """
<node>
  <interface name="org.gnome.Shell.Extensions.VoiceTalk">
    <method name="List"/>
    <method name="Focus"/>
    <method name="Workspaces"/>
  </interface>
</node>
"""


def test_every_module_agrees_on_the_bus_name():
    # The rename that broke `vt doctor` was one hardcoded copy of this string
    # drifting from the others, so assert they are literally the same object.
    from vt import actions
    from vt.sources import windows

    assert actions.SHELL_BUS_NAME == shell.SHELL_BUS_NAME
    assert windows.SHELL_BUS_NAME == shell.SHELL_BUS_NAME
    assert shell.SHELL_OBJECT_PATH == "/" + shell.SHELL_BUS_NAME.replace(".", "/")


def test_missing_methods_names_the_gap(monkeypatch):
    monkeypatch.setattr(shell, "methods", lambda: set(shell._METHOD_RE.findall(INTROSPECTION)))
    missing = shell.missing_methods()
    assert "Pointer" in missing and "TypeText" in missing
    assert "List" not in missing
    features = shell.missing_features(missing)
    assert "touchpad (pointer control)" in features
    # One line per feature, not one per method: four window methods missing is
    # one thing wrong, not four.
    assert len(features) == len(set(features))


def test_no_methods_means_not_running(monkeypatch):
    monkeypatch.setattr(shell, "methods", lambda: set())
    assert shell.missing_methods() == set()


def test_expected_methods_match_the_shipped_extension():
    """The extension's interface XML is the contract; drift breaks silently."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "gnome-extension" / "gnomespeak@local" / "extension.js"
    declared = set(shell._METHOD_RE.findall(source.read_text()))
    assert declared == set(shell.EXPECTED_METHODS)


# --- extension install state ------------------------------------------------
# The bus can only say "nobody is answering". These cover the three ways that
# happens, because two of them are fixable and one of them was self-inflicted.

def test_install_problems_reports_a_missing_install(tmp_path):
    problems = shell.install_problems(tmp_path)
    assert problems and "not installed" in problems[0]


def test_install_problems_reports_a_dangling_symlink(tmp_path):
    (tmp_path / shell.EXTENSION_UUID).symlink_to(tmp_path / "deleted-by-a-rename")
    problems = shell.install_problems(tmp_path)
    # This is the one that looks like a working install from every angle except
    # the one that matters: the directory entry is there, the extension is not.
    assert "no longer exists" in problems[0]


def test_install_problems_reports_a_legacy_install(tmp_path):
    (tmp_path / shell.EXTENSION_UUID).mkdir()
    (tmp_path / "voicetalk@local").symlink_to(tmp_path / "gone")
    problems = shell.install_problems(tmp_path)
    assert any("voicetalk@local" in p and "target is gone" in p for p in problems)


def test_a_healthy_install_has_no_problems(tmp_path):
    (tmp_path / shell.EXTENSION_UUID).mkdir()
    assert shell.install_problems(tmp_path) == []


# --- status(): why the extension is not answering ---------------------------
# A fresh install is on disk, enabled, and invisible to the running shell until
# the next login. Reporting that as "not installed" is what made `vt setup` and
# `make dev` look like they disagreed.

@pytest.fixture
def gnome(monkeypatch):
    """A machine with gnome-extensions present and the extension not on the bus."""
    monkeypatch.setattr(shell.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(shell, "is_available", lambda: False)
    monkeypatch.setattr(shell, "is_enabled", lambda: True)
    monkeypatch.setattr(shell, "load_state", lambda: "unscanned")


def test_status_calls_a_fresh_install_pending_login(gnome, tmp_path):
    (tmp_path / shell.EXTENSION_UUID).mkdir()
    code, message = shell.status(tmp_path)
    assert code == "pending-login"
    assert "next login" in message


def test_status_reports_a_broken_install_over_the_login(gnome, tmp_path):
    code, message = shell.status(tmp_path)
    assert code == "broken"
    assert "not installed" in message


def test_status_separates_disabled_from_pending(gnome, tmp_path, monkeypatch):
    (tmp_path / shell.EXTENSION_UUID).mkdir()
    monkeypatch.setattr(shell, "is_enabled", lambda: False)
    assert shell.status(tmp_path)[0] == "disabled"


def test_status_does_not_send_a_failed_load_around_the_login_loop(gnome, tmp_path, monkeypatch):
    """An extension that threw on load will throw again after the next login."""
    (tmp_path / shell.EXTENSION_UUID).mkdir()
    monkeypatch.setattr(shell, "load_state", lambda: "error")
    assert shell.status(tmp_path)[0] == "error"


def test_status_is_active_when_the_bus_answers(gnome, tmp_path, monkeypatch):
    monkeypatch.setattr(shell, "is_available", lambda: True)
    assert shell.status(tmp_path)[0] == "active"


def test_status_says_nothing_to_fix_without_gnome(monkeypatch, tmp_path):
    monkeypatch.setattr(shell.shutil, "which", lambda name: None)
    assert shell.status(tmp_path)[0] == "no-shell"


def test_load_state_reads_the_shells_own_answer(monkeypatch):
    monkeypatch.setattr(shell.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        shell.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="  State: ACTIVE\n"),
    )
    assert shell.load_state() == "active"


def test_load_state_calls_an_unknown_uuid_unscanned(monkeypatch):
    """`gnome-extensions info` fails for an extension installed since login."""
    monkeypatch.setattr(shell.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        shell.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=2, stdout=""),
    )
    assert shell.load_state() == "unscanned"
