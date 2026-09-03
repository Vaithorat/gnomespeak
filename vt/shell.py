"""The GNOME extension's D-Bus identity and capability probe, in one place.

Three modules used to carry their own copy of the bus name, and the rename from
VoiceTalk to GnomeSpeak reached only one of them: `vt doctor` probed
`org.gnome.Shell.Extensions.GnomeSpeak`, which nothing has ever exported, and
so reported the extension missing on every machine where it was running fine.
The name lives here now, and every caller imports it, so a rename cannot
half-land again.

The name itself deliberately keeps the old spelling. It is a wire identifier
shared with an extension that only reloads on log out: changing it would break
every already-installed extension until its owner logged out, to buy nothing a
user can see.
"""

import ast
import re
import shutil
import subprocess
from pathlib import Path

SHELL_BUS_NAME = "org.gnome.Shell.Extensions.VoiceTalk"
SHELL_OBJECT_PATH = "/org/gnome/Shell/Extensions/VoiceTalk"

EXTENSION_UUID = "gnomespeak@local"
# The uuid the same extension carries on extensions.gnome.org. The store
# requires a uuid whose domain half is one the author controls, and "@local" is
# not one -- but the local install predates the listing and still works, so
# both are recognised and neither is rewritten underneath anyone.
STORE_EXTENSION_UUID = "gnomespeak@vaithorat.github.io"
EXTENSION_UUIDS = (EXTENSION_UUID, STORE_EXTENSION_UUID)
# What the extension directory was called before the rename. An install from
# then is a symlink into a path that no longer exists, and GNOME Shell drops a
# dangling extension in silence.
LEGACY_EXTENSION_UUIDS = ("voicetalk@local",)

INTROSPECTABLE = "org.freedesktop.DBus.Introspectable"

# Every method this version of vt calls. A Shell extension only reloads on log
# out, so an updated checkout can sit on disk for days while the old build keeps
# answering -- and every feature added since then fails one at a time with
# nothing tying the failures together. Comparing this set against what the live
# extension introspects to turns that into one line in `vt doctor`.
EXPECTED_METHODS = frozenset({
    "List",
    "Focus",
    "Close",
    "SendKeys",
    "Minimize",
    "Unminimize",
    "Maximize",
    "Unmaximize",
    "MoveToWorkspace",
    "SwitchWorkspace",
    "Workspaces",
    # Pointer, typing and global chords: the remote-input surface.
    "Pointer",
    "Click",
    "Scroll",
    "TypeText",
    "Keys",
})

# Which feature each method carries, for a doctor line that says what is
# missing rather than which symbol is absent.
METHOD_FEATURES = {
    "Minimize": "window minimize/maximize",
    "Unminimize": "window minimize/maximize",
    "Maximize": "window minimize/maximize",
    "Unmaximize": "window minimize/maximize",
    "MoveToWorkspace": "moving windows between workspaces",
    "SwitchWorkspace": "workspace switching",
    "Workspaces": "workspace switching",
    "SendKeys": "browser tab control and YouTube keys",
    "Pointer": "touchpad (pointer control)",
    "Click": "touchpad (pointer control)",
    "Scroll": "touchpad (pointer control)",
    "TypeText": "typing from the phone",
    "Keys": "keyboard shortcuts and the presentation remote",
}

_METHOD_RE = re.compile(r'<method\s+name="([^"]+)"')

try:
    import dbus
except ImportError:  # pragma: no cover - exercised on machines without dbus
    dbus = None


def interface():
    """The extension's D-Bus interface. Raises when it is not running.

    introspect=False: the interface is named explicitly, so the Introspect
    round trip buys nothing -- once per second, forever -- and a confined
    session refuses it anyway.
    """
    if dbus is None:
        raise RuntimeError("python-dbus is not available")
    bus = dbus.SessionBus()
    obj = bus.get_object(SHELL_BUS_NAME, SHELL_OBJECT_PATH, introspect=False)
    return dbus.Interface(obj, SHELL_BUS_NAME)


def methods() -> set:
    """Method names the live extension exports, or an empty set if unreachable.

    Introspection is the only way to ask "which build is loaded?" without
    invoking something for its side effects: calling Workspaces() to find out
    whether Workspaces() exists switches nothing, but Pointer() would move the
    mouse just to prove it can.
    """
    if dbus is None:
        return set()
    try:
        bus = dbus.SessionBus()
        obj = bus.get_object(SHELL_BUS_NAME, SHELL_OBJECT_PATH, introspect=False)
        xml = str(dbus.Interface(obj, INTROSPECTABLE).Introspect(timeout=5))
    except Exception:
        return set()
    return set(_METHOD_RE.findall(xml))


def missing_methods() -> set:
    """Expected methods the running extension does not have.

    An empty set from an extension that is not running at all is indistinguishable
    from a current one here on purpose: callers check availability first.
    """
    live = methods()
    if not live:
        return set()
    return set(EXPECTED_METHODS) - live


def missing_features(missing) -> list:
    """Feature names, deduplicated in a stable order, for a set of methods."""
    seen = []
    for method in sorted(missing):
        feature = METHOD_FEATURES.get(method)
        if feature and feature not in seen:
            seen.append(feature)
    return seen


def extensions_dir() -> Path:
    """Where GNOME Shell looks for a user's extensions."""
    return Path.home() / ".local" / "share" / "gnome-shell" / "extensions"


def system_extensions_dirs() -> list:
    """Where a distribution package puts an extension, as opposed to a user."""
    return [
        Path("/usr/share/gnome-shell/extensions"),
        Path("/usr/local/share/gnome-shell/extensions"),
    ]


def installed_uuids(base: Path = None) -> list:
    """Which of our uuids are actually on disk, user install or system-wide.

    An extension from the store is an ordinary directory; the development
    install is a symlink into the checkout. Both are installs, and nothing
    below may treat one as more real than the other.
    """
    directory = base or extensions_dir()
    found = []
    for uuid in EXTENSION_UUIDS:
        if (directory / uuid).exists():
            found.append(uuid)
            continue
        if base is None and any((d / uuid).exists() for d in system_extensions_dirs()):
            found.append(uuid)
    return found


def installed_uuid(base: Path = None) -> str:
    """The uuid to name in messages: the installed one, else the local one."""
    found = installed_uuids(base)
    return found[0] if found else EXTENSION_UUID


def install_problems(base: Path = None) -> list:
    """What is wrong with the extension's on-disk install, as prose.

    Answers the question the bus cannot: "not active" covers never installed,
    installed but not enabled, and installed as a symlink into a directory the
    rename deleted -- and only the last of those looks, from the phone, exactly
    like the extension working badly rather than not being there.
    """
    directory = base or extensions_dir()
    problems = []

    for uuid in EXTENSION_UUIDS:
        target = directory / uuid
        if target.is_symlink() and not target.exists():
            problems.append(
                f"{uuid} is a symlink to {os_readlink(target)}, which no longer exists"
            )

    found = installed_uuids(base)
    if not found:
        problems.append(f"{EXTENSION_UUID} is not installed in {directory}")
    elif len(found) > 1:
        # Both copies export the same bus name, so the second one to load
        # silently loses it -- and the half-working result looks like a bug in
        # the extension rather than two of them.
        problems.append(
            "two copies are installed (" + " and ".join(found)
            + "); remove one, they claim the same D-Bus name"
        )

    for uuid in LEGACY_EXTENSION_UUIDS:
        legacy = directory / uuid
        if legacy.is_symlink() or legacy.exists():
            dangling = legacy.is_symlink() and not legacy.exists()
            problems.append(
                f"an old {uuid} install is still there"
                + (" and its target is gone" if dangling else "")
            )
    return problems


def os_readlink(path: Path) -> str:
    try:
        return str(path.readlink())
    except OSError:
        return "an unreadable path"


def is_available() -> bool:
    """Whether anything owns the extension's bus name right now."""
    if dbus is None:
        return False
    try:
        return bool(dbus.SessionBus().name_has_owner(SHELL_BUS_NAME))
    except Exception:
        return False


ENABLED_KEY = ["org.gnome.shell", "enabled-extensions"]


def enabled_uuids():
    """The dconf list of enabled extension uuids, or None if unreadable."""
    try:
        result = subprocess.run(
            ["gsettings", "get"] + ENABLED_KEY, capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None
        value = ast.literal_eval(result.stdout.strip())
        return value if isinstance(value, list) else None
    except Exception:
        return None


def is_enabled() -> bool:
    """Whether the uuid is in the enabled list.

    An unreadable setting counts as enabled: no gsettings is not evidence of a
    problem, and treating it as one would reinstall on every run forever.
    """
    enabled = enabled_uuids()
    return enabled is None or any(uuid in enabled for uuid in EXTENSION_UUIDS)


def load_state() -> str:
    """What the *running* GNOME Shell has done with the extension.

    The disk and dconf halves say what the next session will do; they say
    nothing about this one. A Shell only scans the extensions directory at
    session start, so a just-installed extension is enabled, on disk, correct
    -- and completely absent from the shell that is running, which is the state
    that reads as "installation failed" when only the bus is consulted.

    One of: "active" (loaded and running), "error" (loaded and threw),
    "inactive" (known to the shell, not running), "unscanned" (this session has
    never seen it -- log out and back in), or "unknown" (no way to ask).
    """
    if not shutil.which("gnome-extensions"):
        return "unknown"
    result = None
    for uuid in EXTENSION_UUIDS:
        try:
            result = subprocess.run(
                ["gnome-extensions", "info", uuid],
                capture_output=True, text=True, timeout=5,
            )
        except Exception:
            return "unknown"
        if result.returncode == 0:
            break
    if result is None or result.returncode != 0:
        # The shell answers "doesn't exist" both for never installed and for
        # installed-since-login; the caller has the disk half to tell them
        # apart.
        return "unscanned"
    match = re.search(r"^\s*State:\s*(.+)$", result.stdout, re.MULTILINE)
    if not match:
        return "unknown"
    state = match.group(1).strip().upper()
    if state.startswith("ACTIVE") or state.startswith("ENABLED"):
        return "active"
    if state.startswith("ERROR"):
        return "error"
    return "inactive"


def status(base: Path = None) -> tuple:
    """The extension's state as (code, message), covering disk, dconf and shell.

    Callers used to ask only `is_available()` and print "not loaded -- run
    vt install-extension", which is wrong advice for the most common case by
    far: the install worked, and GNOME Shell simply will not load it until the
    next login. Codes: "active", "pending-login", "error", "disabled",
    "broken", "no-shell".
    """
    if not shutil.which("gnome-extensions"):
        return "no-shell", "no GNOME Shell on this machine"
    if is_available():
        return "active", "loaded and answering on D-Bus"

    problems = install_problems(base)
    if problems:
        return "broken", problems[0]
    uuid = installed_uuid(base)
    if not is_enabled():
        return "disabled", f"{uuid} is installed but not enabled"

    state = load_state()
    if state == "error":
        return "error", f"{uuid} failed to load (gnome-extensions info {uuid})"
    return "pending-login", "installed and enabled; GNOME Shell loads it at your next login"
