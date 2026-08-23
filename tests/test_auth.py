"""Tests for remote access: pairing, device credentials, and what the public
URL is *not* allowed to be enough for.

The premise of every test here is that the server is reachable from the open
internet. A request that arrives through the tunnel gets nothing without a
paired device -- not with the startup token, not with a spoofed client IP, and
not by guessing codes faster than the rate limiter allows.
"""

import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt.auth import (
    CODE_LENGTH,
    AuditLog,
    AuthError,
    DeviceStore,
    PairingCodes,
    RateLimiter,
    clean_name,
    format_code,
    is_private_ip,
    normalize_code,
    resolve_client_ip,
)
from vt.server import VoiceTalkServer

# A request forwarded by cloudflared: loopback peer, real client in the header.
REMOTE = {"CF-Connecting-IP": "203.0.113.7"}


def make_server(tmp_path, **kwargs) -> VoiceTalkServer:
    kwargs.setdefault("token", "test-token")
    kwargs.setdefault("trust_proxy", True)
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


async def pair(client, name="phone", headers=None):
    """Pair a device the way a phone does, and return its auth headers."""
    code = client.vt.auth.codes.issue()
    resp = await client.post(
        "/api/pair", json={"code": code, "name": name}, headers=headers or {}
    )
    assert resp.status == 200, await resp.text()
    body = await resp.json()
    return {"X-VT-Device": body["device_id"], "X-VT-Secret": body["secret"]}


# --- the device store -------------------------------------------------------

def test_secret_survives_a_reload(tmp_path):
    store = DeviceStore(tmp_path / "d.json")
    device_id, secret = store.register("phone")
    assert DeviceStore(tmp_path / "d.json").verify(device_id, secret) is not None


def test_store_is_not_world_readable(tmp_path):
    path = tmp_path / "d.json"
    DeviceStore(path).register("phone")
    assert path.stat().st_mode & 0o077 == 0


def test_the_secret_itself_is_never_written(tmp_path):
    path = tmp_path / "d.json"
    _, secret = DeviceStore(path).register("phone")
    assert secret not in path.read_text()


def test_wrong_secret_and_unknown_id_both_fail(tmp_path):
    store = DeviceStore(tmp_path / "d.json")
    device_id, secret = store.register("phone")
    assert store.verify(device_id, secret + "x") is None
    assert store.verify("0000000000000000", secret) is None
    assert store.verify("", "") is None


def test_revoke_takes_effect_immediately(tmp_path):
    store = DeviceStore(tmp_path / "d.json")
    device_id, secret = store.register("phone")
    assert store.revoke(device_id) is True
    assert store.verify(device_id, secret) is None
    assert store.revoke(device_id) is False


def test_a_corrupt_store_raises_rather_than_unpairing_everything(tmp_path):
    path = tmp_path / "d.json"
    path.write_text("{ not json")
    with pytest.raises(AuthError):
        DeviceStore(path)


def test_names_are_bounded_and_printable():
    assert clean_name("a" * 200) == "a" * 48
    assert clean_name("  \x00\x07  ") == "device"
    assert clean_name(None) == "device"


# --- pairing codes ----------------------------------------------------------

def test_a_code_works_exactly_once(tmp_path):
    codes = PairingCodes(tmp_path / "p.json")
    code = codes.issue()
    assert codes.redeem(code) is True
    assert codes.redeem(code) is False


def test_a_code_is_accepted_as_the_user_would_type_it(tmp_path):
    codes = PairingCodes(tmp_path / "p.json")
    code = codes.issue()
    assert codes.redeem(format_code(code).lower()) is True


def test_an_expired_code_is_refused(tmp_path):
    codes = PairingCodes(tmp_path / "p.json", ttl=-1.0)
    assert codes.redeem(codes.issue()) is False


def test_codes_are_shared_across_processes(tmp_path):
    """`vt pair` runs in a second terminal; the server has to see its code."""
    cli = PairingCodes(tmp_path / "p.json")
    server = PairingCodes(tmp_path / "p.json")
    assert server.redeem(cli.issue()) is True


def test_normalize_rejects_padding_to_the_right_length():
    assert normalize_code("!!!!!!!!!!") == ""
    assert len(normalize_code(format_code("A" * CODE_LENGTH))) == CODE_LENGTH


# --- rate limiting ----------------------------------------------------------

def test_lockout_engages_and_success_clears_it():
    limiter = RateLimiter(limit=3, window=60, lockout=30)
    assert limiter.record_failure("ip") == 0
    assert limiter.record_failure("ip") == 0
    assert limiter.record_failure("ip") > 0
    assert limiter.retry_after("ip") > 0
    limiter.record_success("ip")
    assert limiter.retry_after("ip") == 0


def test_failures_outside_the_window_do_not_accumulate():
    limiter = RateLimiter(limit=3, window=0.01, lockout=30)
    limiter.record_failure("ip")
    limiter.record_failure("ip")
    time.sleep(0.02)
    assert limiter.record_failure("ip") == 0


# --- client address resolution ---------------------------------------------

def test_proxy_headers_are_read_only_from_loopback():
    assert resolve_client_ip("127.0.0.1", REMOTE, True) == ("203.0.113.7", True)
    # An off-loopback caller setting the header themselves is not a proxy.
    assert resolve_client_ip("198.51.100.4", REMOTE, True) == ("198.51.100.4", False)
    assert resolve_client_ip("127.0.0.1", REMOTE, False) == ("127.0.0.1", False)


def test_private_ranges_include_ipv4_mapped_peers():
    assert is_private_ip("192.168.1.5")
    assert is_private_ip("::ffff:192.168.1.5")
    assert is_private_ip("::1")
    assert not is_private_ip("203.0.113.7")
    assert not is_private_ip("")


# --- what the public URL alone gets you ------------------------------------

async def test_the_startup_token_is_refused_from_off_network(client):
    """The whole point: publishing the URL leaks no control.

    The token rides in a QR code and a bookmark, which is fine for a network
    you own and unacceptable as an internet-facing credential.
    """
    resp = await client.get("/api/state", headers={"X-VT-Token": "test-token", **REMOTE})
    assert resp.status == 401
    assert (await resp.json())["needs_pairing"] is True


async def test_no_token_mode_still_refuses_off_network(tmp_path):
    """--no-token means 'anyone on my LAN', never 'anyone at all'."""
    server = make_server(tmp_path, token="")
    async with TestClient(TestServer(server.make_app())) as c:
        assert (await c.get("/api/state")).status == 200
        assert (await c.get("/api/state", headers=REMOTE)).status == 401


async def test_a_forged_private_client_ip_is_still_treated_as_remote(client):
    """A spoofed CF-Connecting-IP must not buy LAN trust.

    Cloudflare's edge overwrites this header, but the security of pairing does
    not get to depend on that: anything arriving through a proxy came from
    outside, whatever address it claims.
    """
    forged = {"CF-Connecting-IP": "192.168.1.50", "X-VT-Token": "test-token"}
    resp = await client.get("/api/state", headers=forged)
    assert resp.status == 401
    assert (await resp.json())["needs_pairing"] is True


async def test_a_paired_device_works_from_off_network(client):
    headers = await pair(client)
    assert (await client.get("/api/state", headers={**headers, **REMOTE})).status == 200
    assert (await client.post(
        "/api/do", json={"target": "bogus:x", "action": "run"},
        headers={**headers, **REMOTE},
    )).status == 200


async def test_require_pairing_refuses_the_token_on_the_lan_too(tmp_path):
    server = make_server(tmp_path, require_pairing=True)
    async with TestClient(TestServer(server.make_app())) as c:
        assert (await c.get("/api/state", headers={"X-VT-Token": "test-token"})).status == 401
        headers = await pair(c)
        assert (await c.get("/api/state", headers=headers)).status == 200


# --- the pairing endpoint ---------------------------------------------------

async def test_pairing_needs_no_credential_but_needs_the_code(client):
    assert (await client.post("/api/pair", json={"code": "AAAAAAAAAA"})).status == 403
    assert (await client.post("/api/pair", json={})).status == 403
    assert (await client.post("/api/pair", data="not json")).status == 403


async def test_a_pairing_code_cannot_be_replayed(client):
    code = client.vt.auth.codes.issue()
    assert (await client.post("/api/pair", json={"code": code})).status == 200
    assert (await client.post("/api/pair", json={"code": code})).status == 403


async def test_guessing_codes_gets_locked_out(client):
    for _ in range(5):
        resp = await client.post("/api/pair", json={"code": "AAAAAAAAAA"}, headers=REMOTE)
    assert resp.status in (403, 429)
    resp = await client.post("/api/pair", json={"code": "AAAAAAAAAA"}, headers=REMOTE)
    assert resp.status == 429
    assert int(resp.headers["Retry-After"]) > 0
    # A real code is refused too while the lockout stands.
    code = client.vt.auth.codes.issue()
    assert (await client.post("/api/pair", json={"code": code}, headers=REMOTE)).status == 429


async def test_guessing_device_secrets_gets_locked_out(client):
    bad = {"X-VT-Device": "deadbeefdeadbeef", "X-VT-Secret": "wrong", **REMOTE}
    for _ in range(6):
        resp = await client.get("/api/state", headers=bad)
    assert resp.status == 429
    # And the lockout covers a valid credential from the same address, so a
    # brute-forcer cannot keep probing from a machine that also holds one.
    headers = await pair(client)
    assert (await client.get("/api/state", headers={**headers, **REMOTE})).status == 429


async def test_the_device_limit_is_enforced(client, monkeypatch):
    monkeypatch.setattr("vt.auth.MAX_DEVICES", 2)
    await pair(client)
    await pair(client)
    code = client.vt.auth.codes.issue()
    resp = await client.post("/api/pair", json={"code": code})
    assert resp.status == 409


# --- device management ------------------------------------------------------

async def test_devices_lists_without_leaking_secrets(client):
    headers = await pair(client, name="Pixel")
    resp = await client.get("/api/devices", headers=headers)
    body = await resp.json()
    assert body["devices"][0]["name"] == "Pixel"
    assert body["current"] == headers["X-VT-Device"]
    assert "secret" not in body["devices"][0]
    assert "secret_hash" not in body["devices"][0]


async def test_revoking_a_device_cuts_it_off_at_once(client):
    keeper = await pair(client, name="mine")
    victim = await pair(client, name="lost phone")
    assert (await client.get("/api/state", headers=victim)).status == 200

    resp = await client.post(
        "/api/devices/revoke", json={"id": victim["X-VT-Device"]}, headers=keeper
    )
    assert resp.status == 200
    assert (await client.get("/api/state", headers={**victim, **REMOTE})).status == 401


async def test_devices_endpoints_require_auth(client):
    assert (await client.get("/api/devices", headers=REMOTE)).status == 401
    assert (await client.post("/api/devices/revoke", json={"id": "x"}, headers=REMOTE)).status == 401


async def test_a_lan_session_can_mint_its_own_device(client):
    """The zero-friction path: the browser holding the startup token upgrades
    itself, so nobody types a code to use the phone on their own network."""
    resp = await client.post(
        "/api/pair/self", json={"name": "Android Firefox"},
        headers={"X-VT-Token": "test-token"},
    )
    assert resp.status == 200
    body = await resp.json()
    headers = {"X-VT-Device": body["device_id"], "X-VT-Secret": body["secret"]}
    assert (await client.get("/api/state", headers={**headers, **REMOTE})).status == 200


async def test_pair_self_is_not_a_way_in_from_outside(client):
    assert (await client.post("/api/pair/self", json={}, headers=REMOTE)).status == 401


# --- session --------------------------------------------------------------

async def test_session_tells_an_unpaired_origin_to_pair(client):
    body = await (await client.get("/api/session", headers=REMOTE)).json()
    assert body["authenticated"] is False
    assert body["needs_pairing"] is True
    assert body["remote"] is True


async def test_session_identifies_a_paired_device(client):
    headers = await pair(client, name="Pixel")
    body = await (await client.get("/api/session", headers={**headers, **REMOTE})).json()
    assert body["authenticated"] is True
    assert body["kind"] == "device"
    assert body["name"] == "Pixel"


# --- response hardening -----------------------------------------------------

async def test_pages_carry_a_nonce_csp_and_no_inline_handlers(client):
    resp = await client.get("/")
    csp = resp.headers["Content-Security-Policy"]
    body = await resp.text()
    assert "'unsafe-inline'" not in csp
    assert "default-src 'none'" in csp
    nonce = csp.split("script-src 'nonce-")[1].split("'")[0]
    assert f'<script nonce="{nonce}">' in body
    assert f'<style nonce="{nonce}">' in body
    assert "onclick=\"" not in body


async def test_each_page_load_gets_a_fresh_nonce(client):
    first = (await client.get("/")).headers["Content-Security-Policy"]
    second = (await client.get("/")).headers["Content-Security-Policy"]
    assert first != second


async def test_security_headers_are_on_every_response(client):
    for path in ("/", "/api/state"):
        resp = await client.get(path, headers={"X-VT-Token": "test-token"})
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        assert resp.headers["Referrer-Policy"] == "no-referrer"
        assert "Content-Security-Policy" in resp.headers


async def test_hsts_only_once_the_hop_was_really_https(client):
    plain = await client.get("/")
    assert "Strict-Transport-Security" not in plain.headers
    secure = await client.get("/", headers={"X-Forwarded-Proto": "https"})
    assert "max-age=" in secure.headers["Strict-Transport-Security"]


async def test_the_pairing_redirect_preserves_the_code(client):
    """?t=...&p=... has to survive the token-stripping bounce, or a pairing
    link that also carries a token silently loses the code."""
    body = await (await client.get("/", params={"t": "test-token", "p": "ABCDE12345"})).text()
    assert 'p.delete("t")' in body
    assert "ABCDE12345" not in body  # still never reflected


# --- audit log --------------------------------------------------------------

async def test_actions_are_recorded_with_who_asked(client, tmp_path):
    headers = await pair(client, name="Pixel")
    await client.post(
        "/api/do", json={"target": "bogus:x", "action": "run"},
        headers={**headers, **REMOTE},
    )
    entries = AuditLog(tmp_path / "audit.log").tail(50)
    actions = [e for e in entries if e["event"] == "action"]
    assert actions[-1]["who"] == "Pixel"
    assert actions[-1]["ip"] == "203.0.113.7"
    assert actions[-1]["target"] == "bogus:x"


async def test_rejections_are_recorded(client, tmp_path):
    await client.get("/api/state", headers={"X-VT-Token": "test-token", **REMOTE})
    await client.post("/api/pair", json={"code": "AAAAAAAAAA"}, headers=REMOTE)
    events = {e["event"] for e in AuditLog(tmp_path / "audit.log").tail(50)}
    assert "auth.reject" in events
    assert "pair.reject" in events


def test_the_audit_log_is_not_world_readable(tmp_path):
    log = AuditLog(tmp_path / "audit.log")
    log.record("action", who="phone")
    assert (tmp_path / "audit.log").stat().st_mode & 0o077 == 0


def test_a_broken_audit_log_never_breaks_a_request(tmp_path):
    """Evidence, not a dependency: logging failure must stay silent."""
    log = AuditLog(tmp_path / "nope" / "deep" / "audit.log")
    log.path.parent.parent.write_text("i am a file, not a directory")
    log.record("action", who="phone")  # must not raise
