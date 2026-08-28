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
from urllib.parse import parse_qs, urlparse

from vt.model import Target, Action

try:
    import yt_dlp
    HAS_YT_DLP = True
except ImportError:
    yt_dlp = None
    HAS_YT_DLP = False

# Searches hit the network; yt-dlp itself is not slow, YouTube sometimes is.
SEARCH_TIMEOUT = 20

# The last video the phone asked for. `fix_autoplay` reopens it after the
# restart, so the tap that failed because autoplay was blocked completes
# itself rather than making the user search for the video a second time.
_last_video_url = ""


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


# yt-dlp has never promised a related-videos field, and which key holds it --
# when one is present at all -- has moved between extractor rewrites. Try the
# names that have been used, then fall back to a search, so the feature
# degrades to "more like this" instead of breaking outright.
_RELATED_KEYS = ("related_videos", "related", "up_next")


def video_id(url: str) -> str:
    """The video id in a YouTube URL, or "" when there is not one."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.hostname and "youtu.be" in parsed.hostname:
        return parsed.path.lstrip("/").split("/")[0]
    return (parse_qs(parsed.query).get("v") or [""])[0]


def current_video_url() -> str:
    """The YouTube watch URL open in the browser right now, or "".

    Read from Firefox's session store, the same file the tab list comes from --
    the window manager only ever reports a title, never a URL.
    """
    try:
        from vt.sources.firefox import get_firefox_windows
        sessions = get_firefox_windows()
    except Exception:
        return ""

    fallback = ""
    for session in sessions:
        tabs = session.get("tabs") or []
        selected = session.get("selected", 0)
        for i, tab in enumerate(tabs):
            url = tab.get("url") or ""
            if "youtube.com/watch" not in url and "youtu.be/" not in url:
                continue
            # The tab the user is looking at wins over one parked in the back.
            if i == selected:
                return url
            fallback = fallback or url
    return fallback


def _normalise_related(entry) -> dict | None:
    """Related entries are shaped like search entries, but not always keyed alike."""
    if not isinstance(entry, dict):
        return None
    if not entry.get("id") and entry.get("video_id"):
        entry = dict(entry, id=entry["video_id"])
    if not entry.get("duration") and entry.get("length_seconds"):
        entry = dict(entry, duration=entry["length_seconds"])
    return _entry_to_video(entry)


def _extract_info(url: str) -> dict:
    """Full metadata for one video, through whichever yt-dlp is available."""
    which = backend()
    if which == "module":
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 10,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False) or {}

    result = subprocess.run(
        [cli_path(), "-J", "--no-warnings", "--skip-download", url],
        capture_output=True,
        text=True,
        timeout=SEARCH_TIMEOUT,
    )
    if result.returncode != 0 and not result.stdout.strip():
        stderr = (result.stderr or "").strip()
        raise RuntimeError(stderr.splitlines()[-1] if stderr else "yt-dlp failed")
    return json.loads(result.stdout)


def related_videos(url: str = "", limit: int = 15) -> tuple[list[dict], str]:
    """Videos to watch next after `url`. Returns (videos, error).

    With no URL, whatever is playing in the browser is used -- the point of the
    feature is not having to know what that is.
    """
    if not backend():
        return [], unavailable_message()

    url = url.strip() or current_video_url()
    if not url:
        return [], (
            "No YouTube video is open. Play one first, or search for something "
            "instead."
        )

    try:
        info = _extract_info(url)
    except subprocess.TimeoutExpired:
        return [], "yt-dlp timed out; the network or YouTube is slow right now."
    except Exception as e:
        detail = str(e).strip().splitlines()[-1] if str(e).strip() else e.__class__.__name__
        return [], f"Could not read that video: {detail}"

    current = info.get("id") or video_id(url)

    videos = []
    for key in _RELATED_KEYS:
        for entry in info.get(key) or []:
            video = _normalise_related(entry)
            if video and video["id"] != current:
                videos.append(video)
            if len(videos) >= limit:
                break
        if videos:
            break

    if videos:
        return videos[:limit], ""

    # No related list in the metadata: search for the title instead. Not the
    # same thing as YouTube's sidebar, but it answers the same question.
    title = (info.get("title") or "").strip()
    if not title:
        return [], "That video carries no related list and no title to search on."

    results, error = search(title, limit + 1)
    if error:
        return [], error
    return [v for v in results if v["id"] != current][:limit], ""


def search_youtube(query: str, limit: int = 10) -> list[dict]:
    """Search YouTube, discarding the reason for any failure.

    Kept for callers that only want the list; prefer `search()`, which can tell
    "nothing matched" apart from "yt-dlp is not installed".
    """
    videos, _ = search(query, limit)
    return videos


def get_youtube_target() -> Target:
    """Return YouTube as a Target with a search action.

    When the browser is set to block autoplay, the target says so and offers to
    fix it. Without that the failure is invisible from the phone: the tap works,
    the tab opens, and nothing plays.
    """
    from vt.sources.browser_autoplay import state as autoplay_state

    available = bool(backend())
    if not available:
        return Target(
            id="youtube:search",
            kind="youtube",
            title="YouTube",
            icon="▶",
            status="yt-dlp not installed",
            note=unavailable_message(),
        )

    autoplay = autoplay_state()
    actions = [Action(id="search", label="Search")]
    note = ""
    status = "ready"
    if autoplay["status"] == "blocked":
        status = "autoplay blocked"
        note = autoplay["reason"] + " Tap 'Allow autoplay' to fix it from here."
        actions.append(
            Action(id="fix_autoplay", label="Allow autoplay (restarts Firefox)", kind="confirm")
        )
    elif autoplay["status"] == "unknown" and autoplay["reason"]:
        note = autoplay["reason"]

    return Target(
        id="youtube:search",
        kind="youtube",
        title="YouTube",
        icon="▶",
        status=status,
        note=note,
        actions=actions,
    )


def _open_url(video_url: str) -> dict:
    """Hand a URL to the desktop's default browser."""
    try:
        subprocess.run(
            ["xdg-open", video_url],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return {"ok": True, "message": ""}
    except FileNotFoundError:
        return {"ok": False, "message": "xdg-open not found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Timeout opening browser"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def play_video(video_url: str) -> dict:
    """Open a YouTube video in the default browser and report whether it plays.

    Opening is not playing. Firefox blocks autoplay of audible media by default,
    so the tab loads paused, publishes no MPRIS player, and never appears under
    Players -- the old "Playing video" reply claimed a success that had not
    happened, and left walking to the PC as the only way to find out. The
    autoplay policy is knowable up front, so check it and say which of the two
    actually occurred.
    """
    global _last_video_url
    from vt.sources.browser_autoplay import state as autoplay_state

    autoplay = autoplay_state()
    opened = _open_url(video_url)
    if not opened["ok"]:
        return opened
    _last_video_url = video_url

    if autoplay["status"] == "blocked":
        return {
            "ok": False,
            "message": (
                "Opened in the browser, but it is set to block autoplay so the "
                "video will not start. " + autoplay["fix"] +
                " Or use 'Allow autoplay' on the YouTube screen."
            ),
        }

    if autoplay["status"] == "unknown":
        return {"ok": True, "message": "Opened in the browser."}

    return {"ok": True, "message": "Playing — appears under Players in a few seconds."}


def last_video_url() -> str:
    """The most recent video the phone opened, or "" if there has not been one."""
    return _last_video_url


def fix_autoplay(reopen_url: str | None = None) -> dict:
    """Allow autoplay, then restart Firefox so the change takes effect.

    Both halves are needed and neither is enough alone: the pref is only read at
    startup, so writing it without a restart changes nothing the user can see.
    """
    from vt.sources.browser_autoplay import restart_firefox, set_autoplay

    if reopen_url is None:
        reopen_url = _last_video_url
    written = set_autoplay(allow=True)
    if not written["ok"]:
        return written

    if not written["needs_restart"]:
        return {"ok": True, "message": "Autoplay allowed. Videos will start on their own from now on."}

    restarted = restart_firefox(reopen_url)
    if not restarted["ok"]:
        return {"ok": False, "message": "Autoplay allowed, but " + restarted["message"]}
    return {"ok": True, "message": "Autoplay allowed and " + restarted["message"].lower()}
