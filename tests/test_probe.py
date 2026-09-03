"""Tests for the saved-PC reachability probe.

The phone cannot ask another origin whether it is up -- the browser refuses the
cross-origin request, and the page's own CSP says connect-src 'self' -- so the
PC asks on its behalf. The tests here are mostly about what the answer must NOT
contain: a probe that reported status codes or bodies would turn a paired phone
into a port scanner with a readable result.
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from vt.server import VoiceTalkServer, probe_origin

AUTH = {"X-VT-Token": "test-token"}


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


@pytest.fixture
async def other_pc():
    """A second machine that answers /api/session the way a real one does."""
    app = web.Application()

    async def session(request):
        return web.json_response({"authenticated": False}, status=401)

    app.router.add_get("/api/session", session)
    async with TestClient(TestServer(app)) as c:
        yield f"http://127.0.0.1:{c.server.port}"


def test_only_http_urls_are_probed():
    assert probe_origin("file:///etc/passwd") == ""
    assert probe_origin("ftp://example.com") == ""
    assert probe_origin("") == ""
    assert probe_origin("not a url") == ""


def test_credentials_in_a_url_are_refused():
    """A probe is a question about a machine, not a way to send it a secret."""
    assert probe_origin("http://user:secret@example.com") == ""


def test_the_path_and_query_are_dropped():
    assert probe_origin("https://pc.example.com/some/page?t=secret") == "https://pc.example.com"


def test_a_port_survives_and_ipv6_is_bracketed():
    assert probe_origin("http://192.168.1.4:8765/") == "http://192.168.1.4:8765"
    assert probe_origin("http://[::1]:8765/") == "http://[::1]:8765"


async def test_a_machine_that_answers_is_reachable(client, other_pc):
    resp = await client.post("/api/probe", json={"urls": [other_pc]}, headers=AUTH)
    body = await resp.json()
    assert body["servers"] == [{"url": other_pc, "reachable": True, "checked": True}]


async def test_an_answer_carries_nothing_but_yes_or_no(client, other_pc):
    """Not the status code, not a header, not a byte of the body."""
    body = await client.post("/api/probe", json={"urls": [other_pc]}, headers=AUTH)
    row = (await body.json())["servers"][0]
    assert set(row) == {"url", "reachable", "checked"}


async def test_a_machine_that_is_not_there_is_not_reachable(client):
    # Port 1 on localhost: nothing listens, and the connection is refused at once.
    resp = await client.post("/api/probe", json={"urls": ["http://127.0.0.1:1"]}, headers=AUTH)
    row = (await resp.json())["servers"][0]
    assert row["reachable"] is False and row["checked"] is True


async def test_a_url_that_cannot_be_probed_says_so(client):
    resp = await client.post("/api/probe", json={"urls": ["file:///etc/passwd"]}, headers=AUTH)
    row = (await resp.json())["servers"][0]
    assert row == {"url": "file:///etc/passwd", "reachable": False, "checked": False}


async def test_the_number_of_urls_is_capped(client):
    urls = [f"http://127.0.0.1:{port}" for port in range(9000, 9040)]
    resp = await client.post("/api/probe", json={"urls": urls}, headers=AUTH)
    assert len((await resp.json())["servers"]) == client.vt.MAX_PROBE_URLS


async def test_probing_requires_a_credential(client, other_pc):
    assert (await client.post("/api/probe", json={"urls": [other_pc]})).status == 401


async def test_a_body_that_is_not_a_list_is_refused(client):
    resp = await client.post("/api/probe", json={"urls": "everything"}, headers=AUTH)
    assert resp.status == 400
