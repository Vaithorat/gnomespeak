"""Tests for what a paired device is allowed to do, and for how long.

A scope is not authentication: the phone is who it says it is, and is being
told this particular thing is not its to do. That distinction is why a refusal
is 403 rather than 401 -- a 401 makes the page throw its credential away and
ask to pair again, which is the opposite of what should happen.
"""

import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt.auth import CAPABILITIES, DeviceStore, PairingCodes, capability_for, scope_allows
from vt.server import VoiceTalkServer


@pytest.fixture
async def client(tmp_path):
    server = VoiceTalkServer(
        "127.0.0.1", 0, token="test-token",
        devices_path=tmp_path / "devices.json",
        audit_path=tmp_path / "audit.log",
        codes_path=tmp_path / "pairing.json",
    )
    async with TestClient(TestServer(server.make_app())) as c:
        c.vt = server
        yield c


def guest(client, scope="guest", expires_in=0.0):
    device_id, secret = client.vt.auth.devices.register(
        "Visitor", scope=scope, expires_in=expires_in
    )
    return {"X-VT-Device": device_id, "X-VT-Secret": secret}


# --- the scope table --------------------------------------------------------

def test_a_full_device_may_do_everything():
    assert all(scope_allows("full", capability) for capability in CAPABILITIES)


def test_a_guest_may_only_touch_media():
    allowed = [c for c in CAPABILITIES if scope_allows("guest", c)]
    assert allowed == ["media"]


def test_an_unknown_scope_is_treated_as_full():
    """Anything stored by an older version predates scopes and had them all."""
    assert scope_allows("", "power") is True
    assert scope_allows("something-else", "power") is True


def test_volume_and_shutdown_are_not_the_same_permission():
    """Both are system: rows, and that is exactly the trap."""
    assert capability_for("system:audio") == "media"
    assert capability_for("system:mic") == "media"
    assert capability_for("system:power") == "power"
    assert capability_for("system:display") == "system"


def test_players_and_streams_are_media():
    assert capability_for("player:firefox") == "media"
    assert capability_for("stream:95") == "media"
    assert capability_for("audio:sink") == "media"


def test_an_unknown_target_kind_is_not_a_guests():
    """A new target type should need a decision, not arrive allowed."""
    assert capability_for("somethingnew:1") == "apps"
    assert scope_allows("guest", capability_for("somethingnew:1")) is False


# --- the store --------------------------------------------------------------

def test_a_device_keeps_its_scope(tmp_path):
    store = DeviceStore(tmp_path / "devices.json")
    device_id, secret = store.register("Visitor", scope="guest")
    assert store.verify(device_id, secret)["scope"] == "guest"
    assert store.list_devices()[0]["scope"] == "guest"


def test_a_device_paired_without_a_scope_is_full(tmp_path):
    store = DeviceStore(tmp_path / "devices.json")
    device_id, secret = store.register("Mine")
    assert store.verify(device_id, secret)["scope"] == "full"
    assert store.list_devices()[0]["expires"] == 0.0


def test_an_expired_credential_stops_working(tmp_path):
    store = DeviceStore(tmp_path / "devices.json")
    device_id, secret = store.register("Visitor", scope="guest", expires_in=-1)
    assert store.verify(device_id, secret) is None


def test_an_expired_credential_is_forgotten(tmp_path):
    """It should also leave `vt devices`, which is where someone checks."""
    store = DeviceStore(tmp_path / "devices.json")
    device_id, secret = store.register("Visitor", expires_in=-1)
    store.verify(device_id, secret)
    assert store.list_devices() == []


def test_a_credential_that_has_not_expired_still_works(tmp_path):
    store = DeviceStore(tmp_path / "devices.json")
    device_id, secret = store.register("Visitor", expires_in=3600)
    assert store.verify(device_id, secret) is not None
    assert store.list_devices()[0]["expires"] > time.time()


# --- pairing codes carry the terms ------------------------------------------

def test_a_code_carries_the_scope_it_was_issued_with(tmp_path):
    codes = PairingCodes(tmp_path / "pairing.json")
    code = codes.issue("visitor", scope="guest", device_ttl=7200)
    terms = codes.redeem_terms(code)
    assert terms == {"scope": "guest", "device_ttl": 7200.0, "label": "visitor"}


def test_a_code_still_works_only_once(tmp_path):
    codes = PairingCodes(tmp_path / "pairing.json")
    code = codes.issue("visitor", scope="guest")
    assert codes.redeem_terms(code) is not None
    assert codes.redeem_terms(code) is None


async def test_pairing_with_a_guest_code_makes_a_guest(client):
    code = client.vt.auth.codes.issue("visitor", scope="guest", device_ttl=3600)
    resp = await client.post("/api/pair", json={"code": code, "name": "Visitor"})
    body = await resp.json()
    assert body["ok"] is True

    device = client.vt.auth.devices.list_devices()[-1]
    assert device["scope"] == "guest"
    assert device["expires"] > time.time()


# --- what the server refuses ------------------------------------------------

async def test_a_guest_may_change_the_volume(client, monkeypatch):
    monkeypatch.setattr("vt.server.execute_action",
                        lambda *a, **k: {"ok": True, "message": "Volume set"})
    resp = await client.post("/api/do", json={"target": "system:audio", "action": "mute"},
                             headers=guest(client))
    assert resp.status == 200
    assert (await resp.json())["ok"] is True


async def test_a_guest_may_not_shut_the_machine_down(client):
    resp = await client.post("/api/do", json={"target": "system:power", "action": "shutdown"},
                             headers=guest(client))
    assert resp.status == 403
    assert (await resp.json())["error"] == "forbidden"


async def test_a_refusal_is_not_a_401(client):
    """401 makes the page drop its credential and ask to pair again."""
    resp = await client.post("/api/do", json={"target": "system:power", "action": "lock"},
                             headers=guest(client))
    assert resp.status != 401


async def test_a_guest_may_not_type_on_the_pc(client):
    resp = await client.post("/api/input", json={"op": "text", "text": "hello"},
                             headers=guest(client))
    assert resp.status == 403


async def test_a_guest_may_not_read_the_files(client):
    assert (await client.get("/api/files/anything", headers=guest(client))).status == 403


async def test_a_guest_may_not_write_the_clipboard(client):
    resp = await client.post("/api/clipboard", json={"text": "hi"}, headers=guest(client))
    assert resp.status == 403


async def test_a_guest_may_not_open_a_link(client):
    resp = await client.post("/api/open", json={"url": "https://example.com"},
                             headers=guest(client))
    assert resp.status == 403


async def test_a_guest_may_not_take_a_screenshot(client):
    assert (await client.get("/api/screenshot", headers=guest(client))).status == 403


async def test_a_guest_may_not_read_the_security_log(client):
    assert (await client.get("/api/audit", headers=guest(client))).status == 403


async def test_a_guest_may_not_manage_other_devices(client):
    assert (await client.get("/api/devices", headers=guest(client))).status == 403


async def test_a_guest_can_still_see_what_is_playing(client):
    """Refusing everything would leave a visitor a blank page to control."""
    assert (await client.get("/api/state", headers=guest(client))).status == 200


async def test_a_refusal_is_recorded(client):
    await client.post("/api/do", json={"target": "system:power", "action": "shutdown"},
                      headers=guest(client))
    assert "scope.reject" in [e["event"] for e in client.vt.auth.audit.tail(10)]


async def test_a_full_device_is_refused_nothing(client, monkeypatch):
    monkeypatch.setattr("vt.server.execute_action",
                        lambda *a, **k: {"ok": True, "message": "done"})
    headers = guest(client, scope="full")
    resp = await client.post("/api/do", json={"target": "system:power", "action": "lock"},
                             headers=headers)
    assert resp.status == 200


async def test_the_lan_token_is_not_a_guest(client, monkeypatch):
    monkeypatch.setattr("vt.server.execute_action",
                        lambda *a, **k: {"ok": True, "message": "done"})
    resp = await client.post("/api/do", json={"target": "system:power", "action": "lock"},
                             headers={"X-VT-Token": "test-token"})
    assert resp.status == 200


async def test_a_guest_may_not_mint_itself_a_full_credential(client):
    """The hole this closes: /api/pair/self would have replaced the guest's
    limited credential with a full, never-expiring one."""
    headers = guest(client, scope="guest", expires_in=3600)
    before = len(client.vt.auth.devices.list_devices())

    resp = await client.post("/api/pair/self", json={"name": "Sneaky"}, headers=headers)

    assert resp.status == 403
    assert len(client.vt.auth.devices.list_devices()) == before


async def test_the_lan_browser_may_still_mint_one(client):
    resp = await client.post("/api/pair/self", json={"name": "This browser"},
                             headers={"X-VT-Token": "test-token"})
    assert resp.status == 200
    assert (await resp.json())["ok"] is True


async def test_a_guest_may_not_list_the_transferred_files(client):
    assert (await client.get("/api/files", headers=guest(client))).status == 403


async def test_a_guest_may_not_probe_other_machines(client):
    resp = await client.post("/api/probe", json={"urls": ["http://127.0.0.1:1"]},
                             headers=guest(client))
    assert resp.status == 403


async def test_a_guest_may_not_read_the_clipboard(client):
    """Reading is not the lesser half: it holds whatever was copied last."""
    assert (await client.get("/api/clipboard", headers=guest(client))).status == 403


async def test_a_guest_may_not_read_the_notifications(client):
    """Messages and delivery codes are not a visitor's business."""
    assert (await client.get("/api/notifications", headers=guest(client))).status == 403


async def test_a_guest_may_not_dismiss_or_mute_notifications(client):
    headers = guest(client)
    assert (await client.post("/api/notifications/dismiss",
                              json={"id": 1}, headers=headers)).status == 403
    assert (await client.post("/api/notifications/mute",
                              json={"app": "Slack"}, headers=headers)).status == 403


async def test_a_guest_may_not_read_the_machines_diagnostics(client):
    assert (await client.get("/api/diagnostics", headers=guest(client))).status == 403


async def test_a_guest_can_still_see_and_control_the_music(client, monkeypatch):
    """Whatever else is refused, the visitor's phone must still be worth opening."""
    monkeypatch.setattr("vt.server.execute_action",
                        lambda *a, **k: {"ok": True, "message": "Paused"})
    headers = guest(client)
    assert (await client.get("/api/state", headers=headers)).status == 200
    resp = await client.post("/api/do", json={"target": "player:vlc", "action": "playpause"},
                             headers=headers)
    assert resp.status == 200
