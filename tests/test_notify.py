"""Tests for the one place that puts a banner on the PC's screen."""

from vt import notify as mod


class Result:
    def __init__(self, returncode=0, stderr=""):
        self.returncode, self.stderr, self.stdout = returncode, stderr, ""


def test_the_banner_is_attributed_to_gnomespeak(monkeypatch):
    calls = []
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(mod.subprocess, "run", lambda argv, **kw: calls.append(argv) or Result())

    assert mod.notify("Phone battery low", "9% and not charging.")["ok"] is True
    assert calls[0][:5] == ["notify-send", "-u", "normal", "-a", "GnomeSpeak"]
    assert calls[0][5:] == ["Phone battery low", "9% and not charging."]


def test_a_banner_without_a_body_passes_one_argument(monkeypatch):
    calls = []
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(mod.subprocess, "run", lambda argv, **kw: calls.append(argv) or Result())
    mod.notify("Just this")
    assert calls[0][-1] == "Just this"


def test_a_machine_without_notify_send_says_so(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(mod.subprocess, "run", _must_not_run)
    assert mod.notify("Anything")["ok"] is False


def test_notify_send_failing_is_reported(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(mod.subprocess, "run",
                        lambda argv, **kw: Result(returncode=1, stderr="no session bus\n"))
    result = mod.notify("Anything")
    assert result["ok"] is False and "no session bus" in result["message"]


def _must_not_run(*args, **kwargs):
    raise AssertionError("notify-send was called on a machine that does not have it")
