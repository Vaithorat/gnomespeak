"""Tests for the HTTP server: auth, action dispatch, and injection regressions."""


import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from vt.actions import execute_app_action, match_window, shell_error
from vt.server import VoiceTalkServer


def make_server(tmp_path, **kwargs) -> VoiceTalkServer:
    """A server whose credential files live under tmp_path.

    Without this every test would read -- and pairing tests would write -- the
    developer's real ~/.config/gnomespeak/devices.json.
    """
    kwargs.setdefault("token", "test-token")
    return VoiceTalkServer(
        "127.0.0.1", 0,
        devices_path=tmp_path / "devices.json",
        audit_path=tmp_path / "audit.log",
        codes_path=tmp_path / "pairing.json",
        **kwargs,
    )


@pytest.fixture
async def client(tmp_path):
    server = make_server(tmp_path)
    async with TestClient(TestServer(server.make_app())) as c:
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


async def test_no_token_mode_allows_everything(tmp_path):
    server = make_server(tmp_path, token="")
    assert server.token == ""
    async with TestClient(TestServer(server.make_app())) as c:
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

@pytest.fixture
def installed(monkeypatch):
    """Pin the installed-app index so quit tests do not read the real machine.

    execute_app_action now resolves the app name against this index, so without
    the stub these tests would pass or fail depending on whether the developer
    happens to have Firefox or VS Code installed.
    """

    def use(*binaries: str):
        index = {b: {"binary": b, "name": b} for b in binaries}
        monkeypatch.setattr("vt.sources.apps.get_binary_index", lambda: index)

    return use


def test_quit_does_not_require_dbus(monkeypatch, installed):
    """pkill needs no D-Bus, so a missing python-dbus must not block quit."""
    installed("firefox")
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


def test_quit_matches_the_executable_exactly(monkeypatch, installed):
    """-x -U, not -f: matching the whole command line killed bystanders."""
    installed("code")
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


def test_quit_reports_when_nothing_matched(monkeypatch, installed):
    class Result:
        returncode = 1  # pkill: no process matched

    installed("ghost")  # installed, but not currently running
    monkeypatch.setattr("vt.actions.subprocess.run", lambda argv, **kw: Result())
    result = execute_app_action("ghost", "quit")
    assert result["ok"] is False
    assert "No running process" in result["message"]


def test_quit_rejects_names_that_are_pkill_options(monkeypatch, installed):
    """"app:-9" must never reach pkill.

    pkill would read the -9 as the signal and -U as the only match criterion
    left, so the argv that was meant to quit one app would SIGKILL every
    process this user owns. The name is resolved against the installed index
    first, which a leading-dash name can never be in.
    """
    installed("firefox")

    def fake_run(argv, **kwargs):
        raise AssertionError(f"pkill was invoked with {argv}")

    monkeypatch.setattr("vt.actions.subprocess.run", fake_run)
    for name in ("-9", "-f", "--signal=KILL"):
        result = execute_app_action(name, "quit")
        assert result["ok"] is False


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


# --- clipboard, input, files, notifications ---------------------------------
# Every one of these endpoints reaches the desktop through a source module, so
# the source is faked and what is tested here is the HTTP contract: who may
# call it, what it does with a malformed body, and what it writes to the audit
# log.

AUTH = {"X-VT-Token": "test-token"}


@pytest.mark.parametrize("method,path", [
    ("get", "/api/clipboard"),
    ("post", "/api/clipboard"),
    ("post", "/api/input"),
    ("get", "/api/notifications"),
    ("get", "/api/files"),
    ("post", "/api/upload"),
    ("get", "/api/files/anything.txt"),
    ("post", "/api/files/open"),
])
async def test_remote_endpoints_require_a_credential(client, method, path):
    resp = await getattr(client, method)(path)
    assert resp.status == 401


async def test_clipboard_read(client, monkeypatch):
    monkeypatch.setattr(
        "vt.sources.clipboard.read_text",
        lambda: {"ok": True, "text": "from the PC", "message": ""},
    )
    resp = await client.get("/api/clipboard", headers=AUTH)
    assert resp.status == 200
    assert (await resp.json())["text"] == "from the PC"


async def test_clipboard_write_is_audited(client, monkeypatch):
    written = {}

    def fake_write(text):
        written["text"] = text
        return {"ok": True, "message": "Copied"}

    monkeypatch.setattr("vt.sources.clipboard.write_text", fake_write)
    resp = await client.post("/api/clipboard", json={"text": "hello"}, headers=AUTH)
    assert resp.status == 200
    assert written["text"] == "hello"
    assert any(e["event"] == "clipboard.set" for e in client.vt.auth.audit.tail(5))


async def test_input_dispatches_to_the_source(client, monkeypatch):
    seen = {}

    def fake_execute(op, payload):
        seen["op"] = op
        seen["payload"] = payload
        return {"ok": True, "message": ""}

    monkeypatch.setattr("vt.sources.remote_input.execute", fake_execute)
    resp = await client.post("/api/input", json={"op": "move", "dx": 5, "dy": -3}, headers=AUTH)
    assert resp.status == 200
    assert seen["op"] == "move"
    assert seen["payload"]["dx"] == 5


async def test_pointer_moves_are_not_audited(client, monkeypatch):
    """20 Hz of pointer deltas would bury every other line in the log."""
    monkeypatch.setattr(
        "vt.sources.remote_input.execute", lambda op, payload: {"ok": True, "message": ""}
    )
    await client.post("/api/input", json={"op": "move", "dx": 1, "dy": 1}, headers=AUTH)
    await client.post("/api/input", json={"op": "keys", "keys": "ctrl+c"}, headers=AUTH)
    events = [e for e in client.vt.auth.audit.tail(10) if e["event"] == "input"]
    assert [e["op"] for e in events] == ["keys"]


async def test_input_rejects_a_non_object_body(client):
    resp = await client.post("/api/input", data="[]", headers=AUTH)
    assert resp.status == 400


def upload_form(filename: str, payload: bytes) -> FormData:
    """One multipart file field, the way a phone's <input type="file"> sends it."""
    form = FormData()
    form.add_field("file", payload, filename=filename, content_type="application/octet-stream")
    return form


@pytest.fixture
def transfers(tmp_path, monkeypatch):
    monkeypatch.setenv("GNOMESPEAK_TRANSFER_DIR", str(tmp_path / "incoming"))
    from vt.sources.transfer import transfer_dir

    return transfer_dir()


async def test_upload_then_list_then_download(client, transfers):
    resp = await client.post("/api/upload", data=upload_form("hello.txt", b"phone bytes"), headers=AUTH)
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] and body["name"] == "hello.txt"
    assert (transfers / "hello.txt").read_bytes() == b"phone bytes"

    listing = await (await client.get("/api/files", headers=AUTH)).json()
    assert [f["name"] for f in listing["files"]] == ["hello.txt"]

    download = await client.get("/api/files/hello.txt", headers=AUTH)
    assert download.status == 200
    assert await download.read() == b"phone bytes"


async def test_upload_cannot_write_outside_the_transfer_dir(client, transfers):
    resp = await client.post(
        "/api/upload", data=upload_form("../../escaped.txt", b"nope"), headers=AUTH
    )
    assert (await resp.json())["ok"] is True
    # Whatever the name arrives as -- aiohttp percent-encodes the separators on
    # the way out, a hand-rolled client would not -- it lands in the transfer
    # directory and nowhere else. safe_name's own handling of a literal
    # "../../" is covered in tests/test_remote_features.py.
    written = list(transfers.iterdir())
    assert len(written) == 1
    assert written[0].parent == transfers
    assert not (transfers.parent / "escaped.txt").exists()
    assert not (transfers.parent.parent / "escaped.txt").exists()


async def test_upload_without_a_file_is_a_400(client, transfers):
    resp = await client.post("/api/upload", data={"notafile": "x"}, headers=AUTH)
    assert resp.status == 400


async def test_download_of_a_missing_file_is_a_404(client, transfers):
    resp = await client.get("/api/files/nothing-here.txt", headers=AUTH)
    assert resp.status == 404


async def test_notifications_report_why_they_are_empty(client, monkeypatch):
    class FakeMirror:
        error = "dbus-monitor is not installed"
        running = False

        def start(self):
            return False

        def entries(self, since):
            return []

    monkeypatch.setattr("vt.sources.notifications_mirror.mirror", lambda: FakeMirror())
    body = await (await client.get("/api/notifications", headers=AUTH)).json()
    assert body["ok"] is False
    assert body["error"] == "dbus-monitor is not installed"
