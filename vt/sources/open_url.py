"""Open a link from the phone in the PC's browser.

The single most-used thing on a phone-to-desktop bridge: a link arrives on the
phone, and the screen you want it on is the big one. Everything needed was
already here -- the share sheet lands text in the page, and `xdg-open` is how
YouTube and the streaming shortcuts already reach the browser -- so this is the
"and open it" that sat between them.

Only http and https. A desktop's URL handlers reach much further than a browser
(`steam://`, `apt://`, `ms-word://`, and whatever else is registered), and a
link is the one thing here that arrives as free text from a phone that may be
handing on something it was sent. Refusing every other scheme keeps this a
"show me that page" button rather than an "invoke anything installed" one.
"""

import re
import subprocess
from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("http", "https")

# A bare host somebody typed or shared without a scheme: "example.com",
# "docs.python.org/3/library". Anything with whitespace or a control character
# is text, not a link, and is refused rather than guessed at.
_BARE_HOST = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9-]+)+(?::\d+)?(?:[/?#].*)?$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f\s]")


def normalise(text: str) -> str:
    """The URL to open, or "" when this is not one.

    Accepts a full http(s) URL, or a bare host that can only sensibly be one.
    """
    candidate = (text or "").strip()
    if not candidate or _CONTROL.search(candidate):
        return ""
    if "://" not in candidate:
        return f"https://{candidate}" if _BARE_HOST.match(candidate) else ""
    try:
        parsed = urlsplit(candidate)
    except Exception:
        return ""
    if parsed.scheme.lower() not in ALLOWED_SCHEMES or not parsed.netloc:
        return ""
    return candidate


def open_url(text: str) -> dict:
    """Open a link on the PC. Returns the usual result dict."""
    url = normalise(text)
    if not url:
        return {
            "ok": False,
            "message": "That is not an http or https link, so nothing was opened",
        }
    try:
        # Popen, not run: xdg-open hands off to a browser that may take seconds
        # to start, and the phone should not wait for it. start_new_session so
        # the browser outlives the server.
        subprocess.Popen(
            ["xdg-open", url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError:
        return {"ok": False, "message": "xdg-open not found (install xdg-utils)"}
    except Exception as e:
        return {"ok": False, "message": f"Could not open it: {e}"}
    host = urlsplit(url).netloc
    return {"ok": True, "message": f"Opened {host} on the PC", "url": url}
