"""Tests for the HTTP server: auth, action dispatch, and injection regressions."""


import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from vt.actions import execute_app_action, match_window, shell_error
from vt.server import VoiceTalkServer


def _make_app(server: VoiceTalkServer) -> web.Application:
    app = web.Application()
    app.router.add_get("/", server.handle_root)
    app.router.add_get("/api/state", server.handle_api_state)
    app.router.add_get("/api/apps", server.handle_api_apps)
    app.router.add_post("/api/do", server.handle_api_do)
    return app


@pytest.fixture
async def client():
    server = VoiceTalkServer("127.0.0.1", 0, token="test-token")
    async with TestClient(TestServer(_make_app(server))) as c:
        c.vt = server
        yield c


# --- auth -------------------------------------------------------------------

async def test_state_requires_token(client):
    resp = await client.get("/api/state")
    assert resp.status == 401


async def test_state_rejects_wrong_token(client):
    resp = await client.get("/api/state", headers={"X-VT-Token": "wrong"})
    assert resp.status == 401


async def test_state_accepts_token(client):
    resp = await client.get("/api/state", headers={"X-VT-Token": "test-token"})
    assert resp.status == 200
    assert "targets" in await resp.json()


async def test_do_requires_token(client):
    resp = await client.post("/api/do", json={"target": "system:audio", "action": "mute"})
    assert resp.status == 401


async def test_no_token_mode_allows_everything():
    server = VoiceTalkServer("127.0.0.1", 0, token="")
    assert server.token == ""
    async with TestClient(TestServer(_make_app(server))) as c:
        assert (await c.get("/api/state")).status == 200


async def test_apps_requires_token(client):
    resp = await client.get("/api/apps")
    assert resp.status == 401


# --- installed apps ---------------------------------------------------------

async def test_apps_lists_installed_applications(client, monkeypatch):
    from vt.model import Action, Target

    fake = [
        Target(id="launcher:firefox", kind="launcher", title="Firefox",
               subtitle="Web Browser", actions=[Action(id="launch", label="Launch")]),
    ]
    monkeypatch.setattr("vt.server.get_installed_targets", lambda q="": fake)

    resp = await client.get("/api/apps", headers={"X-VT-Token": "test-token"})
    assert resp.status == 200
    body = await resp.json()
    assert body["apps"][0]["id"] == "launcher:firefox"
    assert body["apps"][0]["actions"][0]["id"] == "launch"


async def test_apps_passes_the_query_through(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "vt.server.get_installed_targets", lambda q="": seen.update(q=q) or []
    )
    await client.get("/api/apps", params={"q": "brow ser"},
                     headers={"X-VT-Token": "test-token"})
    assert seen["q"] == "brow ser"


async def test_installed_apps_stay_out_of_the_snapshot(client):
    """They are hundreds of rows that never move; /api/state polls at 1 Hz."""
    resp = await client.get("/api/state", headers={"X-VT-Token": "test-token"})
    kinds = {t["kind"] for t in (await resp.json())["targets"]}
    assert "launcher" not in kinds


# --- request validation -----------------------------------------------------

async def test_do_rejects_bad_json(client):
    resp = await client.post(
        "/api/do", data="not json", headers={"X-VT-Token": "test-token"}
    )
    assert resp.status == 400


async def test_do_requires_target_and_action(client):
    resp = await client.post(
        "/api/do", json={"target": "system:audio"}, headers={"X-VT-Token": "test-token"}
    )
    assert resp.status == 400


async def test_do_rejects_unknown_kind(client):
    resp = await client.post(
        "/api/do",
        json={"target": "bogus:thing", "action": "run"},
        headers={"X-VT-Token": "test-token"},
    )
    body = await resp.json()
    assert body["ok"] is False
    assert "Unknown target kind" in body["message"]


async def test_do_rejects_target_without_kind(client):
    resp = await client.post(
        "/api/do",
        json={"target": "nokind", "action": "run"},
        headers={"X-VT-Token": "test-token"},
    )
    assert (await resp.json())["ok"] is False


# --- reflected-XSS regression (fix 1) --------------------------------------

async def test_token_page_does_not_reflect_the_query(client):
    """?t= must never be interpolated into the page.

    "?t=');alert(1)//" used to close the JS string and run attacker script on
    this origin, where the API token lives in localStorage.
    """
    payload = "');alert(document.domain);//"
    resp = await client.get("/", params={"t": payload})
    body = await resp.text()
    assert resp.status == 200
    assert "alert(document.domain)" not in body
    assert payload not in body
    assert "localStorage.setItem" in body  # still the token-capture page


async def test_token_page_has_no_closing_script_injection(client):
    resp = await client.get("/", params={"t": "</script><img src=x onerror=alert(1)>"})
    body = await resp.text()
    assert "<img" not in body
    assert body.count("</script>") == 1


# --- app quit no longer needs D-Bus (fix 3) --------------------------------

def test_quit_does_not_require_dbus(monkeypatch):
    """pkill needs no D-Bus, so a missing python-dbus must not block quit."""
    monkeypatch.setattr("vt.actions.HAS_DBUS", False)
    calls = []

    class Result:
        returncode = 0

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return Result()

    monkeypatch.setattr("vt.actions.subprocess.run", fake_run)
    result = execute_app_action("firefox", "quit")

    assert result["ok"] is True
    assert "not importable" not in result["message"]
    assert calls, "pkill was never invoked"


def test_quit_matches_the_executable_exactly(monkeypatch):
    """-x -U, not -f: matching the whole command line killed bystanders."""
    seen = {}

    class Result:
        returncode = 0

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        return Result()

    monkeypatch.setattr("vt.actions.subprocess.run", fake_run)
    execute_app_action("code", "quit")

    assert "-f" not in seen["argv"]
    assert "-x" in seen["argv"]
    assert "-U" in seen["argv"]
    assert seen["argv"][-1] == "code"


def test_quit_reports_when_nothing_matched(monkeypatch):
    class Result:
        returncode = 1  # pkill: no process matched

    monkeypatch.setattr("vt.actions.subprocess.run", lambda argv, **kw: Result())
    result = execute_app_action("ghost", "quit")
    assert result["ok"] is False
    assert "No running process" in result["message"]


# --- extension error reporting (fix from the focus bug) --------------------

class _FakeDBusError(Exception):
    def __init__(self, name, message=""):
        super().__init__(message or name)
        self._name = name

    def get_dbus_name(self):
        return self._name


def test_missing_extension_reads_as_unavailable():
    e = _FakeDBusError("org.freedesktop.DBus.Error.ServiceUnknown")
    assert shell_error(e) == "GNOME extension not available"


def test_extension_js_error_is_surfaced_not_hidden():
    """A live extension throwing must not read as 'not installed'."""
    e = _FakeDBusError(
        "org.gnome.gjs.JSError.TypeError",
        "workspace.get_active_window is not a function",
    )
    msg = shell_error(e)
    assert "not available" not in msg
    assert "get_active_window" in msg


# --- window matching --------------------------------------------------------

def test_match_window_prefers_wm_class_over_title():
    windows = [
        {"id": 1, "title": "firefox notes", "wm_class": "Gedit"},
        {"id": 2, "title": "GitHub - Mozilla Firefox", "wm_class": "firefox"},
    ]
    assert match_window(windows, "firefox")["id"] == 2


def test_match_window_accepts_reverse_dns_class():
    windows = [{"id": 7, "title": "Files", "wm_class": "org.gnome.Nautilus"}]
    assert match_window(windows, "nautilus")["id"] == 7


def test_match_window_returns_none_when_absent():
    assert match_window([{"id": 1, "title": "x", "wm_class": "y"}], "firefox") is None
