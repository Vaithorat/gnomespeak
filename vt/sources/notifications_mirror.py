"""Mirror desktop notifications to the phone.

Notifications are method calls to org.freedesktop.Notifications, not signals,
so nothing can subscribe to them the ordinary way: a client only sees another
client's Notify() call by becoming a bus monitor. `dbus-monitor` is exactly
that, already installed on any system with D-Bus, and already holds the
privileged BecomeMonitor call -- so this reads its output instead of
reimplementing it, and a machine that refuses monitoring degrades to an empty
list with a reason rather than a traceback.

The mirror is read-only and deliberately so. Acting on a notification means
activating an action on the sender's own bus name, which is a second feature
with a second failure mode; showing what arrived covers what people actually
want from a phone across the room.
"""

import shutil
import subprocess
import threading
import time
from collections import deque

# The phone shows a short list and asks for what it has not seen, so a long
# backlog buys nothing -- and holding one means holding whatever text was in
# every notification since the server started.
MAX_ENTRIES = 60

# Top-level arguments in dbus-monitor's output carry exactly three spaces of
# indent; hint dictionaries and action arrays nest deeper. That distinction is
# what keeps a hint's string value from being read as the notification body.
_TOP_LEVEL_STRING = '   string "'

_MATCH = "interface='org.freedesktop.Notifications',member='Notify'"

# Notify(app_name, replaces_id, app_icon, summary, body, actions, hints, timeout).
# Of its four top-level strings, these are the ones worth a row on a phone.
_APP, _ICON, _SUMMARY, _BODY = 0, 1, 2, 3


class NotificationMirror:
    """A background reader of the session bus's notification traffic."""

    def __init__(self, command=None):
        self._command = command or [
            "dbus-monitor", "--session", _MATCH,
        ]
        self._entries: deque = deque(maxlen=MAX_ENTRIES)
        self._seq = 0
        self._lock = threading.Lock()
        self._thread = None
        self._proc = None
        self._error = ""
        self._started = False

    # --- lifecycle ----------------------------------------------------------

    def available(self) -> bool:
        return shutil.which(self._command[0]) is not None

    def start(self) -> bool:
        """Begin mirroring. Idempotent, and safe to call from a request."""
        with self._lock:
            if self._started:
                return not self._error
            self._started = True
            if not self.available():
                self._error = (
                    "Notification mirroring needs dbus-monitor. Install it with "
                    "`sudo apt install dbus-bin` (or `sudo dnf install dbus-tools`)."
                )
                return False
        try:
            self._proc = subprocess.Popen(
                self._command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except Exception as e:
            with self._lock:
                self._error = f"Could not start dbus-monitor: {e}"
            return False

        self._thread = threading.Thread(
            target=self._read_loop, name="vt-notifications", daemon=True
        )
        self._thread.start()
        return True

    def stop(self):
        """Stop mirroring and let the reader thread fall out of its loop."""
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        with self._lock:
            self._started = False

    # --- reading ------------------------------------------------------------

    def _read_loop(self):
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        strings: list = []
        collecting = False
        try:
            for line in proc.stdout:
                if line.startswith("method call") or line.startswith("signal "):
                    # A new message ends the previous one: Notify's arguments
                    # are however many lines follow it, with no terminator.
                    if collecting:
                        self._record(strings)
                    collecting = "member=Notify" in line
                    strings = []
                    continue
                if collecting and line.startswith(_TOP_LEVEL_STRING):
                    strings.append(line.strip()[len('string "'):-1])
            if collecting:
                self._record(strings)
        except Exception as e:
            with self._lock:
                self._error = f"Notification mirror stopped: {e}"
            return

        # Falling out of the loop means dbus-monitor exited. Its stderr says
        # why -- most often that the bus refused BecomeMonitor.
        stderr = ""
        try:
            if proc.stderr:
                stderr = proc.stderr.read().strip()
        except Exception:
            pass
        with self._lock:
            if not self._error:
                self._error = stderr.splitlines()[-1] if stderr else "dbus-monitor exited"

    def _record(self, strings: list):
        """Turn one Notify call's top-level strings into an entry."""
        if len(strings) <= _SUMMARY:
            return
        summary = strings[_SUMMARY].strip()
        body = strings[_BODY].strip() if len(strings) > _BODY else ""
        if not summary and not body:
            return
        with self._lock:
            self._seq += 1
            self._entries.append({
                "seq": self._seq,
                "ts": time.time(),
                "app": strings[_APP].strip() or "Desktop",
                "icon": strings[_ICON].strip(),
                "summary": summary,
                "body": body,
            })

    # --- reading out --------------------------------------------------------

    def entries(self, since: int = 0, limit: int = MAX_ENTRIES) -> list:
        """Notifications newer than `since`, oldest first."""
        with self._lock:
            items = [e for e in self._entries if e["seq"] > since]
        return items[-limit:]

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    @property
    def running(self) -> bool:
        return bool(self._proc and self._proc.poll() is None)


_mirror = None
_mirror_lock = threading.Lock()


def mirror() -> NotificationMirror:
    """The process-wide mirror, started on first use.

    Started lazily rather than at import: `vt status` and `vt do` have no use
    for a background subprocess that outlives their own second of runtime.
    """
    global _mirror
    with _mirror_lock:
        if _mirror is None:
            _mirror = NotificationMirror()
    return _mirror
