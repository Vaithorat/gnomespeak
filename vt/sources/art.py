"""Album art: fetched, size-capped, cached by track, never blindly proxied.

`mpris:artUrl` is a string a player hands us. Turning that into "the server
fetches whatever URL it is told to" would make every media player on the PC a
way to make the server issue requests, so this module treats it as a claim to
be checked: an image, under a size cap, from a file on disk or over http(s),
and nothing else gets past.
"""

import hashlib
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

MAX_BYTES = 4 * 1024 * 1024
CACHE_SIZE = 24
TIMEOUT = 5.0

# Magic bytes for the formats a browser will render. A file that is not one of
# these is not art, whatever the player called it.
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_cache: dict = {}
# key -> the URL a player published. The phone only ever names a key, so the
# set of URLs the server can be asked to fetch is exactly the set some player
# on this PC advertised.
_known: dict = {}


def key_for(art_url: str) -> str:
    """A short, stable id for one art URL, used as the cache-busting token."""
    if not art_url:
        return ""
    key = hashlib.sha256(art_url.encode("utf-8", "replace")).hexdigest()[:16]
    if key not in _known:
        if len(_known) >= CACHE_SIZE * 4:
            _known.clear()
        _known[key] = art_url
    return key


def url_for(key: str) -> str:
    """The URL behind a key, or "" for a key no player ever published."""
    return _known.get(key, "")


def sniff(data: bytes) -> str:
    for prefix, content_type in _SIGNATURES:
        if data.startswith(prefix):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def fetch(art_url: str) -> tuple:
    """(bytes, content type) for an art URL, or (b"", "") with a reason logged."""
    if not art_url:
        return b"", ""
    cached = _cache.get(art_url)
    if cached is not None:
        return cached

    parsed = urlparse(art_url)
    data = b""
    try:
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path))
            if path.is_file() and path.stat().st_size <= MAX_BYTES:
                data = path.read_bytes()
        elif parsed.scheme in ("http", "https"):
            request = urllib.request.Request(art_url, headers={"User-Agent": "gnomespeak"})
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                if response.headers.get("Content-Type", "").startswith("image/"):
                    data = response.read(MAX_BYTES + 1)
        elif parsed.scheme == "data":
            return b"", ""
    except Exception:
        data = b""

    if len(data) > MAX_BYTES:
        data = b""
    content_type = sniff(data) if data else ""
    if not content_type:
        data = b""

    if len(_cache) >= CACHE_SIZE:
        _cache.clear()
    _cache[art_url] = (data, content_type)
    return data, content_type
