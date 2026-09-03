"""What is working and what is not, in a form a phone can render.

`vt doctor` answers this in a terminal, which is exactly where the person
debugging usually is not: the phone is in their hand and the PC is across the
room. This module produces the same picture as structured rows.

Deliberately narrower than `vt doctor`. It covers what a phone can act on --
the features it can see missing and the fix it can be told -- and leaves out
the checks that only make sense beside the machine, like port availability.
Every row is a read; nothing here changes anything.
"""

import os
import shutil

# ok: works. warn: degraded, and the row says what is lost. info: not
# applicable to this machine, which is not a problem. fail: broken.
OK, WARN, INFO, FAIL = "ok", "warn", "info", "fail"


def _row(check_id, title, state, detail, fix="", lost=""):
    return {"id": check_id, "title": title, "state": state,
            "detail": detail, "fix": fix, "lost": lost}


def _session() -> dict:
    session = os.environ.get("XDG_SESSION_TYPE", "") or (
        "wayland" if os.environ.get("WAYLAND_DISPLAY") else "")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    if not session:
        return _row("session", "Session", INFO, "not a graphical session")
    return _row("session", "Session", OK, " · ".join(p for p in (session, desktop) if p))


def _extension() -> dict:
    from vt import shell

    code, message = shell.status()
    if code == "active":
        missing = shell.missing_methods()
        if not missing:
            return _row("extension", "GNOME extension", OK, "loaded, every method present")
        return _row(
            "extension", "GNOME extension", WARN,
            f"an older build is loaded ({len(missing)} method(s) missing)",
            fix="Run `vt install-extension` on the PC, then log out and back in",
            lost=", ".join(shell.missing_features(missing)),
        )
    if code == "no-shell":
        return _row("extension", "GNOME extension", INFO, message)
    state = WARN if code == "pending-login" else FAIL
    return _row(
        "extension", "GNOME extension", state, message,
        fix=("Log out and back in on the PC" if code == "pending-login"
             else "Run `vt install-extension` on the PC, then log out and back in"),
        lost="windows, workspaces, touchpad, typing",
    )


def _clipboard() -> dict:
    from vt.sources.clipboard import backend

    tool = backend()
    if tool:
        return _row("clipboard", "Clipboard", OK, f"{tool['name']} available")
    return _row("clipboard", "Clipboard", WARN, "no clipboard tool on the PC",
                fix="Install wl-clipboard (Wayland) or xclip (X11)",
                lost="clipboard sync both ways")


def _notifications() -> dict:
    from vt.sources.notifications_mirror import mirror

    feed = mirror()
    if not feed.available():
        return _row("notifications", "Notification mirroring", WARN,
                    "dbus-monitor is not installed",
                    fix="Install dbus-bin (Debian) or dbus-tools (Fedora)",
                    lost="notifications on the phone")
    if feed.error:
        return _row("notifications", "Notification mirroring", WARN, feed.error,
                    lost="notifications on the phone")
    return _row("notifications", "Notification mirroring", OK,
                "running" if feed.running else "ready")


def _audio() -> dict:
    if shutil.which("wpctl"):
        return _row("audio", "Audio", OK, "PipeWire available")
    return _row("audio", "Audio", WARN, "wpctl not found",
                fix="Install pipewire and wireplumber on the PC",
                lost="volume, per-app volume, output switching")


def _screenshot() -> dict:
    from vt.sources import screenshot

    if screenshot.available():
        return _row("screenshot", "Screenshot", OK,
                    "through the desktop portal (it may ask on the PC)")
    return _row("screenshot", "Screenshot", WARN, screenshot.unavailable_message(),
                lost="screenshots")


def _autostart() -> dict:
    from vt import service

    state = service.status()
    if not state.get("available"):
        return _row("autostart", "Starts with the session", INFO, state.get("detail", ""))
    if state.get("active"):
        return _row("autostart", "Starts with the session", OK, "running as a user service")
    if state.get("installed"):
        return _row("autostart", "Starts with the session", WARN,
                    "the unit is installed but not running",
                    fix="Run `vt install-service` on the PC")
    return _row("autostart", "Starts with the session", INFO,
                "not installed — the server was started by hand",
                fix="Run `vt install-service` on the PC")


def _push() -> dict:
    from vt import push

    if not push.available():
        return _row("push", "Notifications with the page closed", WARN,
                    "the cryptography package is missing",
                    fix="Run `pip install gnomespeak[push]` on the PC",
                    lost="notifications and alerts while the page is shut")
    return _row("push", "Notifications with the page closed", OK,
                "ready — turn it on from the notifications screen")


def _transfer() -> dict:
    from vt.sources.transfer import transfer_dir

    directory = transfer_dir()
    if os.access(directory, os.W_OK):
        return _row("files", "File transfer", OK, str(directory))
    return _row("files", "File transfer", WARN, f"{directory} is not writable",
                lost="sending files to the PC")


CHECKS = (_session, _extension, _clipboard, _notifications, _push, _audio,
          _screenshot, _autostart, _transfer)


def collect() -> dict:
    """Every check, plus a one-line summary the phone can show in a header."""
    rows = []
    for check in CHECKS:
        try:
            rows.append(check())
        except Exception as e:
            # A check that throws is itself a finding, and losing the rest of
            # the page because one of them did would be the worse outcome.
            rows.append(_row(getattr(check, "__name__", "check").strip("_"),
                             "Check failed", FAIL, str(e)))
    counts = {state: sum(1 for r in rows if r["state"] == state)
              for state in (OK, WARN, INFO, FAIL)}
    if counts[FAIL]:
        summary = f"{counts[FAIL]} broken, {counts[WARN]} degraded"
    elif counts[WARN]:
        summary = f"{counts[WARN]} thing(s) not working fully"
    else:
        summary = "everything checked is working"
    return {"ok": True, "checks": rows, "counts": counts, "summary": summary}
