"""YouTube search: find videos and open them in the browser.

yt-dlp is reached two ways, because which one exists depends on how vt was
started. The Python module is only importable by the interpreter it was
installed for -- a `pip install yt-dlp` inside a venv is invisible to
`python3 -m vt serve` -- while the `yt-dlp` command on PATH works for both.
Preferring the module and falling back to the command means the feature works
however the user installed it, and `unavailable_message()` says so plainly when
neither is there. Reporting that as "no results" sent the last debugging session
looking for a network problem that did not exist.
"""

import json
import shutil
import subprocess
import sys
from vt.model import Target, Action

try:
    import yt_dlp
    HAS_YT_DLP = True
except ImportError:
    yt_dlp = None
    HAS_YT_DLP = False

# Searches hit the network; yt-dlp itself is not slow, YouTube sometimes is.
SEARCH_TIMEOUT = 20


def cli_path() -> str:
    """Path to the yt-dlp command, or "" when it is not on PATH."""
    return shutil.which("yt-dlp") or ""


def backend() -> str:
    """Which yt-dlp we can actually use: "module", "cli", or "" for neither."""
    if HAS_YT_DLP:
        return "module"
    if cli_path():
        return "cli"
    return ""


def unavailable_message() -> str:
    """Why search cannot run, named precisely enough to act on."""
    return (
        "yt-dlp is not available to this interpreter "
        f"({sys.executable}). Install it with 'pipx install yt-dlp', "
        "'apt install yt-dlp', or pip install it into the interpreter you "
        "start vt with."
    )


def _entry_to_video(entry: dict) -> dict | None:
    """Normalise one yt-dlp entry into the shape the phone renders."""
    video_id = entry.get("id")
    if not video_id:
        return None
    return {
        "id": video_id,
        "title": entry.get("title") or "Unknown",
        # Flat playlist entries carry "channel"; full extraction carries
        # "uploader". Neither is guaranteed.
        "channel": entry.get("channel") or entry.get("uploader") or "Unknown",
        "duration": int(entry.get("duration") or 0),
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


def _search_module(query: str, limit: int) -> list[dict]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "default_search": "ytsearch",
        "socket_timeout": 10,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)

    videos = []
    for entry in (info.get("entries") or [])[:limit]:
        video = _entry_to_video(entry) if entry else None
        if video:
            videos.append(video)
    return videos


def _search_cli(query: str, limit: int) -> list[dict]:
    """Shell out to yt-dlp. --dump-json prints one JSON object per line."""
    result = subprocess.run(
        [
            cli_path(),
            "--flat-playlist",
            "--dump-json",
            "--no-warnings",
            "--skip-download",
            f"ytsearch{limit}:{query}",
        ],
        capture_output=True,
        text=True,
        timeout=SEARCH_TIMEOUT,
    )

    videos = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        video = _entry_to_video(entry)
        if video:
            videos.append(video)

    if not videos and result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr.splitlines()[-1] if stderr else "yt-dlp failed")
    return videos[:limit]


def search(query: str, limit: int = 15) -> tuple[list[dict], str]:
    """Search YouTube. Returns (videos, error) -- error is "" on success.

    An empty list with an empty error means the search ran and matched nothing,
    which is a different thing from the search never having run at all.
    """
    if not query or not query.strip():
        return [], ""

    which = backend()
    if not which:
        return [], unavailable_message()

    try:
        if which == "module":
            return _search_module(query, limit), ""
        return _search_cli(query, limit), ""
    except subprocess.TimeoutExpired:
        return [], "yt-dlp timed out; the network or YouTube is slow right now."
    except Exception as e:
        detail = str(e).strip().splitlines()[-1] if str(e).strip() else e.__class__.__name__
        return [], f"Search failed: {detail}"


def search_youtube(query: str, limit: int = 10) -> list[dict]:
    """Search YouTube, discarding the reason for any failure.

    Kept for callers that only want the list; prefer `search()`, which can tell
    "nothing matched" apart from "yt-dlp is not installed".
    """
    videos, _ = search(query, limit)
    return videos


def get_youtube_target() -> Target:
    """Return YouTube as a Target with a search action."""
    available = bool(backend())
    return Target(
        id="youtube:search",
        kind="youtube",
        title="YouTube",
        icon="▶",
        status="ready" if available else "yt-dlp not installed",
        actions=[Action(id="search", label="Search")] if available else [],
    )


def play_video(video_url: str) -> dict:
    """Open a YouTube video in the default browser."""
    try:
        subprocess.run(
            ["xdg-open", video_url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return {"ok": True, "message": "Playing video"}
    except FileNotFoundError:
        return {"ok": False, "message": "xdg-open not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Timeout opening browser"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}
