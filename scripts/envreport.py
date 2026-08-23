"""Report which optional pieces the running interpreter can actually see.

`make env` runs this. It exists because the usual VoiceTalk confusion -- the
server behaving differently in a VS Code terminal than in a plain one -- is
always the same thing: two interpreters, one of which is missing yt-dlp or
python-dbus. Printing sys.executable next to the import results settles it.
"""

import importlib.util
import sys

CHECKS = (
    ("aiohttp", "required - web server"),
    ("psutil", "required - running apps"),
    ("dbus", "media players, window control"),
    ("gi", "GNOME Shell extension"),
    ("qrcode", "QR code on startup"),
    ("yt_dlp", "YouTube search"),
    ("pytest", "tests"),
)


def main():
    print("  interpreter   %s" % sys.executable)
    print("")
    for module, why in CHECKS:
        try:
            found = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            found = False
        print("  %s %-10s %s" % ("✓" if found else "✗", module, why))


if __name__ == "__main__":
    main()
