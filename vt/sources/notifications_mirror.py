"""Mirror desktop notifications to the phone.

Notifications are method calls to org.freedesktop.Notifications, not signals,
so nothing can subscribe to them the ordinary way: a client only sees another
client's Notify() call by becoming a bus monitor. `dbus-monitor` is exactly
that, already installed on any system with D-Bus, and already holds the
privileged BecomeMonitor call -- so this reads its output instead of
reimplementing it, and a machine that refuses monitoring degrades to an empty
list with a reason rather than a traceback.

One thing can be acted on: dismissal. `CloseNotification` is a method on the
daemon, so any client may call it -- but it needs the notification's id, which
lives in the *reply* to Notify rather than in the call. So the monitor also
watches replies from the daemon and correlates them by serial.

Activating an action is the one that stays out of reach: an app listens for
`ActionInvoked` from the notification daemon's own bus name, and vt is not the
daemon. Offering a button that cannot work would be worse than not offering it.
"""

import re
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

NOTIFY_BUS = "org.freedesktop.Notifications"
NOTIFY_PATH = "/org/freedesktop/Notifications"

_SERIAL_RE = re.compile(r"\bserial=(\d+)\b")
_REPLY_SERIAL_RE = re.compile(r"\breply_serial=(\d+)\b")
_SENDER_RE = re.compile(r"\bsender=(\S+)")
_DESTINATION_RE = re.compile(r"\bdestination=(\S+)")
_UINT32_RE = re.compile(r"^\s*uint32\s+(\d+)\s*$")


def _int(match) -> int:
    return int(match.group(1)) if match else 0


def notification_daemon() -> str:
    """The unique bus name currently serving notifications, or "".

    GNOME Shell forwards each Notify on to other listeners, so the same
    notification appears on the bus more than once; the daemon's own name is
    what tells the original from its echoes.
    """
    try:
        import dbus

        bus = dbus.SessionBus()
        return str(bus.get_name_owner(NOTIFY_BUS))
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
             "--object-path", "/org/freedesktop/DBus",
             "--method", "org.freedesktop.DBus.GetNameOwner", NOTIFY_BUS],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0:
            match = re.search(r"'(:[\d.]+)'", result.stdout)
            if match:
                return match.group(1)
    except Exception:
        pass
    return ""


def dismiss(notification_id: int) -> dict:
    """Close a notification on the PC. Needs the id the daemon handed back."""
    try:
        import dbus
    except ImportError:
        return {"ok": False, "message": "python-dbus is not available"}
    try:
        bus = dbus.SessionBus()
        obj = bus.get_object(NOTIFY_BUS, NOTIFY_PATH, introspect=False)
        dbus.Interface(obj, NOTIFY_BUS).CloseNotification(dbus.UInt32(notification_id))
        return {"ok": True, "message": "Dismissed"}
    except Exception as e:
        return {"ok": False, "message": f"Could not dismiss it: {e}"}


# Notify(app_name, replaces_id, app_icon, summary, body, actions, hints, timeout).
# Of its four top-level strings, these are the ones worth a row on a phone.
_APP, _ICON, _SUMMARY, _BODY = 0, 1, 2, 3


class NotificationMirror:
    """A background reader of the session bus's notification traffic."""

    # Apps whose notifications are dropped on the way through. In memory and
    # per-session on purpose: this is "not tonight", not a settings screen, and
    # a mute that outlived the server would be one nobody could find later.
    def muted(self) -> list:
        with self._lock:
            return sorted(self._muted)

    def mute(self, app: str) -> bool:
        """Stop mirroring one app's notifications. True when it was not already."""
        app = (app or "").strip()
        if not app:
            return False
        with self._lock:
            if app in self._muted:
                return False
            self._muted.add(app)
            # What is already on the phone stays; what has not been read yet
            # goes, so muting a chatty app clears the backlog it just made.
            self._entries = deque(
                (e for e in self._entries if e["app"] != app), maxlen=MAX_ENTRIES
            )
            return True

    def unmute(self, app: str) -> bool:
        with self._lock:
            if app not in self._muted:
                return False
            self._muted.discard(app)
            return True

    def __init__(self, command=None, daemon: str = None):
        # Called from the reader thread with each new entry, by whoever wants
        # to push rather than poll. Left unset, this class behaves exactly as
        # it did when the phone asked every three seconds.
        self.on_entry = None
        self._daemon = daemon if daemon is not None else ""
        self._command = command or []
        self._entries: deque = deque(maxlen=MAX_ENTRIES)
        self._muted: set = set()
        self._pending: dict = {}
        self._seq = 0
        self._lock = threading.Lock()
        self._thread = None
        self._proc = None
        self._error = ""
        self._started = False

    # --- lifecycle ----------------------------------------------------------

    def available(self) -> bool:
        return shutil.which(self._command[0] if self._command else "dbus-monitor") is not None

    def _build_command(self) -> list:
        """dbus-monitor, watching Notify calls and the daemon's replies.

        The replies are what carry the notification id, and the id is what
        makes dismissal possible at all.
        """
        if self._command:
            return self._command
        if not self._daemon:
            self._daemon = notification_daemon()
        rules = [_MATCH]
        if self._daemon:
            rules.append(f"type='method_return',sender='{self._daemon}'")
        return ["dbus-monitor", "--session", *rules]

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
                self._build_command(),
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
        serial = 0
        awaiting = 0          # reply_serial we are reading an id for
        try:
            for line in proc.stdout:
                header = (line.startswith("method call") or line.startswith("signal ")
                          or line.startswith("method return") or line.startswith("error "))
                if header:
                    if collecting:
                        self._record(strings, serial)
                    strings = []
                    awaiting = 0
                    collecting = self._is_own_notify(line)
                    serial = _int(_SERIAL_RE.search(line)) if collecting else 0
                    if line.startswith("method return") and self._from_daemon(line):
                        awaiting = _int(_REPLY_SERIAL_RE.search(line))
                    continue
                if collecting and line.startswith(_TOP_LEVEL_STRING):
                    strings.append(line.strip()[len('string "'):-1])
                    continue
                if awaiting:
                    match = _UINT32_RE.match(line)
                    if match:
                        self._attach_id(awaiting, int(match.group(1)))
                        awaiting = 0
            if collecting:
                self._record(strings, serial)
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

    def _from_daemon(self, line: str) -> bool:
        if not self._daemon:
            return False
        match = _SENDER_RE.search(line)
        return bool(match and match.group(1) == self._daemon)

    def _is_own_notify(self, line: str) -> bool:
        """A Notify call addressed to the daemon, not one it forwarded on."""
        if "member=Notify" not in line or not line.startswith("method call"):
            return False
        if not self._daemon:
            return True
        match = _DESTINATION_RE.search(line)
        return bool(match and match.group(1) == self._daemon)

    def _attach_id(self, serial: int, notification_id: int):
        with self._lock:
            entry = self._pending.pop(serial, None)
            if entry is not None:
                entry["id"] = notification_id

    def _record(self, strings: list, serial: int = 0):
        """Turn one Notify call's top-level strings into an entry."""
        if len(strings) <= _SUMMARY:
            return
        summary = strings[_SUMMARY].strip()
        body = strings[_BODY].strip() if len(strings) > _BODY else ""
        if not summary and not body:
            return
        app = strings[_APP].strip() or "Desktop"
        with self._lock:
            if app in self._muted:
                # Dropped here rather than at the phone: a muted app should not
                # reach the socket, the poll, or the memory this holds.
                return
            self._seq += 1
            entry = {
                "seq": self._seq,
                "ts": time.time(),
                "app": app,
                "icon": strings[_ICON].strip(),
                "summary": summary,
                "body": body,
                # Filled in when the daemon's reply arrives; until then this
                # notification cannot be dismissed, and the phone says so by
                # showing no button rather than one that fails.
                "id": 0,
            }
            self._entries.append(entry)
            if serial:
                if len(self._pending) > MAX_ENTRIES:
                    self._pending.clear()
                self._pending[serial] = entry
        # Outside the lock: the listener hands this to another thread's event
        # loop, and holding the mirror's lock across that would let a slow
        # loop stall the reader that feeds it.
        listener = self.on_entry
        if listener is not None and entry is not None:
            try:
                listener(entry)
            except Exception:
                pass

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
