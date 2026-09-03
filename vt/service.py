"""The systemd user unit that starts the server with the desktop session.

A remote you have to walk over to the PC and start is not a remote, and this is
the one axis where every comparable tool beats us today. The fix is a unit, and
the only real decision in it is *user*, not system: every source vt reads --
MPRIS, the GNOME Shell extension, the session bus, PipeWire, the clipboard --
lives inside the login session and does not exist outside it. A system unit
would come up at boot with none of them, and would report an empty desktop
rather than an error.

The unit is therefore bound to `graphical-session.target`: it starts when the
desktop does, and it stops when the desktop does, which is also what makes a
second login not leave two servers fighting over the port.

Getting in afterwards is pairing, not the startup token. A service prints its
banner where nobody reads it, so a token nobody has seen is not a credential --
`vt pair` mints a code from the terminal instead, against the same file the
running server reads.
"""

import os
import shutil
import subprocess
from pathlib import Path

UNIT_NAME = "gnomespeak.service"
SESSION_TARGET = "graphical-session.target"


def unit_dir() -> Path:
    """Where a user's own systemd units live."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def unit_path() -> Path:
    return unit_dir() / UNIT_NAME


def vt_executable() -> str:
    """The `vt` this unit should run.

    sys.argv[0] would be right for a venv install and wrong for `python -m vt`,
    and the unit outlives the shell that created it either way -- so an
    absolute path is the only form that still means the same thing at the next
    login.
    """
    import sys

    candidate = Path(sys.argv[0]).resolve()
    if candidate.name == "vt" and candidate.exists():
        return str(candidate)
    found = shutil.which("vt")
    if found:
        return str(Path(found).resolve())
    # Last resort: this interpreter, running the package. Still absolute, and
    # still the same interpreter that has vt's dependencies installed.
    return f"{sys.executable} -m vt"


def exec_start(*, port: int = 8765, tunnel_name: str = "", host: str = "") -> str:
    """The ExecStart line for the requested shape of server."""
    command = f"{vt_executable()} serve --port {port}"
    if host:
        command += f" --host {host}"
    if tunnel_name:
        command += f" --tunnel-name {tunnel_name}"
    # Nothing on the terminal to read, so the token cannot be a way in. Pairing
    # works from any network and survives restarts, which a fresh random token
    # printed to the journal does not.
    command += " --require-pairing"
    return command


def unit_text(*, port: int = 8765, tunnel_name: str = "", host: str = "") -> str:
    return f"""[Unit]
Description=GnomeSpeak remote control
Documentation=https://github.com/Vaithorat/gnomespeak
After={SESSION_TARGET}
PartOf={SESSION_TARGET}

[Service]
Type=simple
ExecStart={exec_start(port=port, tunnel_name=tunnel_name, host=host)}
Restart=on-failure
RestartSec=3
# The server talks to the session bus, PipeWire and the Shell extension, all of
# which live in this session; systemd's own environment is what carries them in.
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy={SESSION_TARGET}
"""


def systemctl(*args, timeout: float = 15.0):
    """Run `systemctl --user ...`, or None where systemd is not in charge."""
    if not shutil.which("systemctl"):
        return None
    try:
        return subprocess.run(
            ["systemctl", "--user", *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except Exception:
        return None


def is_available() -> bool:
    """Whether there is a systemd user manager to install into."""
    result = systemctl("is-system-running")
    return result is not None


def _property(name: str) -> str:
    result = systemctl("show", UNIT_NAME, "--property", name, "--value")
    if result is None or result.returncode != 0:
        return ""
    return result.stdout.strip()


def status() -> dict:
    """What the unit is doing, in the terms `vt doctor` reports.

    `installed` is the file on disk, `enabled` is whether the next login starts
    it, and `active` is whether it is running now. They come apart in ways that
    matter: an installed-but-not-enabled unit is exactly what a reboot silently
    fails to start.
    """
    path = unit_path()
    if not is_available():
        return {
            "available": False, "installed": path.exists(), "enabled": False,
            "active": False, "detail": "no systemd user manager on this machine",
        }
    installed = path.exists()
    enabled = _property("UnitFileState") == "enabled"
    active = _property("ActiveState") == "active"
    detail = ""
    if installed and not enabled:
        detail = "installed but not enabled — it will not start at the next login"
    elif installed and not active:
        # Normal when the unit was just written and the session target has
        # already been reached; misleading if not said.
        detail = "enabled; it starts with the next desktop session"
    return {
        "available": True, "installed": installed, "enabled": enabled,
        "active": active, "detail": detail,
    }


def session_target_active() -> bool:
    """Whether this desktop actually reaches graphical-session.target.

    The unit hangs off that target, so a desktop that never reaches it would
    install cleanly and then never start. Better to say so at install time than
    to be discovered after a reboot.
    """
    result = systemctl("is-active", SESSION_TARGET)
    return bool(result and result.stdout.strip() == "active")


def install(*, port: int = 8765, tunnel_name: str = "", host: str = "", start: bool = True) -> dict:
    """Write, enable and (by default) start the unit. Returns a result dict."""
    if not is_available():
        return {"ok": False, "message": "No systemd user manager here — nothing to install into."}

    directory = unit_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        unit_path().write_text(unit_text(port=port, tunnel_name=tunnel_name, host=host))
    except OSError as e:
        return {"ok": False, "message": f"Could not write {unit_path()}: {e}"}

    systemctl("daemon-reload")
    enabled = systemctl("enable", UNIT_NAME)
    if enabled is None or enabled.returncode != 0:
        reason = (enabled.stderr.strip() if enabled else "systemctl is unavailable")
        return {"ok": False, "message": f"Wrote the unit but could not enable it: {reason}"}

    started = None
    if start:
        # restart, not start: reinstalling with a different port has to replace
        # the running server, not leave the old one holding the old port.
        started = systemctl("restart", UNIT_NAME)

    return {
        "ok": True,
        "message": f"Installed {UNIT_NAME}",
        "path": str(unit_path()),
        "started": bool(started and started.returncode == 0),
        "start_error": (started.stderr.strip() if started and started.returncode != 0 else ""),
        "session_target": session_target_active(),
    }


def uninstall() -> dict:
    """Stop, disable and remove the unit, leaving nothing behind."""
    existed = unit_path().exists()
    if is_available():
        systemctl("disable", "--now", UNIT_NAME)
    try:
        unit_path().unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        return {"ok": False, "message": f"Could not remove {unit_path()}: {e}"}
    if is_available():
        systemctl("daemon-reload")
        systemctl("reset-failed", UNIT_NAME)
    return {
        "ok": True,
        "message": f"Removed {UNIT_NAME}" if existed else "Nothing was installed",
    }
