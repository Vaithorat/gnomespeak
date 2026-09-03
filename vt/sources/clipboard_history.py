"""The last few things copied on the PC.

"Send me that" is nearly always followed by "and the one before it". The
clipboard itself holds exactly one item, so the history is kept here: a small
ring in memory, filled by a thread that reads the clipboard on a slow poll and
by every write the phone makes.

Three deliberate limits, because a clipboard holds whatever was copied last and
that is sometimes a password:

  * memory only -- nothing is written to disk, so nothing survives the server,
  * short -- a couple of dozen entries, not a searchable archive,
  * started on request -- a session that never opens the clipboard screen never
    runs the poll at all.

The poll is a poll because neither Wayland nor X11 offers a usable "the
clipboard changed" signal to a client that does not own it. Two seconds is slow
enough to be invisible in a process list and fast enough that copying two
things in a row keeps both.
"""

import threading
import time

MAX_ENTRIES = 25
POLL_SECONDS = 2.0

# Anything longer is a document, not a clip worth offering on a phone. The
# entry keeps a preview and says how much was left out.
MAX_TEXT = 4096


class ClipboardHistory:
    """Recent clipboard contents, newest last."""

    def __init__(self, reader=None, poll_seconds: float = POLL_SECONDS):
        self._reader = reader
        self._poll = poll_seconds
        self._entries: list = []
        self._seq = 0
        self._lock = threading.Lock()
        self._thread = None
        self._stop = threading.Event()
        self._error = ""

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> bool:
        """Begin watching. Idempotent, and safe to call from a request."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._loop, args=(self._stop,), name="vt-clipboard", daemon=True
            )
            self._thread.start()
        return True

    def stop(self):
        with self._lock:
            thread, stop = self._thread, self._stop
            self._thread = None
        if stop:
            stop.set()
        if thread:
            thread.join(timeout=3)

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    @property
    def error(self) -> str:
        with self._lock:
            return self._error

    # --- collecting ---------------------------------------------------------

    def _read(self) -> dict:
        if self._reader is not None:
            return self._reader()
        from vt.sources.clipboard import read_text

        return read_text()

    def _loop(self, stop: threading.Event):
        while not stop.is_set():
            try:
                result = self._read()
            except Exception as e:
                with self._lock:
                    self._error = f"Clipboard watch stopped: {e}"
                return
            if result.get("ok"):
                self.record(result.get("text") or "")
                with self._lock:
                    self._error = ""
            else:
                with self._lock:
                    self._error = result.get("message") or ""
            if stop.wait(self._poll):
                return

    def record(self, text: str) -> bool:
        """Add one clip. Returns whether it was new."""
        text = text or ""
        if not text.strip():
            return False
        truncated = len(text) > MAX_TEXT
        stored = text[:MAX_TEXT]
        with self._lock:
            # Only consecutive repeats are dropped: copying A, then B, then A
            # again means A is the newest thing, and the phone should see it
            # where it actually is.
            if self._entries and self._entries[-1]["text"] == stored:
                return False
            self._seq += 1
            self._entries.append({
                "seq": self._seq,
                "ts": time.time(),
                "text": stored,
                "truncated": truncated,
                "length": len(text),
            })
            del self._entries[:-MAX_ENTRIES]
            return True

    def entries(self, limit: int = MAX_ENTRIES) -> list:
        """Recent clips, newest first."""
        with self._lock:
            return list(reversed(self._entries))[:limit]

    def clear(self) -> int:
        """Forget everything. The button someone looks for after copying a password."""
        with self._lock:
            count = len(self._entries)
            self._entries = []
            return count


_history = None
_history_lock = threading.Lock()


def history() -> ClipboardHistory:
    """The process-wide history, created on first use."""
    global _history
    with _history_lock:
        if _history is None:
            _history = ClipboardHistory()
    return _history
