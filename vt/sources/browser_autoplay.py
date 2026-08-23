"""Whether the browser will actually start a video vt opens for it.

Opening a YouTube URL with xdg-open is not the same as playing it. Firefox
blocks autoplay of audible media by default, so the tab loads *paused*: no
sound, no MPRIS player published, nothing under Players. From the phone that
looks like vt did nothing, and the only way forward is to walk to the PC and
press play -- which defeats the point of a phone remote.

`media.autoplay.default = 0` is the same setting as "Allow Audio and Video" in
Firefox's own Settings -> Privacy & Security -> Autoplay. With it set, a video
opened from the phone starts on its own and Firefox publishes an MPRIS player
within a few seconds, so it appears under Players with full transport controls.

This module finds the profile, reports the current setting, and can write it.
The write goes to user.js rather than prefs.js because Firefox rewrites prefs.js
from memory when it exits -- an edit made while it is running would be thrown
away. user.js is the supported way in, and it is re-applied on every start,
which is why `set_autoplay(allow=False)` removes the line again rather than
writing the opposite value: reverting should hand the setting back to the
Settings UI, not keep overriding it.
"""

import configparser
import re
import shutil
import subprocess
import time
from pathlib import Path

PREF = "media.autoplay.default"
ALLOW_ALL = 0        # Firefox: "Allow Audio and Video"
BLOCK_AUDIBLE = 1    # Firefox's default
BLOCK_ALL = 5

# The three ways Firefox is packaged on the distros vt supports. Snap and
# flatpak each relocate the profile, and the snap build cannot even see
# ~/.mozilla, so guessing one path would break for most Ubuntu users.
_PROFILE_ROOTS = (
    "~/.mozilla/firefox",
    "~/snap/firefox/common/.mozilla/firefox",
    "~/.var/app/org.mozilla.firefox/.mozilla/firefox",
)

_MARKER = "/* set by vt allow-autoplay */"

# state() is read by doctor, by the snapshot, and before every play. Those are
# three small file reads a second in the worst case; cache them briefly.
_CACHE_TTL = 5.0
_cache: tuple[float, tuple] | None = None


def profile_roots() -> list[Path]:
    """Existing Firefox profile roots, in packaging-preference order."""
    return [p for p in (Path(r).expanduser() for r in _PROFILE_ROOTS) if p.is_dir()]


def _ini_candidates(parser: configparser.ConfigParser) -> list[str]:
    """Profile paths from profiles.ini, best guess first.

    profiles.ini names the default twice and the two can disagree: an
    [InstallXXXX] section points at the profile for that particular Firefox
    install, and it wins over a [ProfileN] entry marked Default=1. Preferring
    the Install section is what keeps this correct for anyone who has ever run
    the profile manager.
    """
    installs, defaults, rest = [], [], []
    for section in parser.sections():
        name = section.lower()
        if name.startswith("install"):
            if parser.has_option(section, "Default"):
                installs.append(parser.get(section, "Default"))
        elif name.startswith("profile"):
            path = parser.get(section, "Path", fallback="")
            if parser.get(section, "Default", fallback="") == "1":
                defaults.append(path)
            else:
                rest.append(path)
    return [p for p in installs + defaults + rest if p]


def default_profile() -> Path | None:
    """The profile Firefox actually starts with, or None if it cannot be found."""
    for root in profile_roots():
        ini = root / "profiles.ini"
        if not ini.is_file():
            continue

        parser = configparser.ConfigParser()
        try:
            parser.read(ini)
        except (configparser.Error, OSError):
            continue

        for rel in _ini_candidates(parser):
            path = Path(rel)
            resolved = path if path.is_absolute() else root / path
            if resolved.is_dir():
                return resolved

    # No profiles.ini (a fresh install that has never been launched) -- fall
    # back to the conventional directory name.
    for root in profile_roots():
        for entry in sorted(root.glob("*.default*")):
            if entry.is_dir():
                return entry
    return None


def _read_pref(path: Path) -> int | None:
    """The value of PREF in one prefs file, or None if it is not set there."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # user_pref("media.autoplay.default", 0);  -- whitespace varies by writer.
    match = re.search(
        r'user_pref\(\s*"%s"\s*,\s*(-?\d+)\s*\)' % re.escape(PREF), text
    )
    return int(match.group(1)) if match else None


def _effective_pref(profile: Path) -> int:
    """PREF as Firefox will see it.

    user.js is replayed over prefs.js on every start, so when both set the pref
    only user.js matters. Absent either, Firefox's built-in default applies.
    """
    for name in ("user.js", "prefs.js"):
        value = _read_pref(profile / name)
        if value is not None:
            return value
    return BLOCK_AUDIBLE


def default_browser() -> str:
    """The desktop id of the default browser, or "" if it cannot be determined."""
    if not shutil.which("xdg-settings"):
        return ""
    try:
        result = subprocess.run(
            ["xdg-settings", "get", "default-web-browser"],
            capture_output=True, text=True, timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def is_firefox_default() -> bool:
    return "firefox" in default_browser().lower()


def firefox_pids() -> list[int]:
    """PIDs of running Firefox main processes (not content children)."""
    try:
        import psutil
    except ImportError:
        return []

    pids = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if "firefox" not in name:
                continue
            cmdline = proc.info.get("cmdline") or []
            # Content/GPU/utility children all carry -contentproc; the parent
            # is the one without it. Killing a child achieves nothing.
            if any(arg == "-contentproc" for arg in cmdline):
                continue
            pids.append(proc.info["pid"])
        except Exception:
            continue
    return pids


def state(force: bool = False) -> dict:
    """How autoplay is configured right now.

    Returns a dict with:
      status   "allowed" | "blocked" | "unknown"
      reason   one sentence, safe to show on the phone
      fix      what to do about it, or "" when nothing needs doing
      profile  the profile path as a string, or ""
    """
    global _cache
    now = time.monotonic()
    if not force and _cache and now - _cache[0] < _CACHE_TTL:
        return dict(_cache[1])

    result = _state_uncached()
    _cache = (now, result)
    return dict(result)


def _state_uncached() -> dict:
    browser = default_browser()
    profile = default_profile()

    if profile is None:
        if browser and "firefox" not in browser.lower():
            return {
                "status": "unknown",
                "reason": (
                    f"Your default browser ({browser}) is not Firefox, and vt "
                    "cannot change its autoplay policy from outside."
                ),
                "fix": "",
                "profile": "",
            }
        return {
            "status": "unknown",
            "reason": "No Firefox profile found, so autoplay policy is unknown.",
            "fix": "",
            "profile": "",
        }

    value = _effective_pref(profile)
    if value == ALLOW_ALL:
        return {
            "status": "allowed",
            "reason": "Firefox allows autoplay; videos opened from the phone start on their own.",
            "fix": "",
            "profile": str(profile),
        }

    label = "all media" if value == BLOCK_ALL else "audible media"
    return {
        "status": "blocked",
        "reason": (
            f"Firefox blocks autoplay of {label}, so a video opened from the "
            "phone loads paused and never reaches Players."
        ),
        "fix": "Run 'vt allow-autoplay' on the PC, then restart Firefox.",
        "profile": str(profile),
    }


def set_autoplay(allow: bool = True) -> dict:
    """Write (or remove) the autoplay pref in the default profile's user.js.

    Returns {"ok", "message", "needs_restart"}. Firefox reads user.js once at
    startup, so a change never takes effect in the running instance -- saying so
    is the difference between this working and the user assuming it did not.
    """
    profile = default_profile()
    if profile is None:
        return {
            "ok": False,
            "message": "No Firefox profile found; nothing to change.",
            "needs_restart": False,
        }

    user_js = profile / "user.js"
    error = _rewrite_user_js(user_js, allow)
    if error:
        return {"ok": False, "message": error, "needs_restart": False}

    _invalidate()
    running = bool(firefox_pids())
    if allow:
        return {
            "ok": True,
            "message": f"Autoplay allowed in {user_js}",
            "needs_restart": running,
            "residual": "",
        }

    # Removing the override does not necessarily restore the old behaviour.
    # Firefox copies whatever user.js set into prefs.js when it shuts down, so
    # the value outlives the file that introduced it -- and vt cannot edit
    # prefs.js back, because Firefox rewrites it from memory on exit. Saying
    # "reverted" here without this would be wrong in the common case.
    residual = ""
    if _read_pref(profile / "prefs.js") == ALLOW_ALL:
        residual = (
            "Firefox has already saved this setting in its own preferences, so "
            "autoplay stays allowed. To undo it fully, set Settings -> Privacy & "
            "Security -> Autoplay back to 'Block Audio'."
        )
    return {
        "ok": True,
        "message": f"Autoplay override removed from {user_js}",
        "needs_restart": running,
        "residual": residual,
    }


def _rewrite_user_js(user_js: Path, allow: bool) -> str:
    """Set or clear our pref line in user.js. Returns "" or an error message."""
    try:
        existing = user_js.read_text(encoding="utf-8") if user_js.is_file() else ""
    except OSError as e:
        return f"Cannot read {user_js}: {e}"

    # Drop any line we or the user previously wrote for this pref, so repeated
    # runs cannot stack duplicates that shadow each other.
    kept = [
        line for line in existing.splitlines()
        if PREF not in line and line.strip() != _MARKER
    ]
    while kept and not kept[-1].strip():
        kept.pop()

    if allow:
        kept.append(_MARKER)
        kept.append(f'user_pref("{PREF}", {ALLOW_ALL});')
    body = "\n".join(kept)
    if body:
        body += "\n"

    try:
        if body.strip():
            user_js.write_text(body, encoding="utf-8")
        elif user_js.is_file():
            # Reverting an otherwise-empty user.js should leave no file behind,
            # so Firefox's own Settings UI is authoritative again.
            user_js.unlink()
    except OSError as e:
        return f"Cannot write {user_js}: {e}"
    return ""


def restart_firefox(reopen_url: str = "") -> dict:
    """Ask Firefox to quit, then start it again.

    SIGTERM is the same signal the window manager sends when you close the last
    window, so Firefox shuts down cleanly and restores its tabs on the next
    start; SIGKILL would lose them. If it has not gone after the grace period
    vt reports that rather than escalating, because forcing it is exactly the
    case where the user's tabs are at risk.

    The grace period is short on purpose: this runs on the server's single
    worker thread, so every second spent waiting is a second the state snapshot
    does not refresh. Firefox normally exits in two or three.
    """
    pids = firefox_pids()
    if not pids:
        return _launch_firefox(reopen_url, was_running=False)

    try:
        import psutil
    except ImportError:
        return {"ok": False, "message": "psutil is required to restart Firefox."}

    procs = []
    for pid in pids:
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            procs.append(proc)
        except Exception:
            continue

    _, alive = psutil.wait_procs(procs, timeout=10)
    if alive:
        return {
            "ok": False,
            "message": (
                "Firefox did not exit within 10s; it may be asking to confirm. "
                "Close it on the PC and the new setting applies on the next start."
            ),
        }

    # Firefox refuses to start while its profile lock is still being released.
    time.sleep(1.5)
    return _launch_firefox(reopen_url, was_running=True)


def _launch_firefox(url: str, was_running: bool) -> dict:
    argv = ["firefox"]
    if url:
        argv += ["--new-window", url]
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        return {"ok": False, "message": "firefox is not on PATH."}
    except OSError as e:
        return {"ok": False, "message": f"Could not start Firefox: {e}"}

    what = "restarted" if was_running else "started"
    if url:
        return {"ok": True, "message": f"Firefox {what}; the video should start playing."}
    return {"ok": True, "message": f"Firefox {what}."}


def _invalidate() -> None:
    global _cache
    _cache = None
