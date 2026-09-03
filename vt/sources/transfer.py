"""File transfer between the phone and the PC.

Everything lands in one directory -- ~/Downloads/GnomeSpeak by default -- and
nothing outside it is ever served. That single rule is what makes the feature
safe to expose to a paired phone: a name that tries to escape the directory is
rejected before it is a path, and a download request is resolved against the
directory's real path afterwards, so a symlink planted inside it cannot lead
out either.

The phone is not a filesystem browser. It sends a file, or it takes back one
that was sent -- which is the whole of what "share this to my PC" means in
practice, and it needs no notion of directories at all.
"""

import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

# Big enough for a photo or a PDF, small enough that a mistyped upload cannot
# fill the disk while the user watches a spinner.
MAX_BYTES = 100 * 1024 * 1024

# Anything that is not plainly part of a file name. Keeping a whitelist rather
# than stripping "../" is what makes traversal impossible to express, instead
# of merely hard to spell.
_UNSAFE = re.compile(r"[^A-Za-z0-9._ ()\-]+")
_MAX_NAME = 120


def _xdg_download_dir() -> Path:
    """The user's real Downloads directory, whatever it is called locally."""
    try:
        result = subprocess.run(
            ["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=2
        )
        path = result.stdout.strip()
        if result.returncode == 0 and path:
            return Path(path)
    except Exception:
        pass
    return Path.home() / "Downloads"


def transfer_dir() -> Path:
    """Where transferred files live, created on demand."""
    override = os.environ.get("GNOMESPEAK_TRANSFER_DIR")
    base = Path(override) if override else _xdg_download_dir() / "GnomeSpeak"
    base.mkdir(parents=True, exist_ok=True)
    return base


def safe_name(name: str) -> str:
    """A file name reduced to something that cannot mean anything but a name."""
    # Take the last path component first: a browser on Android sends bare names,
    # but nothing stops a client from sending "../../.bashrc".
    base = str(name or "").replace("\\", "/").split("/")[-1].strip()
    base = _UNSAFE.sub("_", base).strip(". ")
    if not base:
        base = "upload"
    if len(base) > _MAX_NAME:
        stem, dot, suffix = base.rpartition(".")
        if dot and len(suffix) <= 10:
            base = stem[: _MAX_NAME - len(suffix) - 1] + "." + suffix
        else:
            base = base[:_MAX_NAME]
    return base


def unique_path(name: str) -> Path:
    """A path in the transfer directory that does not exist yet."""
    directory = transfer_dir()
    base = safe_name(name)
    candidate = directory / base
    if not candidate.exists():
        return candidate
    stem, dot, suffix = base.rpartition(".")
    if not dot:
        stem, suffix = base, ""
    for n in range(1, 1000):
        alt = f"{stem}-{n}{('.' + suffix) if suffix else ''}"
        candidate = directory / alt
        if not candidate.exists():
            return candidate
    return directory / f"{stem}-{int(time.time())}{('.' + suffix) if suffix else ''}"


def resolve(name: str):
    """The path a download request names, or None when it is not ours.

    Resolved rather than joined: the name is already sanitized, but the
    directory's own contents are not, and a symlink inside it pointing at
    ~/.ssh would otherwise be served as though it were a received file.
    """
    directory = transfer_dir().resolve()
    try:
        path = (directory / safe_name(name)).resolve()
    except OSError:
        return None
    if not path.is_file():
        return None
    try:
        path.relative_to(directory)
    except ValueError:
        return None
    return path


def list_files(limit: int = 50) -> list:
    """Files in the transfer directory, newest first."""
    directory = transfer_dir()
    entries = []
    try:
        for path in directory.iterdir():
            if not path.is_file() or path.is_symlink():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append({
                "name": path.name,
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            })
    except OSError:
        return []
    entries.sort(key=lambda e: e["mtime"], reverse=True)
    return entries[:limit]


def human_size(size: int) -> str:
    """A size a phone screen has room for."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" or value >= 10 else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


_OFFICE_SUFFIXES = {
    ".xlsx", ".xls", ".xlsm", ".xltx", ".xlt",
    ".ods", ".ots", ".csv", ".tsv",
    ".docx", ".doc", ".docm", ".dotx", ".dot",
    ".odt", ".ott", ".rtf",
    ".pptx", ".ppt", ".pptm", ".potx", ".pot",
    ".odp", ".otp",
    ".odg", ".odf",
}


def _focus_target(win_id):
    if not win_id:
        return
    if isinstance(win_id, str) and win_id.startswith("cosmic:"):
        try:
            from vt.sources.cosmic_windows import focus_window as cosmic_focus
            cosmic_focus(win_id)
        except Exception:
            pass
    else:
        try:
            import dbus
            from vt.sources.windows import shell_interface
            shell_interface().Focus(dbus.UInt32(win_id))
        except Exception:
            pass


def _raise_opened_window(initial_ids: set, file_name: str, timeout: float = 3.5):
    """Wait for the opened window to appear and bring it to the foreground.

    Under Wayland/GNOME, an app launched in the background without an activation
    token opens unfocused or behind active windows, which can feel like a glitch
    where the window flickered and vanished. Activating it as soon as it appears
    raises it cleanly above the active workspace.
    """
    from vt.sources.windows import list_windows
    stem = Path(file_name).stem.lower()
    name_lower = file_name.lower()
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        time.sleep(0.1)
        try:
            cur = list_windows()
            # 1. First preference: window matching the file title or stem
            for w in cur:
                title = str(w.get("title") or "").lower()
                if name_lower in title or (len(stem) >= 3 and stem in title):
                    _focus_target(w.get("id"))
                    return

            # 2. Second preference: any newly mapped window ID
            new_wins = [w for w in cur if w.get("id") not in initial_ids]
            if new_wins:
                _focus_target(new_wins[0].get("id"))
                return
        except Exception:
            pass


def open_in_desktop(path: Path) -> dict:
    """Hand a received file to whatever the desktop opens it with.

    For office documents, --nologo is passed to LibreOffice when available:
    LibreOffice otherwise pops up an XWayland/Wayland splash screen that unmaps
    a second later before the document opens, reading visually as a window
    rapidly opening and closing.

    The newly opened window is brought to the foreground via the GNOME
    extension (or COSMIC) so it doesn't open buried or unfocused behind
    maximized windows under Wayland.
    """
    initial_ids = set()
    try:
        from vt.sources.windows import list_windows
        initial_ids = {w.get("id") for w in list_windows()}
    except Exception:
        pass

    suffix = path.suffix.lower()
    if suffix in _OFFICE_SUFFIXES and shutil.which("libreoffice"):
        cmd = ["libreoffice", "--nologo", str(path)]
    elif shutil.which("gio"):
        cmd = ["gio", "open", str(path)]
    elif shutil.which("xdg-open"):
        cmd = ["xdg-open", str(path)]
    else:
        return {"ok": False, "message": "Neither gio nor xdg-open found"}

    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        threading.Thread(
            target=_raise_opened_window,
            args=(initial_ids, path.name),
            name="vt-open-raise",
            daemon=True,
        ).start()
        return {"ok": True, "message": f"Opened {path.name}"}
    except FileNotFoundError:
        return {"ok": False, "message": f"{cmd[0]} not found"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}
