"""Find the PC: a sound loud enough to hear from the sofa, and a banner.

The phone half of "find my device" needs a push channel to a page that may not
be open, which a browser cannot promise. This direction can be promised: the PC
is the machine running the server, and it is always listening.

Ringing runs on its own thread rather than inside the request. A sound you
cannot stop is worse than no sound at all -- and stopping it means the caller
that started it has to have returned already, so the phone can send a second
request while the first one is still making noise.
"""

import shutil
import subprocess
import threading
import time

SOUND_ID = "alarm-clock-elapsed"
SOUND_FILE = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"

# How long a ring keeps going if nobody stops it. Long enough to find a laptop
# under a cushion, short enough that a phone left in a pocket cannot leave the
# PC howling all afternoon.
MAX_SECONDS = 60.0

# Gap between repeats, so the alert reads as a ring rather than one long tone.
GAP_SECONDS = 0.4

# How long stop() waits for the player to die before giving up on it.
STOP_TIMEOUT = 2.0


def player_argv() -> list:
    if shutil.which("canberra-gtk-play"):
        return ["canberra-gtk-play", "-i", SOUND_ID]
    if shutil.which("pw-play"):
        return ["pw-play", SOUND_FILE]
    if shutil.which("paplay"):
        return ["paplay", SOUND_FILE]
    return []


class _Ringer:
    """The one ring in progress, if any."""

    def __init__(self):
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._proc = None

    @property
    def ringing(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def start(self, argv: list, seconds: float) -> bool:
        """Begin ringing. False when a ring is already in progress."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._loop, args=(argv, self._stop, seconds),
                name="vt-ring", daemon=True,
            )
            self._thread.start()
            return True

    def stop(self) -> bool:
        """Silence a ring in progress. False when nothing was ringing."""
        with self._lock:
            thread, stop, proc = self._thread, self._stop, self._proc
            if not (thread and thread.is_alive()):
                return False
        stop.set()
        # The player is a child process holding the speaker; asking the thread
        # to stop is not enough while the current repeat is still playing. The
        # process to kill can also be a moment away from existing -- stop can
        # arrive between two repeats -- so keep looking until the thread is
        # gone rather than terminating whichever process happened to be there.
        deadline = time.monotonic() + STOP_TIMEOUT
        while thread.is_alive() and time.monotonic() < deadline:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
            thread.join(timeout=0.05)
            with self._lock:
                proc = self._proc
        return True

    def _loop(self, argv: list, stop: threading.Event, seconds: float):
        deadline = time.monotonic() + seconds
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
            except Exception:
                return
            with self._lock:
                self._proc = proc
            if stop.is_set():
                proc.terminate()
            try:
                proc.wait(timeout=max(1.0, deadline - time.monotonic()))
            except Exception:
                proc.kill()
            with self._lock:
                self._proc = None
            if stop.wait(GAP_SECONDS):
                return


_ringer = _Ringer()


def ringing() -> bool:
    """True while the PC is making noise."""
    return _ringer.ringing


def _banner() -> bool:
    if not shutil.which("notify-send"):
        return False
    try:
        subprocess.run(
            ["notify-send", "-u", "critical", "GnomeSpeak",
             "Your phone is looking for this PC."],
            capture_output=True, timeout=5,
        )
        return True
    except Exception:
        return False


def ring(seconds: float = MAX_SECONDS) -> dict:
    """Play the alert and raise a notification. Returns the usual result dict."""
    argv = player_argv()
    notified = _banner()

    if not argv:
        if notified:
            return {"ok": True, "message": "No sound player found — showed a banner instead"}
        return {"ok": False, "message": "Nothing here can play a sound or show a banner"}

    if not _ringer.start(argv, seconds):
        return {"ok": True, "message": "Already ringing"}
    return {"ok": True, "message": "Ringing the PC"}


def stop() -> dict:
    """Silence the PC. Safe to call when it is not ringing."""
    if _ringer.stop():
        return {"ok": True, "message": "Stopped ringing"}
    return {"ok": True, "message": "It is not ringing"}
