"""Tests for autoplay detection and the play path that depends on it.

The bug these cover is not a crash: opening a YouTube URL in a browser that
blocks autoplay succeeds at every step vt can see, and the video still never
plays. So what is asserted here is mostly what vt *says* -- a play reply that
claims success when the video is sitting paused is the actual defect.
"""

import configparser

import pytest

from vt.sources import browser_autoplay as ba
from vt.sources import youtube


@pytest.fixture(autouse=True)
def clear_cache():
    ba._invalidate()
    yield
    ba._invalidate()


def _make_profile(tmp_path, prefs=None, user_js=None, name="abc123.default"):
    """Build a Firefox profile root the way Firefox lays one out."""
    root = tmp_path / "firefox"
    profile = root / name
    profile.mkdir(parents=True)

    ini = configparser.ConfigParser()
    ini["Profile0"] = {"Name": "default", "IsRelative": "1", "Path": name, "Default": "1"}
    ini["General"] = {"StartWithLastProfile": "1", "Version": "2"}
    with open(root / "profiles.ini", "w") as fh:
        ini.write(fh)

    if prefs is not None:
        (profile / "prefs.js").write_text(prefs)
    if user_js is not None:
        (profile / "user.js").write_text(user_js)
    return root, profile


def _use_profile(monkeypatch, profile):
    monkeypatch.setattr(ba, "default_profile", lambda: profile)


# --- reading the setting -----------------------------------------------------

def test_missing_pref_reads_as_blocked(tmp_path, monkeypatch):
    """Firefox's built-in default blocks audible autoplay, so absent means blocked."""
    _, profile = _make_profile(tmp_path, prefs='user_pref("browser.startup.page", 3);\n')
    _use_profile(monkeypatch, profile)

    result = ba.state()
    assert result["status"] == "blocked"
    assert result["fix"]


def test_allow_pref_reads_as_allowed(tmp_path, monkeypatch):
    _, profile = _make_profile(tmp_path, prefs='user_pref("media.autoplay.default", 0);\n')
    _use_profile(monkeypatch, profile)

    assert ba.state()["status"] == "allowed"


def test_block_all_reads_as_blocked(tmp_path, monkeypatch):
    _, profile = _make_profile(tmp_path, prefs='user_pref("media.autoplay.default", 5);\n')
    _use_profile(monkeypatch, profile)

    result = ba.state()
    assert result["status"] == "blocked"
    assert "all media" in result["reason"]


def test_user_js_wins_over_prefs_js(tmp_path, monkeypatch):
    """Firefox replays user.js over prefs.js on every start, so it decides."""
    _, profile = _make_profile(
        tmp_path,
        prefs='user_pref("media.autoplay.default", 1);\n',
        user_js='user_pref("media.autoplay.default", 0);\n',
    )
    _use_profile(monkeypatch, profile)

    assert ba.state()["status"] == "allowed"


def test_pref_parsing_tolerates_whitespace(tmp_path, monkeypatch):
    _, profile = _make_profile(tmp_path, prefs='user_pref( "media.autoplay.default" ,  0 );\n')
    _use_profile(monkeypatch, profile)

    assert ba.state()["status"] == "allowed"


def test_no_profile_is_unknown_not_blocked(monkeypatch):
    """An unknown setting must not be reported as a fault vt can fix."""
    monkeypatch.setattr(ba, "default_profile", lambda: None)
    monkeypatch.setattr(ba, "default_browser", lambda: "chromium.desktop")

    result = ba.state()
    assert result["status"] == "unknown"
    assert result["fix"] == ""


# --- profile discovery -------------------------------------------------------

def test_install_section_beats_profile_default(tmp_path, monkeypatch):
    """The [Install] entry is the profile Firefox actually launches with."""
    root = tmp_path / "firefox"
    (root / "old.default").mkdir(parents=True)
    (root / "current.default").mkdir(parents=True)
    (root / "profiles.ini").write_text(
        "[Profile0]\nName=old\nIsRelative=1\nPath=old.default\nDefault=1\n\n"
        "[Install4F96D1932A9F858E]\nDefault=current.default\n"
    )
    monkeypatch.setattr(ba, "profile_roots", lambda: [root])

    assert ba.default_profile() == root / "current.default"


def test_profile_found_without_profiles_ini(tmp_path, monkeypatch):
    root = tmp_path / "firefox"
    (root / "xyz.default-release").mkdir(parents=True)
    monkeypatch.setattr(ba, "profile_roots", lambda: [root])

    assert ba.default_profile() == root / "xyz.default-release"


# --- writing the setting -----------------------------------------------------

def test_set_autoplay_writes_user_js(tmp_path, monkeypatch):
    _, profile = _make_profile(tmp_path)
    _use_profile(monkeypatch, profile)
    monkeypatch.setattr(ba, "firefox_pids", lambda: [])

    result = ba.set_autoplay(allow=True)
    assert result["ok"]
    assert result["needs_restart"] is False
    assert 'user_pref("media.autoplay.default", 0);' in (profile / "user.js").read_text()
    assert ba.state()["status"] == "allowed"


def test_set_autoplay_preserves_unrelated_prefs(tmp_path, monkeypatch):
    _, profile = _make_profile(tmp_path, user_js='user_pref("browser.tabs.warnOnClose", false);\n')
    _use_profile(monkeypatch, profile)
    monkeypatch.setattr(ba, "firefox_pids", lambda: [])

    ba.set_autoplay(allow=True)
    text = (profile / "user.js").read_text()
    assert "browser.tabs.warnOnClose" in text
    assert 'user_pref("media.autoplay.default", 0);' in text


def test_set_autoplay_is_idempotent(tmp_path, monkeypatch):
    """Repeated runs must not stack duplicate lines that shadow each other."""
    _, profile = _make_profile(tmp_path)
    _use_profile(monkeypatch, profile)
    monkeypatch.setattr(ba, "firefox_pids", lambda: [])

    ba.set_autoplay(allow=True)
    ba.set_autoplay(allow=True)
    ba.set_autoplay(allow=True)

    text = (profile / "user.js").read_text()
    assert text.count("media.autoplay.default") == 1


def test_revert_removes_only_our_line(tmp_path, monkeypatch):
    _, profile = _make_profile(tmp_path, user_js='user_pref("browser.tabs.warnOnClose", false);\n')
    _use_profile(monkeypatch, profile)
    monkeypatch.setattr(ba, "firefox_pids", lambda: [])

    ba.set_autoplay(allow=True)
    ba.set_autoplay(allow=False)

    text = (profile / "user.js").read_text()
    assert "media.autoplay.default" not in text
    assert "browser.tabs.warnOnClose" in text


def test_revert_deletes_a_user_js_it_emptied(tmp_path, monkeypatch):
    """Leaving an empty user.js behind would keep overriding Firefox's own UI."""
    _, profile = _make_profile(tmp_path)
    _use_profile(monkeypatch, profile)
    monkeypatch.setattr(ba, "firefox_pids", lambda: [])

    ba.set_autoplay(allow=True)
    ba.set_autoplay(allow=False)

    assert not (profile / "user.js").exists()


def test_set_autoplay_flags_restart_while_firefox_runs(tmp_path, monkeypatch):
    """The pref is read once at startup; not saying so reads as "it didn't work"."""
    _, profile = _make_profile(tmp_path)
    _use_profile(monkeypatch, profile)
    monkeypatch.setattr(ba, "firefox_pids", lambda: [4242])

    assert ba.set_autoplay(allow=True)["needs_restart"] is True


def test_set_autoplay_without_profile_fails_cleanly(monkeypatch):
    monkeypatch.setattr(ba, "default_profile", lambda: None)

    result = ba.set_autoplay(allow=True)
    assert result["ok"] is False
    assert "profile" in result["message"].lower()


# --- what the phone is told --------------------------------------------------

def test_play_video_reports_blocked_autoplay(monkeypatch):
    """The old reply said "Playing video" for a tab that sat there paused."""
    monkeypatch.setattr(youtube, "_open_url", lambda url: {"ok": True, "message": ""})
    monkeypatch.setattr(
        ba, "state",
        lambda force=False: {
            "status": "blocked", "reason": "blocked",
            "fix": "Run 'vt allow-autoplay'.", "profile": "/p",
        },
    )

    result = youtube.play_video("https://www.youtube.com/watch?v=abc")
    assert result["ok"] is False
    assert "allow-autoplay" in result["message"]


def test_play_video_reports_playing_when_allowed(monkeypatch):
    monkeypatch.setattr(youtube, "_open_url", lambda url: {"ok": True, "message": ""})
    monkeypatch.setattr(
        ba, "state",
        lambda force=False: {"status": "allowed", "reason": "", "fix": "", "profile": "/p"},
    )

    result = youtube.play_video("https://www.youtube.com/watch?v=abc")
    assert result["ok"] is True
    assert "Players" in result["message"]


def test_play_video_surfaces_open_failure(monkeypatch):
    monkeypatch.setattr(
        youtube, "_open_url", lambda url: {"ok": False, "message": "xdg-open not found"}
    )
    monkeypatch.setattr(
        ba, "state",
        lambda force=False: {"status": "allowed", "reason": "", "fix": "", "profile": "/p"},
    )

    assert youtube.play_video("https://x")["ok"] is False


def test_play_video_remembers_url_for_the_fix(monkeypatch):
    """Fixing autoplay should resume the video, not send the user searching again."""
    monkeypatch.setattr(youtube, "_open_url", lambda url: {"ok": True, "message": ""})
    monkeypatch.setattr(
        ba, "state",
        lambda force=False: {"status": "blocked", "reason": "r", "fix": "f", "profile": "/p"},
    )

    youtube.play_video("https://www.youtube.com/watch?v=remembered")
    assert youtube.last_video_url() == "https://www.youtube.com/watch?v=remembered"


def test_youtube_target_offers_the_fix_when_blocked(monkeypatch):
    monkeypatch.setattr(youtube, "backend", lambda: "module")
    monkeypatch.setattr(
        ba, "state",
        lambda force=False: {
            "status": "blocked", "reason": "Firefox blocks autoplay.",
            "fix": "f", "profile": "/p",
        },
    )

    target = youtube.get_youtube_target()
    assert target.note
    fix = [a for a in target.actions if a.id == "fix_autoplay"]
    assert fix and fix[0].kind == "confirm"


def test_youtube_target_is_quiet_when_allowed(monkeypatch):
    monkeypatch.setattr(youtube, "backend", lambda: "module")
    monkeypatch.setattr(
        ba, "state",
        lambda force=False: {"status": "allowed", "reason": "fine", "fix": "", "profile": "/p"},
    )

    target = youtube.get_youtube_target()
    assert target.note == ""
    assert [a.id for a in target.actions] == ["search"]


def test_fix_autoplay_restarts_and_resumes(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        ba, "set_autoplay",
        lambda allow=True: {"ok": True, "message": "written", "needs_restart": True},
    )
    monkeypatch.setattr(
        ba, "restart_firefox",
        lambda url="": seen.update(url=url) or {"ok": True, "message": "Firefox restarted."},
    )

    result = youtube.fix_autoplay("https://www.youtube.com/watch?v=resume")
    assert result["ok"] is True
    assert seen["url"] == "https://www.youtube.com/watch?v=resume"


def test_fix_autoplay_skips_restart_when_firefox_is_closed(monkeypatch):
    monkeypatch.setattr(
        ba, "set_autoplay",
        lambda allow=True: {"ok": True, "message": "written", "needs_restart": False},
    )
    monkeypatch.setattr(
        ba, "restart_firefox",
        lambda url="": pytest.fail("must not restart a browser that is not running"),
    )

    assert youtube.fix_autoplay("")["ok"] is True


def test_fix_autoplay_reports_a_failed_write(monkeypatch):
    monkeypatch.setattr(
        ba, "set_autoplay",
        lambda allow=True: {"ok": False, "message": "Cannot write", "needs_restart": False},
    )

    assert youtube.fix_autoplay("")["ok"] is False


def test_action_dispatch_routes_fix_autoplay(monkeypatch):
    from vt import actions

    monkeypatch.setattr(youtube, "fix_autoplay", lambda: {"ok": True, "message": "done"})
    result = actions.execute_action("youtube:search", "fix_autoplay", None)
    assert result["ok"] is True


def test_revert_reports_a_value_firefox_has_persisted(tmp_path, monkeypatch):
    """Firefox copies user.js prefs into prefs.js, where vt cannot take them back."""
    _, profile = _make_profile(tmp_path, prefs='user_pref("media.autoplay.default", 0);\n')
    _use_profile(monkeypatch, profile)
    monkeypatch.setattr(ba, "firefox_pids", lambda: [])

    result = ba.set_autoplay(allow=False)
    assert result["ok"]
    assert "Settings" in result["residual"]
    # And the state must keep telling the truth: it is still allowed.
    assert ba.state()["status"] == "allowed"


def test_revert_reports_nothing_residual_when_prefs_are_clean(tmp_path, monkeypatch):
    _, profile = _make_profile(tmp_path)
    _use_profile(monkeypatch, profile)
    monkeypatch.setattr(ba, "firefox_pids", lambda: [])

    ba.set_autoplay(allow=True)
    assert ba.set_autoplay(allow=False)["residual"] == ""
