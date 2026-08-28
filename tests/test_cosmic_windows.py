"""COSMIC window control: the fallback used when the GNOME extension isn't there.

Real pywayland/Wayland IPC isn't reachable in a unit test, so these mock at
the same boundary tests/test_desktop_control.py's _FakeShell does for the
GNOME extension: a fake standing in for cosmic_windows._conn, exposing the
same attributes/methods vt/sources/cosmic_windows.py actually calls.
"""

import pytest

import vt.actions as actions
from vt.sources import cosmic_input, cosmic_windows, windows
from vt.sources import youtube_player


class _FakeToplevel:
    def __init__(self, identifier, title="", app_id="", state=frozenset(), handle="handle"):
        self.identifier = identifier
        self.title = title
        self.app_id = app_id
        self.state = set(state)
        self.cosmic_handle = handle


class _FakeManager:
    """Records the calls execute() makes, same shape as _FakeShell."""

    def __init__(self):
        self.calls = []

    def activate(self, handle, seat):
        self.calls.append(("activate", handle, seat))

    def close(self, handle):
        self.calls.append(("close", handle))

    def set_maximized(self, handle):
        self.calls.append(("set_maximized", handle))

    def unset_maximized(self, handle):
        self.calls.append(("unset_maximized", handle))

    def set_minimized(self, handle):
        self.calls.append(("set_minimized", handle))

    def unset_minimized(self, handle):
        self.calls.append(("unset_minimized", handle))


class _FakeVkbd:
    """Records the calls send_chord() makes, same shape as _FakeManager."""

    def __init__(self):
        self.calls = []

    def keymap(self, fmt, fd, size):
        self.calls.append(("keymap", fmt, size))

    def key(self, time_, key, state):
        self.calls.append(("key", key, state))

    def modifiers(self, depressed, latched, locked, group):
        self.calls.append(("modifiers", depressed, latched, locked, group))


class _FakeConnection:
    def __init__(self, toplevels=(), unavailable=False, keyboard_available=True):
        self.toplevels = {i: tl for i, tl in enumerate(toplevels)}
        self.manager = _FakeManager()
        self.seat = "seat"
        self._unavailable = unavailable
        self.refreshes = 0
        self._keyboard_available = keyboard_available
        self.vkbd = None

    def ensure_ready(self):
        if self._unavailable:
            raise cosmic_windows._NotCosmic("missing globals")

    def refresh(self):
        self.refreshes += 1

    def find(self, identifier):
        return next((tl for tl in self.toplevels.values() if tl.identifier == identifier), None)

    def ensure_keyboard(self):
        if not self._keyboard_available:
            raise cosmic_windows._NoVirtualKeyboard(
                "zwp_virtual_keyboard_manager_v1 not available on this compositor"
            )
        if self.vkbd is None:
            self.vkbd = _FakeVkbd()
        return self.vkbd


@pytest.fixture
def fake_conn(monkeypatch):
    conn = _FakeConnection()
    monkeypatch.setattr(cosmic_windows, "_conn", conn)
    monkeypatch.setattr(cosmic_windows, "HAS_PYWAYLAND", True)
    # send_chord() sleeps to let the compositor settle -- irrelevant and slow
    # in a test that never touches a real compositor.
    monkeypatch.setattr(cosmic_input.time, "sleep", lambda s: None)
    return conn


def test_no_pywayland_means_no_windows(monkeypatch):
    monkeypatch.setattr(cosmic_windows, "HAS_PYWAYLAND", False)
    assert cosmic_windows.list_windows() == []


def test_list_windows_maps_toplevels_to_the_shared_dict_shape(fake_conn):
    fake_conn.toplevels = {
        0: _FakeToplevel("abc", title="Terminal", app_id="com.system76.CosmicTerm"),
        1: _FakeToplevel(
            "def", title="A Video", app_id="firefox",
            state={cosmic_windows._MAXIMIZED, cosmic_windows._ACTIVATED},
        ),
    }
    result = cosmic_windows.list_windows()
    by_id = {w["id"]: w for w in result}

    assert by_id["cosmic:abc"]["title"] == "Terminal"
    assert by_id["cosmic:abc"]["wm_class"] == "com.system76.CosmicTerm"
    assert by_id["cosmic:abc"]["minimized"] is False
    assert by_id["cosmic:abc"]["maximized"] is False
    assert by_id["cosmic:abc"]["backend"] == "cosmic"

    assert by_id["cosmic:def"]["maximized"] is True
    assert by_id["cosmic:def"]["minimized"] is False


def test_a_toplevel_with_no_identifier_yet_is_skipped(fake_conn):
    """identifier arrives as its own event; a toplevel caught mid-burst has none yet."""
    fake_conn.toplevels = {0: _FakeToplevel(None, title="Not ready")}
    assert cosmic_windows.list_windows() == []


def test_list_windows_degrades_to_empty_when_not_cosmic(fake_conn):
    fake_conn._unavailable = True
    assert cosmic_windows.list_windows() == []


@pytest.mark.parametrize("action_id,method,message", [
    ("close", "close", "Window closed"),
    ("close_window", "close", "Window closed"),
    ("minimize", "set_minimized", "Window minimized"),
    ("unminimize", "unset_minimized", "Window restored"),
    ("maximize", "set_maximized", "Window maximized"),
    ("unmaximize", "unset_maximized", "Window unmaximized"),
])
def test_execute_dispatches_to_the_manager(fake_conn, action_id, method, message):
    fake_conn.toplevels = {0: _FakeToplevel("abc", handle="h1")}
    result = cosmic_windows.execute("abc", action_id)
    assert result == {"ok": True, "message": message}
    assert fake_conn.manager.calls == [(method, "h1")]


def test_focus_activates_with_the_seat(fake_conn):
    fake_conn.toplevels = {0: _FakeToplevel("abc", handle="h1")}
    result = cosmic_windows.execute("abc", "focus")
    assert result["ok"] is True
    assert fake_conn.manager.calls == [("activate", "h1", "seat")]


def test_execute_reports_a_closed_window(fake_conn):
    result = cosmic_windows.execute("nonexistent", "focus")
    assert result["ok"] is False
    assert "not found" in result["message"].lower()


def test_execute_reports_the_wrong_compositor(fake_conn):
    fake_conn._unavailable = True
    result = cosmic_windows.execute("abc", "focus")
    assert result["ok"] is False
    assert "not available" in result["message"].lower()


def test_execute_rejects_an_unknown_action(fake_conn):
    fake_conn.toplevels = {0: _FakeToplevel("abc", handle="h1")}
    result = cosmic_windows.execute("abc", "levitate")
    assert result["ok"] is False
    assert fake_conn.manager.calls == []


# --- cosmic_windows.py: send_keys() and its callers -------------------------

def test_send_keys_activates_then_types_through_the_virtual_keyboard(fake_conn):
    fake_conn.toplevels = {0: _FakeToplevel("abc", handle="h1")}
    result = cosmic_windows.send_keys("abc", "ctrl+w")
    assert result == {"ok": True, "message": ""}
    assert fake_conn.manager.calls == [("activate", "h1", "seat")]

    # _FakeConnection.ensure_keyboard() hands back a bare _FakeVkbd(), same as
    # the real one after keymap upload -- that upload step is its own unit
    # test in test_cosmic_input.py, not repeated here.
    ctrl = cosmic_input._MOD_BITS["ctrl"]
    w = cosmic_input._KEYCODES["w"]
    assert fake_conn.vkbd.calls == [
        ("modifiers", ctrl, 0, 0, 0),
        ("key", w, cosmic_input._KEY_PRESSED),
        ("key", w, cosmic_input._KEY_RELEASED),
        ("modifiers", 0, 0, 0, 0),
    ]


def test_send_keys_reports_a_closed_window(fake_conn):
    result = cosmic_windows.send_keys("nonexistent", "k")
    assert result["ok"] is False
    assert "not found" in result["message"].lower()


def test_send_keys_reports_no_virtual_keyboard(fake_conn):
    fake_conn.toplevels = {0: _FakeToplevel("abc", handle="h1")}
    fake_conn._keyboard_available = False
    result = cosmic_windows.send_keys("abc", "k")
    assert result["ok"] is False
    assert "not available" in result["message"].lower()


def test_send_keys_reports_an_unknown_key(fake_conn):
    fake_conn.toplevels = {0: _FakeToplevel("abc", handle="h1")}
    result = cosmic_windows.send_keys("abc", "ctrl+z")
    assert result["ok"] is False


def test_execute_routes_a_tab_id_to_send_keys(fake_conn):
    """id shape matches windows.py's _tab_targets(): "<wid>#tab=<n>&keys=<chord>"."""
    fake_conn.toplevels = {0: _FakeToplevel("abc", handle="h1")}
    result = cosmic_windows.execute("abc#tab=2&keys=alt+3", "focus")
    assert result == {"ok": True, "message": "Switched to tab 3"}
    assert fake_conn.manager.calls == [("activate", "h1", "seat")]
    assert ("key", cosmic_input._KEYCODES["3"], cosmic_input._KEY_PRESSED) in fake_conn.vkbd.calls


def test_execute_routes_a_tab_close_to_send_keys(fake_conn):
    fake_conn.toplevels = {0: _FakeToplevel("abc", handle="h1")}
    result = cosmic_windows.execute("abc#tab=0&keys=alt+1", "close_tab")
    assert result == {"ok": True, "message": "Closed tab 1"}
    assert ("key", cosmic_input._KEYCODES["w"], cosmic_input._KEY_PRESSED) in fake_conn.vkbd.calls


def test_execute_close_tab_on_an_unexpanded_window_types_ctrl_w(fake_conn):
    fake_conn.toplevels = {0: _FakeToplevel("abc", handle="h1")}
    result = cosmic_windows.execute("abc", "close_tab")
    assert result == {"ok": True, "message": "Tab closed"}
    assert fake_conn.manager.calls == [("activate", "h1", "seat")]
    assert ("key", cosmic_input._KEYCODES["w"], cosmic_input._KEY_PRESSED) in fake_conn.vkbd.calls


# --- windows.py: the COSMIC fallback path -----------------------------------

def _cosmic_window(identifier, title, app_id, minimized=False, maximized=False):
    return {
        "id": f"cosmic:{identifier}",
        "title": title,
        "wm_class": app_id,
        "minimized": minimized,
        "maximized": maximized,
        "backend": "cosmic",
    }


def test_gnome_absent_falls_back_to_cosmic(monkeypatch):
    monkeypatch.setattr(windows, "dbus", None)
    monkeypatch.setattr(
        cosmic_windows, "list_windows",
        lambda: [_cosmic_window("abc", "Terminal", "com.system76.CosmicTerm")],
    )
    result = windows.list_windows()
    assert result == [_cosmic_window("abc", "Terminal", "com.system76.CosmicTerm")]


def test_cosmic_multi_tab_firefox_window_now_expands_into_tabs(monkeypatch):
    """send_keys() gives tab-switching somewhere to go -- see cosmic_windows.py."""
    monkeypatch.setattr(windows, "dbus", None)
    monkeypatch.setattr(
        cosmic_windows, "list_windows",
        lambda: [_cosmic_window("abc", "Example — Mozilla Firefox", "firefox", maximized=True)],
    )
    monkeypatch.setattr(
        windows, "get_firefox_windows",
        lambda: [{
            "tabs": [{"title": "Example", "url": "https://a"}, {"title": "Other", "url": "https://b"}],
            "selected": 0,
        }],
    )
    targets = windows.get_window_targets()
    assert len(targets) == 2
    assert targets[0].id == "window:cosmic:abc#tab=0&keys=alt+1"
    assert [a.id for a in targets[0].actions] == ["focus", "close"]


def test_cosmic_single_tab_browser_window_gets_close_tab_and_close_window(monkeypatch):
    """No session data to expand into tabs, but the frame-level tab actions

    (close_tab needs send_keys(); close_window is a plain protocol request)
    are both available now.
    """
    monkeypatch.setattr(windows, "dbus", None)
    monkeypatch.setattr(
        cosmic_windows, "list_windows",
        lambda: [_cosmic_window("abc", "Example — Mozilla Firefox", "firefox", maximized=True)],
    )
    monkeypatch.setattr(windows, "get_firefox_windows", lambda: [])
    targets = windows.get_window_targets()
    assert len(targets) == 1
    action_ids = [a.id for a in targets[0].actions]
    assert "close_tab" in action_ids
    assert "close_window" in action_ids
    assert "unmaximize" in action_ids  # real state, not the both-directions guess


# --- actions.py: routing a "cosmic:" id to this module ----------------------

def test_execute_window_action_routes_cosmic_ids(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cosmic_windows, "execute",
        lambda identifier, action_id: calls.append((identifier, action_id)) or {"ok": True, "message": "ok"},
    )
    result = actions.execute_window_action("cosmic:abc", "focus")
    assert result == {"ok": True, "message": "ok"}
    assert calls == [("abc", "focus")]


# --- youtube_player.py: cosmic_windows.py is now a valid delivery route ----

def test_youtube_tab_lookup_now_includes_cosmic_windows(monkeypatch):
    monkeypatch.setattr(
        youtube_player, "list_windows",
        lambda: [_cosmic_window("abc", "Some Video — YouTube", "firefox")],
    )
    assert youtube_player.find_youtube_tab() == {
        "wid": "cosmic:abc",
        "chord": "",
        "title": "Some Video — YouTube",
    }


def test_youtube_send_keys_routes_cosmic_wid_to_cosmic_windows(monkeypatch):
    calls = []
    monkeypatch.setattr(
        cosmic_windows, "send_keys",
        lambda identifier, chord: calls.append((identifier, chord)) or {"ok": True, "message": ""},
    )
    entry = {"wid": "cosmic:abc", "chord": "", "title": "Video"}
    result = youtube_player._send_keys_to(entry, "f")
    assert result == {"ok": True, "message": ""}
    assert calls == [("abc", "f")]
