"""Tests for sources (MPRIS, audio, apps, windows)."""

from pathlib import Path

import pytest

from vt.sources import apps
from vt.sources.audio import get_audio_targets


def test_audio_targets():
    """Test audio source."""
    targets = get_audio_targets()
    # Should return either a list with one target or an empty list (if wpctl is missing)
    assert isinstance(targets, list)
    if targets:
        assert targets[0].kind == "system"
        assert targets[0].id == "system:audio"
        assert any(a.id == "volume" for a in targets[0].actions)


# --- installed apps ---------------------------------------------------------

def _write(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text("[Desktop Entry]\n" + body)
    return path


@pytest.fixture
def desktop_dir(tmp_path, monkeypatch):
    """Point the .desktop scan at a directory we control."""
    monkeypatch.setattr(apps, "_DESKTOP_DIRS", (tmp_path,))
    apps.reset_index_cache()
    yield tmp_path
    apps.reset_index_cache()


def test_installed_apps_are_launchable_targets(desktop_dir):
    _write(desktop_dir, "firefox.desktop", "Name=Firefox\nGenericName=Web Browser\nExec=firefox %u\n")

    targets = apps.get_installed_targets()
    assert len(targets) == 1
    target = targets[0]
    assert target.id == "launcher:firefox"
    assert target.kind == "launcher"
    assert target.title == "Firefox"
    assert target.subtitle == "Web Browser"
    assert [a.id for a in target.actions] == ["launch"]


def test_installed_apps_do_not_need_the_app_to_be_running(desktop_dir):
    """The whole point: a stopped app is still launchable."""
    _write(desktop_dir, "gimp.desktop", "Name=GIMP\nExec=/usr/bin/gimp-2.10 %U\n")
    assert [t.title for t in apps.get_installed_targets()] == ["GIMP"]


def test_hidden_entries_are_skipped(desktop_dir):
    _write(desktop_dir, "a.desktop", "Name=Visible\nExec=vis\n")
    _write(desktop_dir, "b.desktop", "Name=NoDisplay\nNoDisplay=true\nExec=nd\n")
    _write(desktop_dir, "c.desktop", "Name=Hidden\nHidden=true\nExec=hd\n")
    # Terminal apps need a terminal emulator; launching one from a phone shows
    # the user nothing at all.
    _write(desktop_dir, "d.desktop", "Name=Htop\nTerminal=true\nExec=htop\n")

    assert [t.title for t in apps.get_installed_targets()] == ["Visible"]


def test_search_matches_name_generic_name_and_id(desktop_dir):
    _write(desktop_dir, "firefox.desktop", "Name=Firefox\nGenericName=Web Browser\nExec=firefox\n")
    _write(desktop_dir, "org.gnome.Nautilus.desktop", "Name=Files\nComment=Manage files\nExec=nautilus\n")

    assert [t.title for t in apps.get_installed_targets("browser")] == ["Firefox"]
    assert [t.title for t in apps.get_installed_targets("nautilus")] == ["Files"]
    assert [t.title for t in apps.get_installed_targets("manage files")] == ["Files"]
    assert apps.get_installed_targets("zzz") == []


def test_search_tokens_may_come_in_any_order(desktop_dir):
    _write(desktop_dir, "code.desktop", "Name=Visual Studio Code\nExec=code\n")
    assert len(apps.get_installed_targets("code studio")) == 1


def test_a_name_starting_with_the_query_sorts_first(desktop_dir):
    _write(desktop_dir, "a.desktop", "Name=Archive Manager\nComment=file roller\nExec=file-roller\n")
    _write(desktop_dir, "b.desktop", "Name=Files\nExec=nautilus\n")

    assert [t.title for t in apps.get_installed_targets("file")] == ["Files", "Archive Manager"]


def test_wrapped_exec_keeps_its_wrapper_but_not_its_field_codes(desktop_dir):
    """"flatpak run com.example.App" only works whole; %U must still go."""
    _write(
        desktop_dir,
        "com.example.App.desktop",
        "Name=Example\nExec=/usr/bin/flatpak run --branch=stable com.example.App %U\n",
    )
    entry = apps.get_installed_index()["com.example.App"]
    assert entry["argv"] == ["/usr/bin/flatpak", "run", "--branch=stable", "com.example.App"]
    # The binary is what a *process* will be called, which is what running-app
    # matching compares against -- a different question from how to start it.
    assert entry["binary"] == "com.example.app"


def test_quoted_exec_survives_splitting(desktop_dir):
    _write(desktop_dir, "q.desktop", 'Name=Quoted\nExec="/opt/My App/run.sh" --flag\n')
    assert apps.get_installed_index()["q"]["argv"] == ["/opt/My App/run.sh", "--flag"]


def test_the_index_is_rebuilt_after_the_ttl(desktop_dir, monkeypatch):
    """A server left running must notice apps installed after it started."""
    _write(desktop_dir, "one.desktop", "Name=One\nExec=one\n")
    assert len(apps.get_installed_targets()) == 1

    _write(desktop_dir, "two.desktop", "Name=Two\nExec=two\n")
    assert len(apps.get_installed_targets()) == 1, "cached, as intended"

    monkeypatch.setattr(apps, "_INDEX_TTL", -1)
    assert len(apps.get_installed_targets()) == 2


# --- MPRIS access denials ---------------------------------------------------

class _FakeDBusError(Exception):
    def __init__(self, name):
        super().__init__(name)
        self._name = name

    def get_dbus_name(self):
        return self._name


def test_a_refused_player_is_explained_not_swallowed(monkeypatch, capsys):
    """AccessDenied looks exactly like "no players running" unless we say so.

    Under snap confinement -- a `vt serve` started from the VS Code snap's
    terminal, say -- every property read on snap-packaged Firefox is refused,
    and the player silently vanished from the UI.
    """
    from vt.sources import mpris

    mpris.reset_access_denied_hint()
    monkeypatch.setattr(mpris, "dbus_denied_message", lambda: "denied: snap.code.code")

    class Props:
        def Get(self, iface, prop):
            raise _FakeDBusError("org.freedesktop.DBus.Error.AccessDenied")

    assert mpris._get(Props(), "iface", "PlaybackStatus") is None
    assert mpris.access_denied_hint() == "denied: snap.code.code"
    assert "denied: snap.code.code" in capsys.readouterr().out
    mpris.reset_access_denied_hint()


def test_an_ordinary_missing_property_is_not_reported_as_a_denial():
    """Firefox has no CanRaise; that is not a permission problem."""
    from vt.sources import mpris

    mpris.reset_access_denied_hint()

    class Props:
        def Get(self, iface, prop):
            raise _FakeDBusError("org.freedesktop.DBus.Error.InvalidArgs")

    assert mpris._get(Props(), "iface", "CanRaise", False) is False
    assert mpris.access_denied_hint() is None


# --- MPRIS seek quirk -------------------------------------------------------

def test_firefox_seek_is_withheld_because_it_breaks_the_player():
    """Firefox sets CanSeek=true and implements neither Seek nor SetPosition.

    Either call returns without error, playback does not move, and the player
    then reports Position=0 with no mpris:length for the rest of the track --
    so the progress readout never comes back. Verified against Firefox 154
    (snap) on GNOME 50/Wayland. Trusting CanSeek there hands the user a button
    that silently breaks the display beside it.
    """
    from vt.sources import mpris

    assert not mpris._seek_is_trustworthy(
        "org.mpris.MediaPlayer2.firefox.instance_1_9397", "Firefox"
    )
    # Forks ship the same media backend.
    assert not mpris._seek_is_trustworthy("org.mpris.MediaPlayer2.librewolf", "LibreWolf")


def test_a_normal_player_keeps_its_seek_controls():
    """The quirk is targeted: VLC and friends implement Seek correctly."""
    from vt.sources import mpris

    assert mpris._seek_is_trustworthy("org.mpris.MediaPlayer2.vlc", "VLC media player")
    assert mpris._seek_is_trustworthy("org.mpris.MediaPlayer2.spotify", "Spotify")
    assert mpris._seek_is_trustworthy("org.mpris.MediaPlayer2.mpv", "mpv")


def test_the_withheld_seek_is_explained_rather_than_silently_absent():
    """A missing control with no reason reads as a gap in vt, not in the player."""
    from vt.sources import mpris

    assert "does not implement it" in mpris.SEEK_UNAVAILABLE_REASON


# --- YouTube search ---------------------------------------------------------

def test_missing_yt_dlp_is_reported_not_silent(monkeypatch):
    """A missing yt-dlp must not read as "no results".

    It did, and the reason took a debugging session to find: yt-dlp installed
    into a venv is invisible to `python3 -m vt serve`, and the phone showed
    "No results found" -- indistinguishable from a query that matched nothing.
    """
    from vt.sources import youtube

    monkeypatch.setattr(youtube, "HAS_YT_DLP", False)
    monkeypatch.setattr(youtube, "cli_path", lambda: "")

    results, error = youtube.search("test")
    assert results == []
    assert "yt-dlp is not available" in error
    assert youtube.backend() == ""


def test_nothing_matched_is_not_an_error(monkeypatch):
    """An empty result with no error is a search that ran and found nothing."""
    from vt.sources import youtube

    monkeypatch.setattr(youtube, "HAS_YT_DLP", True)
    monkeypatch.setattr(youtube, "_search_module", lambda q, limit: [])

    results, error = youtube.search("zzzzz")
    assert results == []
    assert error == ""


def test_the_cli_is_used_when_the_module_is_missing(monkeypatch):
    """yt-dlp on PATH works for whichever interpreter started vt."""
    from vt.sources import youtube

    monkeypatch.setattr(youtube, "HAS_YT_DLP", False)
    monkeypatch.setattr(youtube, "cli_path", lambda: "/usr/bin/yt-dlp")
    assert youtube.backend() == "cli"

    seen = {}

    class Result:
        returncode = 0
        stdout = '{"id": "abc123", "title": "A Video", "channel": "Someone", "duration": 42}\n'
        stderr = ""

    monkeypatch.setattr(
        youtube.subprocess, "run", lambda argv, **kw: seen.update(argv=argv) or Result()
    )

    results, error = youtube.search("a video", 5)
    assert error == ""
    assert results == [{
        "id": "abc123",
        "title": "A Video",
        "channel": "Someone",
        "duration": 42,
        "url": "https://www.youtube.com/watch?v=abc123",
    }]
    assert seen["argv"][-1] == "ytsearch5:a video"


def test_a_failing_cli_reports_its_own_stderr(monkeypatch):
    from vt.sources import youtube

    monkeypatch.setattr(youtube, "HAS_YT_DLP", False)
    monkeypatch.setattr(youtube, "cli_path", lambda: "/usr/bin/yt-dlp")

    class Result:
        returncode = 1
        stdout = ""
        stderr = "ERROR: unable to download video data: HTTP Error 429"

    monkeypatch.setattr(youtube.subprocess, "run", lambda argv, **kw: Result())
    results, error = youtube.search("x")
    assert results == []
    assert "429" in error


def test_a_slow_search_is_reported_as_a_timeout(monkeypatch):
    from vt.sources import youtube

    monkeypatch.setattr(youtube, "HAS_YT_DLP", False)
    monkeypatch.setattr(youtube, "cli_path", lambda: "/usr/bin/yt-dlp")

    def timeout(argv, **kw):
        raise youtube.subprocess.TimeoutExpired(argv, youtube.SEARCH_TIMEOUT)

    monkeypatch.setattr(youtube.subprocess, "run", timeout)
    results, error = youtube.search("x")
    assert results == []
    assert "timed out" in error


def test_youtube_search_returns_video_info():
    """A successful search returns video metadata."""
    from vt.sources import youtube

    if not youtube.backend():
        pytest.skip("yt-dlp not installed")

    results = youtube.search_youtube("cat", limit=3)
    assert len(results) <= 3
    if results:
        video = results[0]
        assert "id" in video
        assert "title" in video
        assert "channel" in video
        assert "url" in video
        assert "youtube.com" in video["url"]


def test_youtube_search_empty_query_returns_empty():
    """Empty or whitespace-only queries return no results, and no error."""
    from vt.sources import youtube

    assert youtube.search("") == ([], "")
    assert youtube.search("   ") == ([], "")


def test_youtube_target_has_search_action():
    """The YouTube target offers a search action."""
    from vt.sources import youtube

    if not youtube.backend():
        pytest.skip("yt-dlp not installed")

    target = youtube.get_youtube_target()
    assert target.kind == "youtube"
    assert any(a.id == "search" for a in target.actions)


# --- YouTube player controls ------------------------------------------------

def test_youtube_player_target_is_none_when_no_window(monkeypatch):
    """When no YouTube video is playing, no player target is returned."""
    from vt.sources import youtube_player

    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(youtube_player.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(youtube_player, "find_youtube_window", lambda: None)
    assert youtube_player.get_youtube_player_target() is None


def test_youtube_player_target_has_controls(monkeypatch):
    """On X11 with the tools present, a YouTube window gets keystroke controls."""
    from vt.sources import youtube_player

    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(youtube_player.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        youtube_player, "find_youtube_window",
        lambda: {"id": "0x123", "name": "YouTube - My Video"}
    )
    target = youtube_player.get_youtube_player_target()
    assert target is not None
    assert target.kind == "youtube_player"
    action_ids = [a.id for a in target.actions]
    assert "play_pause" in action_ids
    assert "seek_back" in action_ids
    assert "seek_fwd" in action_ids
    assert "close" in action_ids


def test_missing_x11_tools_are_named(monkeypatch):
    """"Install xdotool" beats a button that silently does nothing."""
    from vt.sources import youtube_player

    monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
    monkeypatch.setattr(youtube_player.shutil, "which", lambda name: None)
    monkeypatch.setattr(youtube_player, "find_youtube_tab", lambda: None)
    reason = youtube_player.x11_unavailable_reason()
    assert "xdotool" in reason and "wmctrl" in reason
    assert youtube_player.get_youtube_player_target() is None


def test_youtube_tab_found_by_window_title(monkeypatch):
    """A window titled "... - YouTube" is already showing it in its active tab.

    That needs no tab switch, so the chord is empty -- and it is the only route
    that works for browsers whose tabs cannot be enumerated at all.
    """
    from vt.sources import youtube_player

    monkeypatch.setattr(youtube_player, "list_windows", lambda: [
        {"id": 7, "title": "Never Gonna Give You Up - YouTube — Mozilla Firefox",
         "wm_class": "firefox"},
    ])

    entry = youtube_player.find_youtube_tab()
    assert entry == {"wid": 7, "chord": "", "title": "Never Gonna Give You Up - YouTube"}
    # No tab switch means no address-bar guard either: the keys go straight in.
    assert youtube_player._chord_for(entry, "f") == "f"


def test_a_window_merely_mentioning_youtube_is_not_a_player(monkeypatch):
    """An editor holding youtube.py must not receive the playback keystrokes.

    Matching on the title alone would send "f" into someone's source file.
    """
    from vt.sources import youtube_player

    monkeypatch.setattr(youtube_player, "list_windows", lambda: [
        {"id": 3, "title": "youtube_player.py - voicetalk - VS Code", "wm_class": "code"},
        {"id": 5, "title": "yt-dlp youtube.com — Terminal", "wm_class": "org.gnome.Ptyxis"},
    ])
    monkeypatch.setattr(youtube_player, "get_firefox_windows", list)

    assert youtube_player.find_youtube_tab() is None


def test_youtube_tab_found_in_a_background_tab(monkeypatch):
    """A video parked behind other tabs still has to be reachable."""
    from vt.sources import youtube_player

    monkeypatch.setattr(youtube_player, "list_windows", lambda: [
        {"id": 4, "title": "Inbox — Mozilla Firefox", "wm_class": "firefox"},
    ])
    monkeypatch.setattr(youtube_player, "get_firefox_windows", lambda: [
        {"selected": 0, "tabs": [
            {"title": "Inbox", "url": "https://mail.example.com/"},
            {"title": "Docs", "url": "https://docs.example.com/"},
            {"title": "Cats", "url": "https://www.youtube.com/watch?v=abc"},
        ]},
    ])

    entry = youtube_player.find_youtube_tab()
    assert entry["wid"] == 4
    assert entry["chord"] == "alt+3"
    # Alt+N is not reserved, so the page gets taken out of the keyboard path
    # first -- otherwise a web app that binds Alt+3 swallows the tab switch.
    assert youtube_player._chord_for(entry, "f") == "ctrl+l,alt+3,escape,f"


def test_youtube_keys_go_through_the_extension(monkeypatch):
    """On Wayland the extension is the only route, so the chord must reach it."""
    from vt.sources import youtube_player

    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setattr(
        youtube_player, "find_youtube_tab",
        lambda: {"wid": 9, "chord": "", "title": "Cats"},
    )

    sent = []

    class FakeInterface:
        def SendKeys(self, wid, chord):
            sent.append((int(wid), chord))

    monkeypatch.setattr(youtube_player, "shell_interface", lambda: FakeInterface())

    assert youtube_player.send_keys("fullscreen")["ok"] is True
    assert sent == [(9, "f")]

    sent.clear()
    assert youtube_player.send_keys("volume_up")["ok"] is True
    assert sent == [(9, "up")]

    sent.clear()
    assert youtube_player.close_youtube_window()["ok"] is True
    assert sent == [(9, "ctrl+w")]


# --- YouTube: what to watch next --------------------------------------------

def test_video_id_is_read_from_either_url_shape():
    from vt.sources import youtube

    assert youtube.video_id("https://www.youtube.com/watch?v=abc123&t=30") == "abc123"
    assert youtube.video_id("https://youtu.be/abc123") == "abc123"
    assert youtube.video_id("https://example.com/") == ""


def test_current_video_prefers_the_tab_being_watched(monkeypatch):
    """Two YouTube tabs open: the one in front is the one being asked about."""
    from vt.sources import youtube

    monkeypatch.setattr(
        "vt.sources.firefox.get_firefox_windows",
        lambda: [{"selected": 2, "tabs": [
            {"title": "Docs", "url": "https://docs.example.com/"},
            {"title": "Old", "url": "https://www.youtube.com/watch?v=background"},
            {"title": "Now", "url": "https://www.youtube.com/watch?v=foreground"},
        ]}],
    )

    assert youtube.current_video_url().endswith("v=foreground")


def test_related_videos_use_the_metadata_list(monkeypatch):
    from vt.sources import youtube

    monkeypatch.setattr(youtube, "backend", lambda: "module")
    monkeypatch.setattr(youtube, "_extract_info", lambda url: {
        "id": "current",
        "title": "The current video",
        "related_videos": [
            {"id": "next1", "title": "Next one", "channel": "Chan", "duration": 90},
            {"id": "current", "title": "The current video", "duration": 60},
        ],
    })

    videos, error = youtube.related_videos("https://www.youtube.com/watch?v=current")
    assert error == ""
    # The video already playing is not something to play next.
    assert [v["id"] for v in videos] == ["next1"]
    assert videos[0]["url"] == "https://www.youtube.com/watch?v=next1"


def test_related_videos_fall_back_to_searching_the_title(monkeypatch):
    """yt-dlp has never promised a related list, so its absence is not a failure."""
    from vt.sources import youtube

    monkeypatch.setattr(youtube, "backend", lambda: "module")
    monkeypatch.setattr(youtube, "_extract_info",
                        lambda url: {"id": "current", "title": "Lo-fi beats"})

    searched = []

    def fake_search(query, limit):
        searched.append(query)
        return [
            {"id": "current", "title": "Lo-fi beats", "channel": "C", "duration": 1, "url": "u"},
            {"id": "other", "title": "More lo-fi", "channel": "C", "duration": 2, "url": "u2"},
        ], ""

    monkeypatch.setattr(youtube, "search", fake_search)

    videos, error = youtube.related_videos("https://www.youtube.com/watch?v=current")
    assert error == ""
    assert searched == ["Lo-fi beats"]
    assert [v["id"] for v in videos] == ["other"]


def test_related_videos_without_a_video_say_what_to_do(monkeypatch):
    from vt.sources import youtube

    monkeypatch.setattr(youtube, "backend", lambda: "module")
    monkeypatch.setattr(youtube, "current_video_url", lambda: "")

    videos, error = youtube.related_videos("")
    assert videos == []
    assert "No YouTube video is open" in error


def test_related_videos_report_a_missing_yt_dlp(monkeypatch):
    """"No results" is how a missing dependency came to look like a network fault."""
    from vt.sources import youtube

    monkeypatch.setattr(youtube, "backend", lambda: "")
    videos, error = youtube.related_videos("https://www.youtube.com/watch?v=x")
    assert videos == []
    assert "yt-dlp" in error
