"""Firefox tab enumeration via the session store.

The window manager sees one window per Firefox window; tabs live entirely
inside the browser and no Mutter/GNOME API can enumerate them. Firefox does
write its complete tab state to sessionstore-backups/recovery.jsonlz4, which
is the only full tab list available without installing a browser extension.

Two consequences worth knowing:

  * The file is rewritten every `browser.sessionstore.interval` ms (15000 by
    default), so the list can lag reality by that much. Lower it in about:config
    for a snappier remote at the cost of more disk writes.
  * It is a snapshot of state, not a control channel. Switching tabs is done by
    synthesizing Alt+N through the GNOME extension -- see vt/actions.py.

The file is mozlz4: an 8-byte magic, a little-endian u32 decompressed size,
then a raw LZ4 block. The block decoder below is ~30 lines, which is cheaper
than making python-lz4 a dependency for one file.
"""

import json
import struct
from pathlib import Path

MAGIC = b"mozLz40\x00"

# Where Firefox keeps profiles, in the order we prefer them. The snap path
# comes first because Ubuntu ships Firefox as a snap by default.
PROFILE_ROOTS = [
    Path.home() / "snap/firefox/common/.mozilla/firefox",
    Path.home() / ".mozilla/firefox",
    Path.home() / ".var/app/org.mozilla.firefox/.mozilla/firefox",
]

# recovery.jsonlz4 is rewritten whole every 15s; re-decompressing 3MB on every
# one-second poll is pure waste, so key a cache on (path, mtime, size).
_cache: dict = {"key": None, "value": []}


def _continue_length(src: bytes, i: int, length: int) -> tuple[int, int]:
    """Finish a length field that saturated its 4-bit slot.

    LZ4 encodes 0..14 inline and signals 15 as "keep reading bytes and add them
    until one is not 255". Returns the total and the new read position.
    """
    while True:
        b = src[i]
        i += 1
        length += b
        if b != 255:
            return length, i


def _lz4_block_decompress(src: bytes) -> bytes:
    """Decode a raw LZ4 block. No frame header, no checksums -- that is what
    mozlz4 stores after its own 12-byte header."""
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1

        lit = token >> 4
        if lit == 15:
            lit, i = _continue_length(src, i, lit)
        dst += src[i:i + lit]
        i += lit

        # A block ends on a literal run with no match to follow.
        if i >= n:
            break

        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset == 0:
            raise ValueError("invalid LZ4 stream: zero offset")

        match = (token & 0x0F) + 4
        if (token & 0x0F) == 15:
            match, i = _continue_length(src, i, match)

        start = len(dst) - offset
        if start < 0:
            raise ValueError("invalid LZ4 stream: offset before start")
        if offset >= match:
            # Non-overlapping: copy the whole run at once.
            dst += dst[start:start + match]
        else:
            # Overlapping run (RLE-style); it must be built byte by byte.
            for j in range(match):
                dst.append(dst[start + j])
    return bytes(dst)


def _read_mozlz4(path: Path) -> dict:
    """Decompress and parse a mozlz4-wrapped JSON file."""
    raw = path.read_bytes()
    if raw[:8] != MAGIC:
        raise ValueError(f"not a mozlz4 file: {path}")
    size = struct.unpack("<I", raw[8:12])[0]
    data = _lz4_block_decompress(raw[12:])
    if len(data) != size:
        raise ValueError(f"size mismatch: got {len(data)}, header said {size}")
    return json.loads(data)


def _session_file() -> Path | None:
    """The freshest session store across every profile we can find.

    Users routinely have several profiles and a stale default; picking by mtime
    gets the one actually in use without parsing profiles.ini.
    """
    best, best_mtime = None, -1.0
    for root in PROFILE_ROOTS:
        if not root.is_dir():
            continue
        for name in ("recovery.jsonlz4", "previous.jsonlz4"):
            for candidate in root.glob(f"*/sessionstore-backups/{name}"):
                try:
                    mtime = candidate.stat().st_mtime
                except OSError:
                    continue
                if mtime > best_mtime:
                    best, best_mtime = candidate, mtime
    return best


def get_firefox_windows() -> list[dict]:
    """Every Firefox window and its tabs, newest session state available.

    Returns a list of {"tabs": [{"title", "url"}], "selected": int} where
    `selected` is a 0-based index into `tabs`. Returns [] when Firefox has
    never run, the profile cannot be found, or the file cannot be parsed --
    all of which are normal, so none of them raise.
    """
    path = _session_file()
    if path is None:
        return []

    try:
        st = path.stat()
    except OSError:
        return []

    key = (str(path), st.st_mtime, st.st_size)
    if _cache["key"] == key:
        return _cache["value"]

    try:
        session = _read_mozlz4(path)
    except Exception:
        # A torn read mid-rewrite, an unknown format, a corrupt file: report no
        # tabs and let the caller fall back to the plain window entry.
        return []

    windows = []
    for w in session.get("windows", []):
        tabs = []
        for t in w.get("tabs", []):
            entries = t.get("entries", [])
            if not entries:
                continue
            # `index` is 1-based and points into the tab's own history stack;
            # the current page is the one we want, not the newest entry.
            idx = max(1, min(t.get("index", len(entries)), len(entries)))
            entry = entries[idx - 1]
            tabs.append({
                "title": entry.get("title") or entry.get("url") or "Untitled",
                "url": entry.get("url", ""),
            })
        if not tabs:
            continue
        selected = max(1, min(w.get("selected", 1), len(tabs))) - 1
        windows.append({"tabs": tabs, "selected": selected})

    _cache["key"] = key
    _cache["value"] = windows
    return windows
