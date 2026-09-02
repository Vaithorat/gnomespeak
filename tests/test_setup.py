"""Tests for first-run setup: the system-dependency script and `make dev`'s
extension step.

The rule both halves are held to is the same one: setting up a machine may
install things and may ask for a password, but it must never fail the run.
Every dependency here backs a feature that reports its own absence, so a box
with no sudo, an unknown distro or no GNOME at all should still end up with a
server it can start.
"""

import os
import shutil
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from vt import cli, shell

ROOT = Path(__file__).resolve().parent.parent
SETUP_SCRIPT = ROOT / "scripts" / "setup-system.sh"
# Resolved once, and absolute: several tests hand the script a PATH with no
# package manager on it, which is also a PATH with no bash on it.
BASH = shutil.which("bash") or "/bin/bash"


# --- the system-dependency script -------------------------------------------

def run_setup(*args, env=None):
    environment = dict(os.environ)
    environment.update(env or {})
    return subprocess.run(
        [BASH, str(SETUP_SCRIPT), *args],
        capture_output=True, text=True, timeout=60, env=environment,
    )


def test_the_setup_script_is_executable_and_parses():
    assert os.access(SETUP_SCRIPT, os.X_OK)
    parsed = subprocess.run(
        [BASH, "-n", str(SETUP_SCRIPT)], capture_output=True, text=True
    )
    assert parsed.returncode == 0, parsed.stderr


def test_check_mode_installs_nothing_and_succeeds():
    result = run_setup("--check")
    assert result.returncode == 0
    assert "system dependencies" in result.stdout


def test_an_unknown_distribution_is_not_an_error():
    """No apt, no dnf, no pacman, no zypper -- and nothing this can install.

    A machine we do not know how to install packages on is the case most likely
    to abort a build, and the one where aborting helps least: vt runs on it, it
    just runs with fewer features.
    """
    # A PATH with only the interpreter's own directory: no package manager, and
    # none of the tools the script probes for, so everything reads as missing.
    result = run_setup(env={"PATH": "/nonexistent", "XDG_SESSION_TYPE": "wayland"})
    assert result.returncode == 0
    assert "unrecognised distribution" in result.stdout


def test_yes_mode_does_not_wait_for_a_password(tmp_path):
    """--yes is for CI, where a sudo prompt is a hang, not a question."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    # A sudo that refuses -n (as a passwordless-less sudo does) and an apt-get
    # that would succeed, so reaching the install at all would be the bug.
    (fake_bin / "sudo").write_text("#!/bin/sh\nexit 1\n")
    (fake_bin / "apt-get").write_text("#!/bin/sh\nexit 0\n")
    for name in ("sudo", "apt-get"):
        (fake_bin / name).chmod(0o755)

    result = run_setup("--yes", env={"PATH": str(fake_bin), "XDG_SESSION_TYPE": "wayland"})
    assert result.returncode == 0
    assert "--yes was given" in result.stdout


def test_x11_only_tools_are_skipped_on_wayland():
    """xdotool under Wayland is a package that can never do anything.

    Only the compositor may synthesize input there, so the fallback tools are
    requested for an X11 session and not otherwise.
    """
    wayland = run_setup("--check", env={"XDG_SESSION_TYPE": "wayland", "PATH": "/nonexistent"})
    x11 = run_setup("--check", env={"XDG_SESSION_TYPE": "x11", "PATH": "/nonexistent"})
    assert "xdotool" not in wayland.stdout
    assert "xdotool" in x11.stdout


@pytest.mark.parametrize("capability", [
    "venv", "dbus", "gi", "wl-clipboard", "xclip", "dbus-monitor",
    "wireplumber", "xdg-user-dirs",
])
def test_every_capability_has_a_package_on_every_distro(capability):
    """A capability with no package name anywhere is a silent gap.

    The script skips what it cannot name, so a missing entry here would show up
    as a feature quietly never being installed rather than as an error.
    """
    for distro in ("debian", "fedora", "arch", "suse"):
        # venv is part of the base install everywhere except Debian, which is
        # the one distro that splits it out -- an empty answer is correct there.
        if capability == "venv" and distro != "debian":
            continue
        probe = run_setup("--package", capability, distro)
        assert probe.stdout.strip(), f"{capability} has no package on {distro}"


# --- `vt install-extension --if-needed` --------------------------------------

@pytest.fixture
def extension_dir(tmp_path, monkeypatch):
    directory = tmp_path / "extensions"
    directory.mkdir()
    monkeypatch.setattr(shell, "extensions_dir", lambda: directory)
    return directory


def test_if_needed_is_a_no_op_when_the_install_is_healthy(extension_dir, monkeypatch, capsys):
    (extension_dir / shell.EXTENSION_UUID).mkdir()
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli, "_enabled_extensions", lambda: [shell.EXTENSION_UUID])
    # Nothing should reach the system: no gsettings write, no shell command.
    monkeypatch.setattr(cli, "enable_extension", _must_not_run)

    cli.cmd_install_extension(Namespace(if_needed=True))

    assert "installed" in capsys.readouterr().out


def test_if_needed_repairs_an_install_that_is_not_enabled(extension_dir, monkeypatch, capsys):
    """Installed but not in the enabled list looks exactly like not installed."""
    (extension_dir / shell.EXTENSION_UUID).mkdir()
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli, "_enabled_extensions", lambda: ["other@example.com"])
    monkeypatch.setattr(cli, "disable_extension", lambda uuid: False)
    enabled = []
    monkeypatch.setattr(
        cli, "enable_extension",
        lambda uuid: (enabled.append(uuid), (True, "Extension enabled"))[1],
    )

    cli.cmd_install_extension(Namespace(if_needed=True))

    assert enabled == [shell.EXTENSION_UUID]


def test_if_needed_skips_a_machine_without_gnome(extension_dir, monkeypatch, capsys):
    """No GNOME Shell is a fact about the machine, not a failure to report."""
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(cli, "enable_extension", _must_not_run)

    cli.cmd_install_extension(Namespace(if_needed=True))

    out = capsys.readouterr().out
    assert "No GNOME Shell" in out
    assert not list(extension_dir.iterdir())


def test_a_missing_source_tree_does_not_fail_the_setup(extension_dir, monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli, "_enabled_extensions", lambda: [])
    monkeypatch.setattr(shell, "install_problems", lambda base=None: ["not installed"])
    monkeypatch.setattr(cli, "__file__", str(tmp_missing_root()))

    cli.cmd_install_extension(Namespace(if_needed=True))

    assert "Extension source not found" in capsys.readouterr().out


def tmp_missing_root() -> Path:
    """A path whose parent has no gnome-extension/ directory beside it."""
    return Path("/nonexistent/vt/cli.py")


def _must_not_run(*args, **kwargs):
    raise AssertionError("a healthy install should not touch the system")
