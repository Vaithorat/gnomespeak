"""Tests for the systemd user unit: what it says, and what installing it runs.

No systemctl is invoked. Every call is recorded, which is the point: the bugs
worth catching here are "wrote the unit and never enabled it" and "enabled a
system unit instead of a user one", and both are visible in the argument list.
"""

from types import SimpleNamespace

import pytest

from vt import service


@pytest.fixture
def systemd(tmp_path, monkeypatch):
    """A fake `systemctl --user` that records calls and succeeds."""
    calls = []

    def fake(*args, timeout=15.0):
        calls.append(list(args))
        if args[:1] == ("show",):
            return SimpleNamespace(returncode=0, stdout="enabled\n", stderr="")
        if args[:1] == ("is-active",):
            return SimpleNamespace(returncode=0, stdout="active\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(service, "systemctl", fake)
    return calls


# --- the unit itself --------------------------------------------------------

def test_the_unit_is_bound_to_the_desktop_session():
    """Every source vt reads dies with the session; so must the server."""
    text = service.unit_text(port=9000)
    assert f"PartOf={service.SESSION_TARGET}" in text
    assert f"WantedBy={service.SESSION_TARGET}" in text


def test_the_unit_requires_pairing():
    """A banner nobody reads is not a credential."""
    assert "--require-pairing" in service.unit_text()


def test_the_unit_carries_the_port_and_the_tunnel_name():
    text = service.unit_text(port=9100, tunnel_name="home")
    assert "--port 9100" in text
    assert "--tunnel-name home" in text


def test_the_unit_runs_an_absolute_path(monkeypatch):
    """The shell that installed it is long gone by the next login."""
    monkeypatch.setattr(service.shutil, "which", lambda name: "/usr/local/bin/vt")
    assert service.exec_start(port=8765).startswith("/")


# --- install / uninstall ----------------------------------------------------

def test_install_writes_enables_and_starts(systemd):
    result = service.install(port=9000)

    assert result["ok"]
    assert service.unit_path().exists()
    assert ["daemon-reload"] in systemd
    assert ["enable", service.UNIT_NAME] in systemd
    # restart, not start: a reinstall on a new port must replace the old server
    # rather than leave it holding the old one.
    assert ["restart", service.UNIT_NAME] in systemd


def test_install_can_skip_starting(systemd):
    service.install(start=False)
    assert not any(call[:1] == ["restart"] for call in systemd)


def test_install_reports_a_desktop_that_never_reaches_the_target(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(
        service, "systemctl",
        lambda *a, timeout=15.0: SimpleNamespace(
            returncode=0, stdout=("inactive\n" if a[:1] == ("is-active",) else ""), stderr=""
        ),
    )
    assert service.install()["session_target"] is False


def test_install_without_systemd_changes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(service, "systemctl", lambda *a, timeout=15.0: None)

    result = service.install()

    assert not result["ok"]
    assert not service.unit_path().exists()


def test_uninstall_disables_and_removes(systemd):
    service.install()
    result = service.uninstall()

    assert result["ok"]
    assert not service.unit_path().exists()
    assert ["disable", "--now", service.UNIT_NAME] in systemd


def test_uninstall_is_fine_when_nothing_is_installed(systemd):
    result = service.uninstall()
    assert result["ok"] and "Nothing" in result["message"]


# --- status -----------------------------------------------------------------

def test_status_reports_a_running_unit(systemd, monkeypatch):
    service.install()
    monkeypatch.setattr(
        service, "_property",
        lambda name: "enabled" if name == "UnitFileState" else "active",
    )
    state = service.status()
    assert state["installed"] and state["enabled"] and state["active"]


def test_status_names_an_installed_but_disabled_unit(systemd, monkeypatch):
    """Exactly the state in which a reboot silently starts nothing."""
    service.install()
    monkeypatch.setattr(service, "_property", lambda name: "disabled")

    state = service.status()

    assert state["installed"] and not state["enabled"]
    assert "not enabled" in state["detail"]


def test_status_without_systemd_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(service, "systemctl", lambda *a, timeout=15.0: None)
    assert service.status()["available"] is False
