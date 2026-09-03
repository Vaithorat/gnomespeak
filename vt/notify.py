"""Put a banner on the PC's screen.

One place, because more than one feature wants it and each of them wanting its
own subprocess call is how two of them end up disagreeing about urgency. A
banner and nothing else: anything that also makes a noise belongs with the
things that are meant to be heard, not with the things that are meant to be
seen when someone next looks.
"""

import shutil
import subprocess


def notify(summary: str, body: str = "", urgency: str = "normal") -> dict:
    """Raise a desktop notification. Returns the usual result dict."""
    if not shutil.which("notify-send"):
        return {"ok": False, "message": "notify-send is not installed"}
    argv = ["notify-send", "-u", urgency, "-a", "GnomeSpeak", summary]
    if body:
        argv.append(body)
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5)
    except Exception as e:
        return {"ok": False, "message": f"Could not show it: {e}"}
    if result.returncode != 0:
        return {"ok": False, "message": (result.stderr or "notify-send failed").strip()}
    return {"ok": True, "message": "Shown on the PC"}
