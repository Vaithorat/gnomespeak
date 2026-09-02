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

import re
from pathlib import Path

SHELL_BUS_NAME = "org.gnome.Shell.Extensions.VoiceTalk"
SHELL_OBJECT_PATH = "/org/gnome/Shell/Extensions/VoiceTalk"

EXTENSION_UUID = "gnomespeak@local"
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


def install_problems(base: Path = None) -> list:
    """What is wrong with the extension's on-disk install, as prose.

    Answers the question the bus cannot: "not active" covers never installed,
    installed but not enabled, and installed as a symlink into a directory the
    rename deleted -- and only the last of those looks, from the phone, exactly
    like the extension working badly rather than not being there.
    """
    directory = base or extensions_dir()
    problems = []

    target = directory / EXTENSION_UUID
    if target.is_symlink() and not target.exists():
        problems.append(
            f"{EXTENSION_UUID} is a symlink to {os_readlink(target)}, which no longer exists"
        )
    elif not target.exists():
        problems.append(f"{EXTENSION_UUID} is not installed in {directory}")

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
