"""Application detection: what is running, and what is installed.

Both views come from the same scan of `.desktop` entries. Running apps are
processes matched back to an entry (psutil); installed apps are the entries
themselves, so an app can be launched when nothing of it is running yet.
"""

import re
import shlex
import time
from pathlib import Path
from vt.model import Target, Action
from vt.sources.steam import get_steam_targets

try:
    import psutil
except ImportError:
    psutil = None

_DESKTOP_DIRS = (
    Path("/usr/share/applications"),
    Path("/var/lib/flatpak/exports/share/applications"),
    Path("/var/lib/snapd/desktop/applications"),
    Path.home() / ".local/share/applications",
)

# Background services that ship a .desktop file but are not user-facing apps.
_SKIP_EXEC = {
    "ibus-daemon", "ibus-setup", "gnome-keyring-daemon", "pulseaudio",
    "pipewire", "wireplumber", "snapd", "dockerd", "docker-desktop",
    "gsd-printer", "xdg-desktop-portal", "tracker-miner-fs", "evolution-alarm-notify",
}

# Launcher prefixes that stand in front of the real command in an Exec line.
_EXEC_WRAPPERS = {"env", "flatpak", "run", "sh", "-c"}

# The index used to be built once per process, which meant a server left running
# never saw an app installed after startup. A minute of staleness is invisible
# to the user and still keeps the scan off the 1 Hz snapshot path.
_INDEX_TTL = 60.0


def _parse_exec(exec_line: str) -> tuple[list[str], str] | None:
    """Split an Exec line into (argv to run, executable basename).

    The two answer different questions. The argv is the command as the desktop
    entry meant it, wrappers included -- "flatpak run com.spotify.Client" only
    works whole. The binary is the name a *process* will carry, which is what
    running-app matching compares against, so the wrappers come off there.
    """
    # Field codes (%f %U ...) are placeholders for files we are not passing.
    exec_line = re.sub(r"%[a-zA-Z]", "", exec_line).strip()
    try:
        argv = shlex.split(exec_line)
    except ValueError:
        argv = exec_line.split()
    if not argv:
        return None

    parts = list(argv)
    # Compare the basename: a desktop file is as likely to say /usr/bin/flatpak
    # as flatpak, and matching only the bare word indexed every flatpak app
    # under "flatpak", where the first one scanned shadowed the rest.
    while parts and ("=" in parts[0] or Path(parts[0]).name in _EXEC_WRAPPERS):
        parts.pop(0)
    if not parts:
        return None

    binary = Path(parts[0]).name.lower()
    if not binary or binary in _SKIP_EXEC:
        return None
    return argv, binary


def _parse_desktop(path: Path) -> dict | None:
    """Extract the fields we need from the [Desktop Entry] section of a .desktop file."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    # Only the main section; trailing [Desktop Action ...] blocks have their own Exec.
    section = re.split(r"^\[(?!Desktop Entry\]).*\]", text, flags=re.MULTILINE)[0]

    def field(key: str) -> str:
        m = re.search(rf"^{key}\s*=\s*(.+?)\s*$", section, re.MULTILINE)
        return m.group(1) if m else ""

    if field("Type") not in ("Application", ""):
        return None
    if field("NoDisplay").lower() == "true" or field("Hidden").lower() == "true":
        return None

    name, exec_line = field("Name"), field("Exec")
    if not name or not exec_line:
        return None

    parsed = _parse_exec(exec_line)
    if parsed is None:
        return None
    argv, binary = parsed

    return {
        "id": path.stem,
        "path": str(path),
        "name": name,
        "icon": field("Icon"),
        "binary": binary,
        "argv": argv,
        # GenericName ("Web Browser") and Comment are what make a search for
        # "browser" find Firefox, so they are worth carrying.
        "subtitle": field("GenericName") or field("Comment"),
        "terminal": field("Terminal").lower() == "true",
    }


_binary_index: dict[str, dict] | None = None
_id_index: dict[str, dict] | None = None
_index_built_at = 0.0


def _build_index() -> None:
    """Scan every applications directory once, producing both indexes."""
    global _binary_index, _id_index, _index_built_at

    binaries: dict[str, dict] = {}
    ids: dict[str, dict] = {}
    for directory in _DESKTOP_DIRS:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.desktop")):
            entry = _parse_desktop(path)
            if not entry:
                continue
            binaries.setdefault(entry["binary"], entry)
            # Desktop ids are unique per directory but shadow across them, and
            # ~/.local/share wins over /usr/share. _DESKTOP_DIRS is in
            # increasing priority order, so a later assignment is the override.
            ids[entry["id"]] = entry

    _binary_index, _id_index, _index_built_at = binaries, ids, time.monotonic()


def _ensure_index() -> None:
    if _binary_index is None or (time.monotonic() - _index_built_at) > _INDEX_TTL:
        _build_index()


def reset_index_cache() -> None:
    """Drop the cached scan. For tests, and for anything that moves _DESKTOP_DIRS."""
    global _binary_index, _id_index, _index_built_at
    _binary_index = None
    _id_index = None
    _index_built_at = 0.0


def _get_desktop_index() -> dict[str, dict]:
    """Map executable basename -> desktop entry."""
    _ensure_index()
    return _binary_index or {}


def get_installed_index() -> dict[str, dict]:
    """Map desktop id ("firefox", "org.gnome.Nautilus") -> desktop entry."""
    _ensure_index()
    return _id_index or {}


def get_app_targets() -> list[Target]:
    """Return running GUI applications as Targets.

    A process is included only when its executable basename matches the Exec
    basename of a visible .desktop entry. Matching on the *binary* rather than
    the display name is what keeps ibus-daemon/ibus-dconf/ibus-portal from all
    collapsing onto "IBus Preferences".
    """
    if not psutil:
        return []

    index = _get_desktop_index()
    found: dict[str, Target] = {}

    for proc in psutil.process_iter(["name", "exe"]):
        try:
            candidates = set()
            if proc.info.get("name"):
                candidates.add(proc.info["name"].lower())
            if proc.info.get("exe"):
                candidates.add(Path(proc.info["exe"]).name.lower())

            for binary in candidates:
                entry = index.get(binary)
                if not entry:
                    continue
                # Dedupe on the resolved app, so one app with many helper
                # processes yields exactly one row.
                if entry["name"] in found:
                    break
                found[entry["name"]] = Target(
                    id=f"app:{binary}",
                    kind="app",
                    title=entry["name"],
                    icon="#",
                    status="running",
                    actions=[
                        Action(id="focus", label="Focus"),
                        Action(id="quit", label="Quit", kind="confirm"),
                    ],
                )
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue

    return sorted(found.values(), key=lambda t: t.title.lower())


def _tokens(query: str) -> list[str]:
    return [tok for tok in query.casefold().split() if tok]


def matches_query(entry: dict, tokens: list[str]) -> bool:
    """Every token must appear somewhere in the entry's searchable text.

    Token-wise rather than substring-wise, so "fire br" finds Firefox by name
    and generic name at once, and word order does not matter.
    """
    haystack = " ".join(
        (entry.get("name", ""), entry.get("subtitle", ""),
         entry.get("id", ""), entry.get("binary", ""))
    ).casefold()
    return all(tok in haystack for tok in tokens)


def get_installed_targets(query: str = "") -> list[Target]:
    """Return installed applications as launchable Targets.

    These are deliberately *not* part of the 1 Hz snapshot: there are hundreds
    of them, they change about once a week, and pushing them to every polling
    phone every second would dwarf the state that actually moves. The server
    serves them from /api/apps instead.
    """
    tokens = _tokens(query)
    targets: list[Target] = []

    # Steam writes .desktop files only for games the user asked for a shortcut
    # to, so the library has to be read from Steam's own manifests. They belong
    # in this list rather than a screen of their own: from the phone, starting
    # a game and starting an application are the same gesture.
    targets.extend(get_steam_targets(query))

    for entry in get_installed_index().values():
        # Terminal=true entries are CLI tools that need a terminal emulator to
        # be of any use; launching one headless from a phone does nothing
        # visible, so they stay out of the list.
        if entry["terminal"]:
            continue
        if tokens and not matches_query(entry, tokens):
            continue
        targets.append(
            Target(
                id=f"launcher:{entry['id']}",
                kind="launcher",
                title=entry["name"],
                subtitle=entry["subtitle"],
                icon="▸",
                status="installed",
                actions=[Action(id="launch", label="Launch")],
            )
        )

    lead = tokens[0] if tokens else ""

    def rank(t: Target) -> tuple:
        # A name that starts with what was typed is almost always the one meant.
        return (0 if lead and t.title.casefold().startswith(lead) else 1, t.title.casefold())

    targets.sort(key=rank)
    return targets
