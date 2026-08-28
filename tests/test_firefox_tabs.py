"""Tests for Firefox tab enumeration and tab-targeted window actions."""

import json
import struct

import pytest

import vt.actions as actions
from vt.sources import firefox
from vt.sources.windows import (
    _match_session_window,
    _strip_browser_suffix,
    _tab_chord,
)


# --- mozlz4 / LZ4 block decoding -------------------------------------------

def test_lz4_literals_only():
    """A block that is nothing but a literal run."""
    block = bytes([0x50]) + b"hello"
    assert firefox._lz4_block_decompress(block) == b"hello"


def test_lz4_non_overlapping_match():
    """A match that copies from far enough back to be a plain slice."""
    block = bytes([0x60]) + b"abcdef" + bytes([0x06, 0x00])
    assert firefox._lz4_block_decompress(block) == b"abcdefabcd"


def test_lz4_overlapping_match():
    """An RLE-style run where the match reads bytes it is still writing.

    This is the case a naive slice copy gets wrong, so it is the one that
    matters most.
    """
    block = bytes([0x32]) + b"abc" + bytes([0x03, 0x00])
    assert firefox._lz4_block_decompress(block) == b"abcabcabc"


def test_lz4_long_literal_run():
    """Literal lengths of 15 or more continue into extra length bytes."""
    payload = bytes(range(20))
    block = bytes([0xF0, 0x05]) + payload
    assert firefox._lz4_block_decompress(block) == payload


def test_lz4_rejects_zero_offset():
    block = bytes([0x60]) + b"abcdef" + bytes([0x00, 0x00])
    with pytest.raises(ValueError):
        firefox._lz4_block_decompress(block)


def _write_mozlz4(path, obj):
    """Store JSON as an uncompressed-but-valid mozlz4 file.

    The whole payload goes out as one literal run, which is legal LZ4 and
    exercises the real header path without needing a compressor. It must be a
    *single* sequence: only the last sequence in a block may omit its match, so
    chaining several literal runs would not be a valid stream.
    """
    raw = json.dumps(obj).encode()
    block = bytearray()
    if len(raw) < 15:
        block.append(len(raw) << 4)
    else:
        block.append(0xF0)
        rest = len(raw) - 15
        while rest >= 255:
            block.append(255)
            rest -= 255
        block.append(rest)
    block += raw
    path.write_bytes(firefox.MAGIC + struct.pack("<I", len(raw)) + bytes(block))


def test_read_mozlz4_roundtrip(tmp_path):
    obj = {"windows": [{"tabs": [], "selected": 1}]}
    p = tmp_path / "recovery.jsonlz4"
    _write_mozlz4(p, obj)
    assert firefox._read_mozlz4(p) == obj


def test_read_mozlz4_rejects_foreign_file(tmp_path):
    p = tmp_path / "recovery.jsonlz4"
    p.write_bytes(b"{}")
    with pytest.raises(ValueError):
        firefox._read_mozlz4(p)


# --- session store -> window/tab structure ---------------------------------

@pytest.fixture
def session(tmp_path, monkeypatch):
    """Point the reader at a synthetic profile and clear its mtime cache."""
    def install(obj):
        profile = tmp_path / "abc.default" / "sessionstore-backups"
        profile.mkdir(parents=True, exist_ok=True)
        _write_mozlz4(profile / "recovery.jsonlz4", obj)
        monkeypatch.setattr(firefox, "PROFILE_ROOTS", [tmp_path])
        firefox._cache["key"] = None
        return firefox.get_firefox_windows()
    return install


def _tab(title, url="https://example.com/", index=1):
    return {"index": index, "entries": [{"title": title, "url": url}]}


def test_tabs_are_enumerated(session):
    windows = session({"windows": [{
        "selected": 2,
        "tabs": [_tab("First"), _tab("Second"), _tab("Third")],
    }]})
    assert len(windows) == 1
    assert [t["title"] for t in windows[0]["tabs"]] == ["First", "Second", "Third"]
    # `selected` is 1-based in the file and 0-based in our model.
    assert windows[0]["selected"] == 1


def test_tab_uses_current_history_entry(session):
    """A tab's `index` points into its back/forward stack, not at the newest."""
    windows = session({"windows": [{
        "selected": 1,
        "tabs": [{
            "index": 1,
            "entries": [
                {"title": "Where we are", "url": "https://a/"},
                {"title": "Forward history", "url": "https://b/"},
            ],
        }],
    }]})
    assert windows[0]["tabs"][0]["title"] == "Where we are"


def test_tabs_without_entries_are_skipped(session):
    windows = session({"windows": [{
        "selected": 1,
        "tabs": [_tab("Real"), {"index": 1, "entries": []}],
    }]})
    assert [t["title"] for t in windows[0]["tabs"]] == ["Real"]


def test_selected_index_is_clamped(session):
    """A torn read can name a selected tab that is no longer there."""
    windows = session({"windows": [{"selected": 99, "tabs": [_tab("Only")]}]})
    assert windows[0]["selected"] == 0


def test_missing_profile_is_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(firefox, "PROFILE_ROOTS", [tmp_path / "nope"])
    firefox._cache["key"] = None
    assert firefox.get_firefox_windows() == []


def test_corrupt_session_store_is_not_an_error(monkeypatch, tmp_path):
    profile = tmp_path / "abc.default" / "sessionstore-backups"
    profile.mkdir(parents=True)
    (profile / "recovery.jsonlz4").write_bytes(b"garbage that is not mozlz4")
    monkeypatch.setattr(firefox, "PROFILE_ROOTS", [tmp_path])
    firefox._cache["key"] = None
    assert firefox.get_firefox_windows() == []


# --- chord generation -------------------------------------------------------

@pytest.mark.parametrize("index,total,expected", [
    (0, 3, "alt+1"),
    (2, 3, "alt+3"),
    (7, 20, "alt+8"),
    (19, 20, "alt+9"),          # last tab has its own shortcut
    (2, 3, "alt+3"),
])
def test_tab_chord_direct(index, total, expected):
    assert _tab_chord(index, total) == expected


def test_tab_chord_beyond_alt_range_walks_forward():
    """Tabs 9..n-1 have no shortcut, so land on 8 and step forward."""
    assert _tab_chord(8, 20) == "alt+8,ctrl+page_down"
    assert _tab_chord(10, 20) == "alt+8," + ",".join(["ctrl+page_down"] * 3)


def test_tab_chord_last_tab_wins_over_walk():
    """The final tab is always alt+9, however far past 8 it sits."""
    assert _tab_chord(30, 31) == "alt+9"


# --- window title <-> session matching --------------------------------------

def test_strip_browser_suffix_handles_dash_variants():
    for dash in ("—", "-", "–"):
        assert _strip_browser_suffix(f"Page {dash} Mozilla Firefox") == "Page"
    assert _strip_browser_suffix("No suffix here") == "No suffix here"


def _sess(titles, selected=0):
    return {"tabs": [{"title": t, "url": ""} for t in titles], "selected": selected}


def test_match_prefers_exact_active_tab_title():
    a, b = _sess(["Alpha", "Beta"]), _sess(["Gamma", "Delta"], selected=1)
    used = set()
    assert _match_session_window("Delta — Mozilla Firefox", [a, b], used) is b


def test_match_falls_back_to_containment():
    """Firefox decorates titles with unread counts and dirty markers."""
    s = _sess(["Calendar | Teams"])
    assert _match_session_window("(1) Calendar | Teams — Mozilla Firefox", [s], set()) is s


def test_match_does_not_reuse_a_claimed_session():
    """Two windows showing the same title must not collapse onto one session."""
    a, b = _sess(["Same"]), _sess(["Same"])
    used = set()
    first = _match_session_window("Same — Mozilla Firefox", [a, b], used)
    second = _match_session_window("Same — Mozilla Firefox", [a, b], used)
    assert first is not second


def test_single_session_matches_even_on_stale_title():
    s = _sess(["Whatever the store says"])
    assert _match_session_window("A newer title — Mozilla Firefox", [s], set()) is s


# --- action dispatch --------------------------------------------------------

class _FakeShell:
    def __init__(self):
        self.calls = []

    def SendKeys(self, wid, keys):
        self.calls.append(("SendKeys", int(wid), str(keys)))

    def Focus(self, wid):
        self.calls.append(("Focus", int(wid)))

    def Close(self, wid):
        self.calls.append(("Close", int(wid)))


@pytest.fixture
def shell(monkeypatch):
    if not actions.HAS_DBUS:
        pytest.skip("python-dbus is required to reach the mocked extension call")
    fake = _FakeShell()
    monkeypatch.setattr(actions, "_shell_interface", lambda: fake)
    return fake


def test_focus_tab_sends_its_chord(shell):
    r = actions.execute_window_action("201#tab=1&keys=alt+2", "focus")
    assert r["ok"]
    assert shell.calls == [("SendKeys", 201, "ctrl+l,alt+2,escape")]


def test_tab_chord_is_shielded_from_the_focused_page(shell):
    """Teams (and Gmail, and Slack) bind Alt+N themselves and preventDefault it.

    Ctrl+L is reserved by Firefox, so parking focus in the address bar first is
    what keeps the chord from being eaten by whatever page happens to be open.
    """
    actions.execute_window_action("201#tab=9&keys=alt+8,ctrl+page_down", "focus")
    keys = shell.calls[0][2]
    assert keys.startswith("ctrl+l,")
    assert keys.endswith(",escape")


def test_close_tab_selects_then_closes(shell):
    """Ctrl+W closes whatever is focused, so the tab must be selected first."""
    r = actions.execute_window_action("201#tab=1&keys=alt+2", "close")
    assert r["ok"]
    assert shell.calls == [("SendKeys", 201, "ctrl+l,alt+2,escape,ctrl+w")]


def test_close_window_from_a_tab_target_closes_the_window(shell):
    r = actions.execute_window_action("201#tab=1&keys=alt+2", "close_window")
    assert r["ok"]
    assert shell.calls == [("Close", 201)]


def test_plain_window_actions_are_unchanged(shell):
    assert actions.execute_window_action("201", "focus")["ok"]
    assert actions.execute_window_action("201", "close")["ok"]
    assert shell.calls == [("Focus", 201), ("Close", 201)]


def test_close_tab_on_plain_window_uses_keystroke(shell):
    """Non-Firefox browsers still get a working close-tab under Wayland."""
    assert actions.execute_window_action("201", "close_tab")["ok"]
    assert shell.calls == [("SendKeys", 201, "ctrl+w")]


def test_malformed_window_id_is_rejected(shell):
    r = actions.execute_window_action("nonsense", "focus")
    assert not r["ok"]
    assert "Invalid window id" in r["message"]
    assert shell.calls == []


def test_unknown_tab_action_is_rejected(shell):
    r = actions.execute_window_action("201#tab=0&keys=alt+1", "wiggle")
    assert not r["ok"]
    assert shell.calls == []
