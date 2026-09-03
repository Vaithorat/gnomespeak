"""Tests for first-run setup: the system-dependency script and `make dev`'s
extension step.

The rule both halves are held to is the same one: setting up a machine may
install things and may ask for a password, but it must never fail the run.
Every dependency here backs a feature that reports its own absence, so a box
with no sudo, an unknown distro or no GNOME at all should still end up with a
server it can start.
"""

import json
import os
import shutil
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest

from vt import cli, package, shell

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
    "wireplumber", "xdg-user-dirs", "libnotify", "udisks",
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


# --- the one-command installer ----------------------------------------------

INSTALL_SCRIPT = ROOT / "install.sh"


def test_the_installer_is_executable_and_parses():
    assert os.access(INSTALL_SCRIPT, os.X_OK)
    parsed = subprocess.run(
        [BASH, "-n", str(INSTALL_SCRIPT)], capture_output=True, text=True
    )
    assert parsed.returncode == 0, parsed.stderr


def test_the_installer_handles_an_externally_managed_python():
    """PEP 668 makes a bare `pip install` fail on every current distro.

    Ubuntu 24.04, Debian 12 and Fedora 39 onwards all ship
    EXTERNALLY-MANAGED, and pip then refuses with
    "error: externally-managed-environment" -- which would end this script
    having installed the system packages and nothing else.
    """
    text = INSTALL_SCRIPT.read_text()
    assert "EXTERNALLY-MANAGED" in text
    assert "pipx install --system-site-packages" in text
    assert "--break-system-packages" in text


def test_the_installer_asks_for_the_extras_a_phone_remote_needs():
    assert "gnomespeak[qr,youtube,push]" in INSTALL_SCRIPT.read_text()


# --- `vt install-extension --if-needed` --------------------------------------

@pytest.fixture
def extension_dir(tmp_path, monkeypatch):
    directory = tmp_path / "extensions"
    directory.mkdir()
    monkeypatch.setattr(shell, "extensions_dir", lambda: directory)
    return directory


def write_extension(directory: Path, version: int) -> Path:
    """An extension tree on disk, the way both a source and an install look."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metadata.json").write_text(
        json.dumps({"uuid": shell.EXTENSION_UUID, "version": version})
    )
    (directory / "extension.js").write_text(f"// version {version}\n")
    return directory


def test_if_needed_is_a_no_op_when_the_install_is_healthy(extension_dir, monkeypatch, capsys):
    write_extension(extension_dir / shell.EXTENSION_UUID, _shipped_version())
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli, "_enabled_extensions", lambda: [shell.EXTENSION_UUID])
    # Nothing should reach the system: no gsettings write, no shell command.
    monkeypatch.setattr(cli, "enable_extension", _must_not_run)

    cli.cmd_install_extension(Namespace(if_needed=True))

    assert "installed" in capsys.readouterr().out


def test_if_needed_repairs_an_install_that_is_not_enabled(extension_dir, monkeypatch, capsys):
    """Installed but not in the enabled list looks exactly like not installed."""
    write_extension(extension_dir / shell.EXTENSION_UUID, _shipped_version())
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(shell, "enabled_uuids", lambda: ["other@example.com"])
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
    # Neither the checkout nor the copy a wheel installs: `pip install` without
    # the data files is exactly this state.
    monkeypatch.setattr(package, "source_dir", lambda uuid=None: tmp_missing_root())

    cli.cmd_install_extension(Namespace(if_needed=True))

    assert "Extension source not found" in capsys.readouterr().out


def test_a_wheel_install_is_copied_rather_than_symlinked(extension_dir, monkeypatch, capsys):
    """pip owns its data directory; a symlink into it dangles at the next upgrade.

    GNOME Shell drops an extension whose directory is a broken symlink without
    a word, so from the phone it reads as the extension misbehaving rather than
    as pip having moved it.
    """
    source = write_extension(extension_dir.parent / "wheel-data" / shell.EXTENSION_UUID, 4)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(package, "source_dir", lambda uuid=shell.EXTENSION_UUID: source)
    monkeypatch.setattr(package, "is_checkout", lambda path, uuid=None: False)
    monkeypatch.setattr(cli, "disable_extension", lambda uuid: False)
    monkeypatch.setattr(cli, "enable_extension", lambda uuid: (True, "Extension enabled"))

    cli.cmd_install_extension(Namespace(if_needed=False))

    target = extension_dir / shell.EXTENSION_UUID
    assert target.is_dir() and not target.is_symlink()
    assert (target / "extension.js").read_text() == "// version 4\n"


def test_a_checkout_is_symlinked_so_edits_are_live(extension_dir, monkeypatch, capsys):
    source = write_extension(extension_dir.parent / "checkout" / shell.EXTENSION_UUID, 4)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(package, "source_dir", lambda uuid=shell.EXTENSION_UUID: source)
    monkeypatch.setattr(package, "is_checkout", lambda path, uuid=None: True)
    monkeypatch.setattr(cli, "disable_extension", lambda uuid: False)
    monkeypatch.setattr(cli, "enable_extension", lambda uuid: (True, "Extension enabled"))

    cli.cmd_install_extension(Namespace(if_needed=False))

    assert (extension_dir / shell.EXTENSION_UUID).is_symlink()


def test_an_upgrade_refreshes_a_copy_left_behind_by_pip(extension_dir, monkeypatch, capsys):
    """`pip install -U` replaces the source and cannot touch the installed copy.

    An extension one version behind the server that calls it is the state
    `vt doctor` reports as "running an older build", one failing feature at a
    time -- so --if-needed treats it as work to do rather than as healthy.
    """
    installed = write_extension(extension_dir / shell.EXTENSION_UUID, 3)
    source = write_extension(extension_dir.parent / "wheel-data" / shell.EXTENSION_UUID, 4)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(package, "source_dir", lambda uuid=shell.EXTENSION_UUID: source)
    monkeypatch.setattr(package, "is_checkout", lambda path, uuid=None: False)
    monkeypatch.setattr(shell, "enabled_uuids", lambda: [shell.EXTENSION_UUID])
    monkeypatch.setattr(cli, "disable_extension", lambda uuid: False)
    monkeypatch.setattr(cli, "enable_extension", lambda uuid: (True, "Extension enabled"))

    cli.cmd_install_extension(Namespace(if_needed=True))

    assert (installed / "extension.js").read_text() == "// version 4\n"
    assert "version 3 → 4" in capsys.readouterr().out


def test_a_symlinked_checkout_is_never_treated_as_stale(extension_dir, monkeypatch, capsys):
    """The symlink is the source; there is no older copy to bring forward."""
    source = write_extension(extension_dir.parent / "checkout" / shell.EXTENSION_UUID, 4)
    (extension_dir / shell.EXTENSION_UUID).symlink_to(source)
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(package, "source_dir", lambda uuid=shell.EXTENSION_UUID: source)
    monkeypatch.setattr(cli, "_enabled_extensions", lambda: [shell.EXTENSION_UUID])
    monkeypatch.setattr(cli, "enable_extension", _must_not_run)

    cli.cmd_install_extension(Namespace(if_needed=True))

    assert "installed" in capsys.readouterr().out


def _shipped_version() -> int:
    """The version in the extension source this checkout would install."""
    return package.metadata_version(package.source_dir())


def tmp_missing_root() -> Path:
    """A path where no extension source exists, checkout or installed."""
    return Path("/nonexistent/gnome-extension/gnomespeak@local")


def _must_not_run(*args, **kwargs):
    raise AssertionError("a healthy install should not touch the system")
