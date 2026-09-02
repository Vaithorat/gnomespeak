"""Tests for the desktop-control sources: Steam, streaming, workspaces, system.

Everything here is the pure logic -- manifest parsing, config merging, message
formatting, bounds checks -- so none of it needs a live D-Bus session, a
running Steam client, or a machine with a battery.
"""

import pytest

import vt.actions as actions
from vt.sources import network, steam, streaming, system, workspaces


# --- Steam library parsing --------------------------------------------------

def _write_manifest(directory, appid, name, state=4):
    (directory / f"appmanifest_{appid}.acf").write_text(
        '"AppState"\n{\n'
        f'\t"appid"\t\t"{appid}"\n'
        f'\t"name"\t\t"{name}"\n'
        f'\t"StateFlags"\t\t"{state}"\n'
        "}\n"
    )


@pytest.fixture
def steam_root(tmp_path, monkeypatch):
    """A Steam install with one library, wired into the module's root lookup."""
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    monkeypatch.setattr(steam, "_STEAM_ROOTS", (str(root),))
    steam.reset_cache()
    yield root
    steam.reset_cache()


def test_installed_games_read_from_manifests(steam_root):
    """The manifests are the library; Steam writes no .desktop file per game."""
    _write_manifest(steam_root / "steamapps", "1245620", "ELDEN RING")
    _write_manifest(steam_root / "steamapps", "570", "Dota 2")

    games = steam.installed_games()
    assert [g["name"] for g in games] == ["Dota 2", "ELDEN RING"]
    assert games[0]["id"] == "570"


def test_partially_downloaded_games_are_skipped(steam_root):
    """StateFlags without the fully-installed bit means it will not launch."""
    _write_manifest(steam_root / "steamapps", "570", "Dota 2", state=1026)
    assert steam.installed_games() == []


def test_runtimes_are_not_games(steam_root):
    """Proton and the Linux runtimes install like games and are not games."""
    _write_manifest(steam_root / "steamapps", "1493710", "Proton Experimental")
    _write_manifest(steam_root / "steamapps", "1391110", "Steam Linux Runtime 3.0")
    _write_manifest(steam_root / "steamapps", "570", "Dota 2")

    assert [g["name"] for g in steam.installed_games()] == ["Dota 2"]


def test_games_on_a_second_drive_are_found(steam_root, tmp_path):
    """libraryfolders.vdf is the only record that a second library exists."""
    other = tmp_path / "Games"
    (other / "steamapps").mkdir(parents=True)
    _write_manifest(other / "steamapps", "570", "Dota 2")
    (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n'
        f'\t\t"path"\t\t"{other}"\n'
        "\t}\n}\n"
    )

    assert [g["name"] for g in steam.installed_games()] == ["Dota 2"]


def test_steam_targets_are_searchable(steam_root):
    _write_manifest(steam_root / "steamapps", "1245620", "ELDEN RING")
    _write_manifest(steam_root / "steamapps", "570", "Dota 2")

    targets = steam.get_steam_targets("elden")
    assert [t.title for t in targets] == ["ELDEN RING"]
    assert targets[0].id == "steam:1245620"
    assert [a.id for a in targets[0].actions] == ["launch"]


def test_steam_launch_rejects_a_non_numeric_appid():
    """The app id lands in a steam:// URL, so it may not be arbitrary text."""
    result = steam.launch_game("570; rm -rf /")
    assert result["ok"] is False
    assert "Invalid Steam app id" in result["message"]


def test_steam_games_appear_in_the_installed_app_search(steam_root, monkeypatch):
    """From the phone, starting a game and starting an app are one gesture."""
    from vt.sources import apps

    _write_manifest(steam_root / "steamapps", "1245620", "ELDEN RING")
    monkeypatch.setattr(apps, "get_installed_index", dict)

    titles = [t.title for t in apps.get_installed_targets("elden")]
    assert "ELDEN RING" in titles


# --- Streaming shortcuts ----------------------------------------------------

@pytest.fixture
def no_streaming_config(monkeypatch, tmp_path):
    monkeypatch.setattr(streaming, "_config_path", lambda: tmp_path / "missing.toml")
    return tmp_path


def test_streaming_defaults_are_offered(no_streaming_config, monkeypatch):
    monkeypatch.setattr(streaming, "_find_app", lambda service: None)
    monkeypatch.setattr(streaming, "_find_binary", lambda service: "")

    targets = streaming.get_streaming_targets()
    ids = [t.id for t in targets]
    assert "streaming:netflix" in ids
    # With no app installed the row still works -- it says so, and opens the web.
    netflix = next(t for t in targets if t.id == "streaming:netflix")
    assert netflix.subtitle == "browser"
    assert [a.id for a in netflix.actions] == ["launch"]


def test_installed_app_is_preferred_over_the_browser(no_streaming_config, monkeypatch):
    monkeypatch.setattr(
        streaming, "_find_app",
        lambda service: {"name": "Spotify"} if service["id"] == "spotify" else None,
    )
    monkeypatch.setattr(streaming, "_find_binary", lambda service: "")

    targets = {t.id: t for t in streaming.get_streaming_targets()}
    assert targets["streaming:spotify"].subtitle == "app"
    assert targets["streaming:netflix"].subtitle == "browser"


def test_streaming_config_overrides_and_disables(monkeypatch, tmp_path):
    """A regional URL should not mean redeclaring the whole service."""
    config = tmp_path / "streaming.toml"
    config.write_text(
        '[[service]]\nid = "netflix"\nurl = "https://www.netflix.com/in/"\n\n'
        '[[service]]\nid = "twitch"\nenabled = false\n\n'
        '[[service]]\nid = "jellyfin"\nlabel = "Jellyfin"\n'
        'url = "http://nas.local:8096"\napp = "jellyfinmediaplayer"\n'
    )
    monkeypatch.setattr(streaming, "_config_path", lambda: config)

    services = {s["id"]: s for s in streaming.services()}
    assert services["netflix"]["url"] == "https://www.netflix.com/in/"
    assert services["netflix"]["label"] == "Netflix"      # untouched by the override
    assert "twitch" not in services
    assert services["jellyfin"]["app"] == ["jellyfinmediaplayer"]


def test_streaming_falls_back_to_the_url(no_streaming_config, monkeypatch):
    monkeypatch.setattr(streaming, "_find_app", lambda service: None)
    monkeypatch.setattr(streaming, "_find_binary", lambda service: "")

    opened = []
    monkeypatch.setattr(streaming, "_open_url",
                        lambda url, label: opened.append(url) or {"ok": True, "message": label})

    assert streaming.execute("netflix", "launch")["ok"] is True
    assert opened == ["https://www.netflix.com"]


def test_streaming_rejects_an_unknown_service(no_streaming_config):
    result = streaming.execute("nosuchservice", "launch")
    assert result["ok"] is False
    assert "nosuchservice" in result["message"]


# --- Workspaces -------------------------------------------------------------

def test_a_single_workspace_offers_nothing(monkeypatch):
    """A row that cannot change anything is noise on a phone screen."""
    monkeypatch.setattr(workspaces, "workspace_info", lambda: {"count": 1, "active": 0})
    assert workspaces.get_workspace_targets() == []


def test_the_active_workspace_has_no_switch_button(monkeypatch):
    """Switching to where you already are is a no-op that would report success."""
    monkeypatch.setattr(workspaces, "workspace_info", lambda: {"count": 3, "active": 1})

    targets = workspaces.get_workspace_targets()
    assert [t.title for t in targets] == ["Workspace 1", "Workspace 2", "Workspace 3"]
    assert targets[1].status == "active"
    assert targets[1].actions == []
    assert [a.id for a in targets[0].actions] == ["switch"]


def test_switching_past_the_last_workspace_is_refused(monkeypatch):
    if not actions.HAS_DBUS:
        pytest.skip("python-dbus is required to reach the bounds check")
    monkeypatch.setattr(workspaces, "workspace_info", lambda: {"count": 2, "active": 0})
    result = workspaces.execute("5", "switch")
    assert result["ok"] is False
    assert "there are 2" in result["message"]


def test_workspace_switch_calls_the_extension(monkeypatch):
    if not actions.HAS_DBUS:
        pytest.skip("python-dbus is required to reach the mocked extension call")
    monkeypatch.setattr(workspaces, "workspace_info", lambda: {"count": 3, "active": 0})

    calls = []

    class FakeInterface:
        def SwitchWorkspace(self, index):
            calls.append(int(index))

    monkeypatch.setattr(workspaces, "shell_interface", lambda: FakeInterface())

    result = workspaces.execute("2", "switch")
    assert result["ok"] is True
    assert result["message"] == "Switched to workspace 3"
    assert calls == [2]


def test_workspace_without_the_extension_says_so(monkeypatch):
    if not actions.HAS_DBUS:
        pytest.skip("python-dbus is required to reach the extension-absent message")
    monkeypatch.setattr(workspaces, "workspace_info", dict)
    result = workspaces.execute("1", "switch")
    assert result["ok"] is False
    assert "extension" in result["message"]


# --- System: battery, brightness, do not disturb ----------------------------

def _battery(monkeypatch, **props):
    monkeypatch.setattr(system, "_battery_properties", lambda: props)


def test_battery_reports_charge_and_time_left(monkeypatch):
    _battery(monkeypatch, IsPresent=1, Percentage=62.4, State=2, TimeToEmpty=8100)
    assert system.battery_summary() == "62% · discharging · 2h 15m left"


def test_a_full_battery_has_no_countdown(monkeypatch):
    """UPower still reports a TimeToEmpty when full, and it is nonsense.

    This machine reports 8391600 seconds on a full battery, which rendered as
    "2331h left" next to the word "full".
    """
    _battery(monkeypatch, IsPresent=1, Percentage=100.0, State=4, TimeToEmpty=8391600)
    assert system.battery_summary() == "100% · full"


def test_charging_counts_up_to_full(monkeypatch):
    _battery(monkeypatch, IsPresent=1, Percentage=40.0, State=1, TimeToFull=3600, TimeToEmpty=999)
    assert system.battery_summary() == "40% · charging · 1h to full"


def test_a_machine_without_a_battery_reports_nothing(monkeypatch):
    _battery(monkeypatch, IsPresent=0)
    assert system.battery_summary() == ""


def test_do_not_disturb_offers_the_half_that_applies(monkeypatch):
    monkeypatch.setattr(system, "battery_summary", lambda: "")
    monkeypatch.setattr(system, "_brightness", lambda: -1)
    monkeypatch.setattr(system, "_night_light_on", lambda: None)
    monkeypatch.setattr(system, "_theme_is_dark", lambda: None)

    monkeypatch.setattr(system, "_banners_shown", lambda: True)
    targets = {t.id: t for t in system.get_system_targets()}
    assert [a.id for a in targets["system:notifications"].actions] == ["dnd_on"]

    monkeypatch.setattr(system, "_banners_shown", lambda: False)
    targets = {t.id: t for t in system.get_system_targets()}
    assert [a.id for a in targets["system:notifications"].actions] == ["dnd_off"]


def test_no_backlight_means_no_display_row(monkeypatch):
    """A desktop monitor has no controllable backlight; a dead slider is worse."""
    monkeypatch.setattr(system, "battery_summary", lambda: "")
    monkeypatch.setattr(system, "_banners_shown", lambda: None)
    monkeypatch.setattr(system, "_brightness", lambda: -1)
    monkeypatch.setattr(system, "_night_light_on", lambda: None)
    monkeypatch.setattr(system, "_theme_is_dark", lambda: None)

    assert [t.id for t in system.get_system_targets()] == ["system:power"]


def test_shutdown_and_restart_require_confirmation(monkeypatch):
    """A mis-heard word must not be able to take the machine down."""
    monkeypatch.setattr(system, "battery_summary", lambda: "")
    monkeypatch.setattr(system, "_brightness", lambda: -1)
    monkeypatch.setattr(system, "_banners_shown", lambda: None)
    monkeypatch.setattr(system, "_night_light_on", lambda: None)
    monkeypatch.setattr(system, "_theme_is_dark", lambda: None)

    power = system.get_system_targets()[0]
    kinds = {a.id: a.kind for a in power.actions}
    assert kinds["restart"] == "confirm"
    assert kinds["shutdown"] == "confirm"
    assert kinds["lock"] == "button"


def test_brightness_slider_needs_a_value(monkeypatch):
    result = system.execute("display", "brightness", None)
    assert result["ok"] is False
    assert "value" in result["message"]


def test_unknown_system_target_is_named():
    result = system.execute("nosuchthing", "lock", None)
    assert result["ok"] is False
    assert "nosuchthing" in result["message"]


# --- System: night light -----------------------------------------------------

def test_night_light_row_appears_without_a_backlight(monkeypatch):
    """A desktop monitor has no backlight, but can still have night light."""
    monkeypatch.setattr(system, "battery_summary", lambda: "")
    monkeypatch.setattr(system, "_banners_shown", lambda: None)
    monkeypatch.setattr(system, "_brightness", lambda: -1)
    monkeypatch.setattr(system, "_night_light_on", lambda: False)
    monkeypatch.setattr(system, "_theme_is_dark", lambda: None)

    targets = {t.id: t for t in system.get_system_targets()}
    display = targets["system:display"]
    assert [a.id for a in display.actions] == ["night_light_on"]
    assert display.status == ""


def test_night_light_action_flips_with_state(monkeypatch):
    monkeypatch.setattr(system, "battery_summary", lambda: "")
    monkeypatch.setattr(system, "_banners_shown", lambda: None)
    monkeypatch.setattr(system, "_brightness", lambda: -1)
    monkeypatch.setattr(system, "_theme_is_dark", lambda: None)

    monkeypatch.setattr(system, "_night_light_on", lambda: True)
    targets = {t.id: t for t in system.get_system_targets()}
    assert [a.id for a in targets["system:display"].actions] == ["night_light_off"]
    assert targets["system:display"].status == "night light"


# --- System: dark theme -------------------------------------------------------

def test_theme_row_offers_the_opposite_mode(monkeypatch):
    monkeypatch.setattr(system, "battery_summary", lambda: "")
    monkeypatch.setattr(system, "_banners_shown", lambda: None)
    monkeypatch.setattr(system, "_brightness", lambda: -1)
    monkeypatch.setattr(system, "_night_light_on", lambda: None)

    monkeypatch.setattr(system, "_theme_is_dark", lambda: True)
    targets = {t.id: t for t in system.get_system_targets()}
    assert [a.id for a in targets["system:display"].actions] == ["theme_light"]
    assert targets["system:display"].status == "dark"

    monkeypatch.setattr(system, "_theme_is_dark", lambda: False)
    targets = {t.id: t for t in system.get_system_targets()}
    assert [a.id for a in targets["system:display"].actions] == ["theme_dark"]
    assert targets["system:display"].status == "light"


def test_theme_execute_calls_gsettings(monkeypatch):
    calls = []
    monkeypatch.setattr(
        system.subprocess, "run",
        lambda argv, **kw: calls.append(argv) or type("R", (), {"returncode": 0, "stderr": ""})(),
    )
    result = system.execute("display", "theme_dark", None)
    assert result["ok"] is True
    assert calls[0] == ["gsettings", "set", system._THEME_SCHEMA,
                         system._THEME_KEY, system._THEME_DARK]

    result = system.execute("display", "theme_light", None)
    assert calls[1] == ["gsettings", "set", system._THEME_SCHEMA,
                         system._THEME_KEY, system._THEME_LIGHT]


def test_night_light_execute_calls_gsettings(monkeypatch):
    calls = []
    monkeypatch.setattr(
        system.subprocess, "run",
        lambda argv, **kw: calls.append(argv) or type("R", (), {"returncode": 0, "stderr": ""})(),
    )
    result = system.execute("display", "night_light_on", None)
    assert result["ok"] is True
    assert calls[0] == ["gsettings", "set", system._NIGHT_LIGHT_SCHEMA,
                         system._NIGHT_LIGHT_KEY, "true"]


# --- System: keep awake -------------------------------------------------------

class _FakeInhibitManager:
    def __init__(self):
        self.inhibited = False
        self.cookie = 42

    def Inhibit(self, app_id, xid, reason, flags, timeout=None):
        self.inhibited = True
        return self.cookie

    def Uninhibit(self, cookie, timeout=None):
        assert int(cookie) == self.cookie
        self.inhibited = False


@pytest.fixture
def fake_session_manager(monkeypatch):
    manager = _FakeInhibitManager()
    fake_dbus = type("FakeDbus", (), {
        "SessionBus": lambda: type("Bus", (), {
            "get_object": lambda self, *a, **k: object(),
        })(),
        "Interface": lambda obj, iface: manager,
        "UInt32": lambda v: v,
    })
    monkeypatch.setattr(system, "dbus", fake_dbus)
    monkeypatch.setattr(system, "_awake_cookie", None)
    yield manager
    monkeypatch.setattr(system, "_awake_cookie", None)


def test_keep_awake_inhibits_and_releases(fake_session_manager):
    result = system.execute("power", "awake_on", None)
    assert result["ok"] is True
    assert fake_session_manager.inhibited is True

    result = system.execute("power", "awake_off", None)
    assert result["ok"] is True
    assert fake_session_manager.inhibited is False


def test_keep_awake_without_dbus_reports_unavailable(monkeypatch):
    monkeypatch.setattr(system, "dbus", None)
    result = system.execute("power", "awake_on", None)
    assert result["ok"] is False
    assert "dbus" in result["message"]


# --- Dispatch ---------------------------------------------------------------

def test_new_kinds_reach_their_sources(monkeypatch):
    """execute_action routes by target kind; a missing branch is a dead button."""
    if not actions.HAS_DBUS:
        pytest.skip("python-dbus is required to reach the mocked extension call")
    monkeypatch.setattr(workspaces, "workspace_info", lambda: {"count": 2, "active": 0})

    seen = []

    class FakeInterface:
        def SwitchWorkspace(self, index):
            seen.append(("workspace", int(index)))

    monkeypatch.setattr(workspaces, "shell_interface", lambda: FakeInterface())
    monkeypatch.setattr(steam, "launch_game", lambda appid: seen.append(("steam", appid)) or {"ok": True, "message": ""})
    monkeypatch.setattr(streaming, "execute", lambda sid, aid: seen.append(("streaming", sid)) or {"ok": True, "message": ""})

    assert actions.execute_action("workspace:1", "switch")["ok"] is True
    assert actions.execute_action("steam:570", "launch")["ok"] is True
    assert actions.execute_action("streaming:netflix", "launch")["ok"] is True

    assert seen == [("workspace", 1), ("steam", "570"), ("streaming", "netflix")]


def test_system_audio_still_routes_to_audio(monkeypatch):
    """system: gained siblings; audio must not fall through to the new branch."""
    called = []
    monkeypatch.setattr(actions, "execute_audio_action",
                        lambda node, aid, value: called.append((node, aid)) or {"ok": True, "message": ""})

    assert actions.execute_action("system:audio", "mute")["ok"] is True
    assert called == [("@DEFAULT_AUDIO_SINK@", "mute")]

    assert actions.execute_action("system:mic", "mute")["ok"] is True
    assert called[-1] == ("@DEFAULT_AUDIO_SOURCE@", "mute")


def test_system_wifi_routes_to_network(monkeypatch):
    called = []
    monkeypatch.setattr(network, "execute",
                        lambda spec, aid: called.append((spec, aid)) or {"ok": True, "message": ""})

    assert actions.execute_action("system:wifi", "wifi_off")["ok"] is True
    assert called == [("wifi", "wifi_off")]


def test_unknown_steam_action_is_refused():
    result = actions.execute_steam_action("570", "quit")
    assert result["ok"] is False
    assert "Unknown Steam action" in result["message"]


# --- Window state and workspace moves ---------------------------------------

class _FakeShell:
    """Records the extension calls a window action makes."""

    def __init__(self, missing=()):
        self.calls = []
        self.missing = set(missing)

    def _record(self, name, *args):
        if name in self.missing:
            raise _unknown_method(name)
        self.calls.append((name, *[int(a) for a in args]))

    def Minimize(self, wid):
        self._record("Minimize", wid)

    def Unminimize(self, wid):
        self._record("Unminimize", wid)

    def Maximize(self, wid):
        self._record("Maximize", wid)

    def Unmaximize(self, wid):
        self._record("Unmaximize", wid)

    def MoveToWorkspace(self, wid, index):
        self._record("MoveToWorkspace", wid, index)


def _unknown_method(name):
    import dbus
    return dbus.DBusException(
        f"no {name}", name="org.freedesktop.DBus.Error.UnknownMethod"
    )


@pytest.fixture
def shell(monkeypatch):
    if not actions.HAS_DBUS:
        pytest.skip("python-dbus is required to reach the mocked extension call")
    fake = _FakeShell()
    monkeypatch.setattr(actions, "_shell_interface", lambda: fake)
    return fake


@pytest.mark.parametrize("action_id,method,message", [
    ("minimize", "Minimize", "Window minimized"),
    ("unminimize", "Unminimize", "Window restored"),
    ("maximize", "Maximize", "Window maximized"),
    ("unmaximize", "Unmaximize", "Window unmaximized"),
])
def test_window_state_actions_call_the_extension(shell, action_id, method, message):
    result = actions.execute_window_action("42", action_id)
    assert result["ok"] is True
    assert result["message"] == message
    assert shell.calls == [(method, 42)]


def test_move_to_workspace_carries_its_index(shell):
    """The workspace travels in the action id, so the button stays a plain button."""
    result = actions.execute_window_action("42", "move_ws_2")
    assert result["ok"] is True
    assert result["message"] == "Moved to workspace 3"
    assert shell.calls == [("MoveToWorkspace", 42, 2)]


def test_malformed_move_action_is_refused(shell):
    result = actions.execute_window_action("42", "move_ws_left")
    assert result["ok"] is False
    assert "Invalid workspace action" in result["message"]
    assert shell.calls == []


def test_an_older_extension_is_told_apart_from_a_broken_one(monkeypatch):
    """An extension that answers the bus but not the method is merely stale.

    Reporting that as a generic D-Bus error sends people to reinstall something
    that is already installed, instead of reloading what they just updated.
    """
    if not actions.HAS_DBUS:
        pytest.skip("python-dbus is required to reach the mocked extension call")
    monkeypatch.setattr(actions, "_shell_interface",
                        lambda: _FakeShell(missing={"Minimize"}))

    result = actions.execute_window_action("42", "minimize")
    assert result["ok"] is False
    assert "install-extension" in result["message"]
    assert "Minimize" in result["message"]


# --- Network: Wi-Fi radio -----------------------------------------------------

def test_no_networkmanager_means_no_wifi_row(monkeypatch):
    monkeypatch.setattr(network, "_properties", lambda: None)
    assert network.get_network_targets() == []


def test_wifi_off_shows_a_turn_on_action(monkeypatch):
    monkeypatch.setattr(network, "_properties", lambda: {"WirelessEnabled": False})
    targets = network.get_network_targets()
    assert [a.id for a in targets[0].actions] == ["wifi_on"]
    assert targets[0].status == "off"


def test_wifi_on_without_connectivity_is_not_connected(monkeypatch):
    monkeypatch.setattr(network, "_properties",
                        lambda: {"WirelessEnabled": True, "Connectivity": 2})
    targets = network.get_network_targets()
    assert [a.id for a in targets[0].actions] == ["wifi_off"]
    assert targets[0].status == "on"


def test_wifi_full_connectivity_is_reported_connected(monkeypatch):
    monkeypatch.setattr(network, "_properties",
                        lambda: {"WirelessEnabled": True, "Connectivity": 4})
    targets = network.get_network_targets()
    assert targets[0].status == "connected"


class _FakeNMProps:
    def __init__(self):
        self.calls = []

    def Set(self, iface, key, value, timeout=None):
        self.calls.append((iface, key, bool(value)))


@pytest.fixture
def fake_nm(monkeypatch):
    props = _FakeNMProps()
    fake_dbus = type("FakeDbus", (), {
        "SystemBus": lambda: type("Bus", (), {
            "get_object": lambda self, *a, **k: object(),
        })(),
        "Interface": lambda obj, iface: props,
        "Boolean": lambda v: v,
    })
    monkeypatch.setattr(network, "dbus", fake_dbus)
    return props


def test_wifi_toggle_sets_the_networkmanager_property(fake_nm):
    result = network.execute("wifi", "wifi_off")
    assert result["ok"] is True
    assert fake_nm.calls == [(network.NM_IFACE, "WirelessEnabled", False)]


def test_wifi_without_dbus_reports_unavailable(monkeypatch):
    monkeypatch.setattr(network, "dbus", None)
    result = network.execute("wifi", "wifi_on")
    assert result["ok"] is False
    assert "dbus" in result["message"]


def test_unknown_network_action_is_named(fake_nm):
    result = network.execute("wifi", "reboot")
    assert result["ok"] is False
    assert "reboot" in result["message"]
