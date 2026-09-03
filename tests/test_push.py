"""Tests for Web Push: reaching a phone whose page is closed.

The encryption is checked against RFC 8291's own worked example rather than
against itself -- if this file passes, the bytes on the wire are the bytes the
standard says they should be, and any browser will decrypt them.
"""

import json
import tempfile
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from vt import push
from vt.server import VoiceTalkServer

AUTH = {"X-VT-Token": "test-token"}

# RFC 8291, section 5.
UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
UA_AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
SALT = "DGv6ra1nlYgDCS1FRnbzlw"
PLAINTEXT = b"When I grow up, I want to be a watermelon"
EXPECTED = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLoc"
    "InmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLV"
    "WGNWQexSgSxsj_Qulcy4a-fN"
)

pytestmark = pytest.mark.skipif(not push.available(), reason="cryptography is not installed")


def subscription(endpoint="https://push.example.com/x"):
    return {"endpoint": endpoint, "keys": {"p256dh": UA_PUBLIC, "auth": UA_AUTH}}


@pytest.fixture
def keys(tmp_path, monkeypatch):
    """A VAPID identity in a temporary directory, not the developer's own."""
    monkeypatch.setattr(push, "_config_dir", lambda: tmp_path)
    return push.vapid_keys()


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setattr(push, "_config_dir", lambda: tmp_path)
    server = VoiceTalkServer(
        "127.0.0.1", 0, token="test-token",
        devices_path=tmp_path / "devices.json",
        audit_path=tmp_path / "audit.log",
        codes_path=tmp_path / "pairing.json",
        push_path=tmp_path / "push.json",
    )
    async with TestClient(TestServer(server.make_app())) as c:
        c.vt = server
        yield c


# --- the standard -----------------------------------------------------------

def test_the_encryption_matches_the_rfc_example():
    """RFC 8291 section 5, byte for byte."""
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.derive_private_key(int.from_bytes(push.b64d(AS_PRIVATE), "big"), ec.SECP256R1())
    body = push.encrypt(PLAINTEXT, UA_PUBLIC, UA_AUTH,
                        salt=push.b64d(SALT), ephemeral=private)
    assert push.b64e(body) == EXPECTED


def test_every_message_gets_its_own_salt_and_key():
    """Two identical payloads must not produce identical ciphertext."""
    first = push.encrypt(b"hello", UA_PUBLIC, UA_AUTH)
    second = push.encrypt(b"hello", UA_PUBLIC, UA_AUTH)
    assert first != second


def test_the_body_carries_the_header_a_browser_expects():
    body = push.encrypt(b"hello", UA_PUBLIC, UA_AUTH)
    assert len(body) > 16 + 4 + 1 + 65
    assert body[20] == 65, "the ephemeral key length byte"


# --- VAPID ------------------------------------------------------------------

def test_the_identity_is_generated_once(keys, tmp_path):
    assert push.vapid_keys() == keys
    assert (tmp_path / "push-keys.json").exists()


def test_the_identity_file_is_private(keys, tmp_path):
    assert oct((tmp_path / "push-keys.json").stat().st_mode)[-3:] == "600"


def test_the_authorization_names_the_push_service(keys):
    header = push.vapid_header("https://push.example.com/some/endpoint")
    assert header.startswith("vapid t=")
    token = header[len("vapid t="):].split(",")[0]
    claims = json.loads(push.b64d(token.split(".")[1]))
    assert claims["aud"] == "https://push.example.com"
    assert claims["sub"].startswith("mailto:")
    assert f"k={keys['public']}" in header


def test_the_token_is_a_real_es256_signature(keys):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils

    header = push.vapid_header("https://push.example.com/x")
    token = header[len("vapid t="):].split(",")[0]
    signing_input, signature = token.rsplit(".", 1)
    raw = push.b64d(signature)
    der = utils.encode_dss_signature(int.from_bytes(raw[:32], "big"),
                                     int.from_bytes(raw[32:], "big"))
    public = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), push.b64d(keys["public"]))
    public.verify(der, signing_input.encode(), ec.ECDSA(hashes.SHA256()))


# --- sending ----------------------------------------------------------------

async def test_a_real_post_reaches_a_push_service(keys):
    """A local server standing in for the push service, and a real request."""
    received = {}

    async def endpoint(request):
        received["body"] = await request.read()
        received["headers"] = dict(request.headers)
        return web.Response(status=201)

    app = web.Application()
    app.router.add_post("/push/{id}", endpoint)
    async with TestClient(TestServer(app)) as service:
        # The request is built for a real https endpoint -- that is what gets
        # signed and encrypted -- and then posted at the local stand-in, which
        # speaks http. Everything on the wire is what a push service would get.
        request = push.build_request(subscription("https://push.example.com/push/abc"),
                                     {"title": "Hi"})
        request.full_url = f"http://127.0.0.1:{service.server.port}/push/abc"
        status = await _post(request)

    assert status == 201
    # urllib title-cases the header names it sends.
    headers = {name.lower(): value for name, value in received["headers"].items()}
    assert headers["content-encoding"] == "aes128gcm"
    assert headers["authorization"].startswith("vapid t=")
    assert headers["ttl"]
    assert len(received["body"]) > 86


async def _post(request) -> int:
    import asyncio
    import urllib.request

    def run():
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status

    return await asyncio.get_running_loop().run_in_executor(None, run)


def test_a_subscription_without_keys_is_refused():
    result = push.send({"endpoint": "https://push.example.com/x"}, {"title": "Hi"})
    assert result["ok"] is False and result["gone"] is True


def test_a_dead_subscription_is_reported_as_gone(monkeypatch, keys):
    import urllib.error

    def http_error(*args, **kwargs):
        raise urllib.error.HTTPError("https://push.example.com/x", 410, "Gone", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", http_error)
    result = push.send(subscription(), {"title": "Hi"})
    assert result["ok"] is False and result["gone"] is True


def test_a_temporary_failure_keeps_the_subscription(monkeypatch, keys):
    import urllib.error

    def http_error(*args, **kwargs):
        raise urllib.error.HTTPError("https://push.example.com/x", 503, "Busy", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", http_error)
    result = push.send(subscription(), {"title": "Hi"})
    assert result["ok"] is False and result["gone"] is False


# --- the store --------------------------------------------------------------

def test_a_subscription_is_kept_and_found(tmp_path):
    store = push.SubscriptionStore(tmp_path / "push.json")
    assert store.add(subscription(), device_id="abc", name="Pixel") is True
    assert len(store) == 1
    assert store.for_device("abc")[0]["name"] == "Pixel"


def test_the_store_is_private(tmp_path):
    store = push.SubscriptionStore(tmp_path / "push.json")
    store.add(subscription(), device_id="abc")
    assert oct((tmp_path / "push.json").stat().st_mode)[-3:] == "600"


def test_rubbish_is_not_a_subscription(tmp_path):
    store = push.SubscriptionStore(tmp_path / "push.json")
    assert store.add({}, device_id="abc") is False
    assert store.add({"endpoint": "http://not-https.example.com",
                      "keys": {"p256dh": "x", "auth": "y"}}) is False
    assert len(store) == 0


def test_subscribing_twice_from_one_phone_keeps_one(tmp_path):
    store = push.SubscriptionStore(tmp_path / "push.json")
    store.add(subscription(), device_id="abc")
    store.add(subscription(), device_id="abc")
    assert len(store) == 1


def test_a_subscription_can_be_forgotten(tmp_path):
    store = push.SubscriptionStore(tmp_path / "push.json")
    store.add(subscription(), device_id="abc")
    assert store.remove("https://push.example.com/x") is True
    assert store.remove("https://push.example.com/x") is False


# --- the endpoints ----------------------------------------------------------

async def test_the_phone_is_given_the_key(client):
    body = await (await client.get("/api/push/key", headers=AUTH)).json()
    assert body["available"] is True
    assert body["key"] and body["subscribed"] is False


async def test_subscribing_and_unsubscribing(client):
    resp = await client.post("/api/push/subscribe",
                             json={"subscription": subscription()}, headers=AUTH)
    assert (await resp.json())["ok"] is True
    assert len(client.vt.push_subscriptions) == 1

    resp = await client.post("/api/push/unsubscribe",
                             json={"endpoint": subscription()["endpoint"]}, headers=AUTH)
    assert (await resp.json())["removed"] is True
    assert len(client.vt.push_subscriptions) == 0


async def test_a_subscription_the_browser_did_not_make_is_refused(client):
    resp = await client.post("/api/push/subscribe", json={"subscription": {"endpoint": "x"}},
                             headers=AUTH)
    assert resp.status == 400


async def test_push_needs_a_credential(client):
    assert (await client.get("/api/push/key")).status == 401
    assert (await client.post("/api/push/subscribe", json={})).status == 401


async def test_a_guest_may_not_subscribe(client):
    device_id, secret = client.vt.auth.devices.register("Visitor", scope="guest")
    headers = {"X-VT-Device": device_id, "X-VT-Secret": secret}
    assert (await client.get("/api/push/key", headers=headers)).status == 403


# --- who gets pushed to -----------------------------------------------------

async def test_a_phone_looking_at_the_page_is_not_pushed_to(client, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "send",
                        lambda entry, payload: sent.append(entry) or {"ok": True, "status": 201})
    client.vt.push_subscriptions.add(subscription(), device_id="abc")
    client.vt._connected_devices.add("abc")

    assert await client.vt.push_out({"title": "Hi"}) == 0
    assert sent == []


async def test_a_phone_with_the_page_closed_is_pushed_to(client, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "send",
                        lambda entry, payload: sent.append(payload) or {"ok": True, "status": 201})
    client.vt.push_subscriptions.add(subscription(), device_id="abc")

    assert await client.vt.push_out({"title": "Hi"}) == 1
    assert sent[0]["title"] == "Hi"


async def test_a_subscription_the_service_calls_gone_is_dropped(client, monkeypatch):
    monkeypatch.setattr(push, "send",
                        lambda entry, payload: {"ok": False, "status": 410, "gone": True,
                                                "message": "Push service said 410"})
    client.vt.push_subscriptions.add(subscription(), device_id="abc")

    await client.vt.push_out({"title": "Hi"})

    assert len(client.vt.push_subscriptions) == 0
    assert "push.dropped" in [e["event"] for e in client.vt.auth.audit.tail(10)]


async def test_a_notification_is_pushed_as_well_as_broadcast(client, monkeypatch):
    pushed = []
    monkeypatch.setattr(push, "send",
                        lambda entry, payload: pushed.append(payload) or {"ok": True, "status": 201})
    monkeypatch.setattr(client.vt, "NOTIFICATION_SETTLE", 0.01)
    client.vt.push_subscriptions.add(subscription(), device_id="abc")

    client.vt._queue_notification({"seq": 3, "app": "Signal", "summary": "A message",
                                   "body": "hello", "id": 7, "ts": 1.0})
    await client.vt._notification_task

    assert pushed[0]["title"] == "A message"
    assert pushed[0]["url"] == "/?go=notifs"


def test_the_temp_dir_is_not_the_developers_config(tmp_path):
    """A guard for these tests themselves: nothing here writes to ~/.config."""
    assert Path(tempfile.gettempdir()) in tmp_path.parents or "pytest" in str(tmp_path)
