"""Clipboard sync between the phone and the PC.

There is no D-Bus clipboard: on Wayland the clipboard belongs to the compositor
and is reachable through wl-clipboard, on X11 through xclip or xsel. All three
are small CLI tools, and which of them exists says which session this is, so
tool discovery doubles as session detection.

Reading is a poll, not a subscription. Neither wl-paste --watch nor an X11
selection owner change is worth a background thread here: the phone asks for
the clipboard when the user opens the clipboard screen, which is the only
moment the answer matters.
"""

import os
import shutil
import subprocess
import tempfile

# A clipboard can hold a whole document. The phone only ever shows a preview of
# it and the point of the feature is a URL or a paragraph, so refuse the
# pathological case rather than stream megabytes to a phone at 1 Hz.
MAX_BYTES = 256 * 1024

_TIMEOUT = 3


def _wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")) or \
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def backend() -> dict:
    """The clipboard tool to use, as {"name", "read", "write"}, or {}.

    Wayland tools are tried first on a Wayland session and last otherwise:
    xclip exists on many Wayland systems through XWayland but talks to the X11
    clipboard, which is a different clipboard than the one the user's native
    apps are copying into.
    """
    wl = {
        "name": "wl-clipboard",
        "read": ["wl-paste", "--no-newline"],
        "write": ["wl-copy"],
        "probe": "wl-copy",
    }
    x11 = [
        {
            "name": "xclip",
            "read": ["xclip", "-selection", "clipboard", "-o"],
            "write": ["xclip", "-selection", "clipboard", "-i"],
            "probe": "xclip",
        },
        {
            "name": "xsel",
            "read": ["xsel", "--clipboard", "--output"],
            "write": ["xsel", "--clipboard", "--input"],
            "probe": "xsel",
        },
    ]
    order = [wl] + x11 if _wayland() else x11 + [wl]
    for candidate in order:
        if shutil.which(candidate["probe"]):
            return candidate
    return {}


def unavailable_message() -> str:
    """What to install, named for the session actually running."""
    if _wayland():
        return (
            "Clipboard sync needs wl-clipboard on Wayland. Install it with "
            "`sudo apt install wl-clipboard` (or `sudo dnf install wl-clipboard`)."
        )
    return (
        "Clipboard sync needs xclip or xsel on X11. Install one with "
        "`sudo apt install xclip` (or `sudo dnf install xclip`)."
    )


def is_available() -> bool:
    return bool(backend())


def read_text() -> dict:
    """The PC clipboard's text content.

    An empty clipboard is a success with empty text, not an error: wl-paste
    exits non-zero when nothing is copied, and reporting that as a failure sent
    the first person to see it looking for a broken install.
    """
    tool = backend()
    if not tool:
        return {"ok": False, "text": "", "message": unavailable_message()}
    try:
        result = subprocess.run(
            tool["read"], capture_output=True, timeout=_TIMEOUT
        )
    except FileNotFoundError:
        return {"ok": False, "text": "", "message": unavailable_message()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": "", "message": f"{tool['name']} timed out"}
    except Exception as e:
        return {"ok": False, "text": "", "message": f"Error: {e}"}

    if result.returncode != 0:
        stderr = result.stderr.decode(errors="ignore").strip().lower()
        if "nothing is copied" in stderr or not stderr:
            return {"ok": True, "text": "", "message": "", "tool": tool["name"]}
        # An image or a file list is a clipboard vt cannot show as text, and
        # saying so beats an empty box that looks like a bug.
        if "no suitable type" in stderr or "not available" in stderr:
            return {
                "ok": True, "text": "", "tool": tool["name"],
                "message": "The clipboard holds something that is not text.",
            }
        return {"ok": False, "text": "", "message": stderr.splitlines()[-1]}

    raw = result.stdout[:MAX_BYTES]
    text = raw.decode("utf-8", errors="replace")
    return {
        "ok": True,
        "text": text,
        "message": "",
        "tool": tool["name"],
        "truncated": len(result.stdout) > MAX_BYTES,
    }


def write_text(text: str) -> dict:
    """Put text on the PC clipboard."""
    tool = backend()
    if not tool:
        return {"ok": False, "message": unavailable_message()}
    payload = str(text or "").encode("utf-8")[:MAX_BYTES]
    if not payload:
        return {"ok": False, "message": "Nothing to copy"}
    # A clipboard owner has to outlive the command that set it: wl-copy and
    # xclip both fork a process that serves the selection until someone else
    # copies something. That child inherits whatever it was given for stderr,
    # so a *pipe* there is never closed and subprocess.run waits out its whole
    # timeout on a copy that already succeeded. A real file has no such reader,
    # so the parent's exit is the only thing waited on -- and the error text is
    # still there to read afterwards.
    try:
        with tempfile.TemporaryFile() as errfile:
            result = subprocess.run(
                tool["write"],
                input=payload,
                stdout=subprocess.DEVNULL,
                stderr=errfile,
                timeout=_TIMEOUT,
            )
            errfile.seek(0)
            stderr = errfile.read().decode(errors="ignore").strip()
    except FileNotFoundError:
        return {"ok": False, "message": unavailable_message()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": f"{tool['name']} timed out"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}

    if result.returncode != 0:
        detail = stderr.splitlines()[-1] if stderr else f"exit {result.returncode}"
        return {"ok": False, "message": f"{tool['name']}: {detail}"}

    count = len(payload.decode("utf-8", errors="ignore"))
    return {"ok": True, "message": f"Copied {count} character{'s' if count != 1 else ''} to the PC"}
