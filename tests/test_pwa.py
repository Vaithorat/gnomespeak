"""Tests for the installable web app: manifest, worker, icons, share target."""

import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

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
        yield c


async def test_the_manifest_is_served_without_a_credential(client):
    """The browser fetches it before anyone has typed anything."""
    resp = await client.get("/manifest.webmanifest")
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("application/manifest+json")


async def test_the_manifest_declares_an_installable_app(client):
    data = json.loads(await (await client.get("/manifest.webmanifest")).text())
    assert data["display"] == "standalone"
    assert data["start_url"] == "/"
    assert {icon["sizes"] for icon in data["icons"]} >= {"192x192", "512x512"}
    assert any(icon["purpose"] == "maskable" for icon in data["icons"])


async def test_the_manifest_registers_a_share_target(client):
    share = json.loads(await (await client.get("/manifest.webmanifest")).text())["share_target"]
    assert share["action"] == "/share"
    assert share["method"] == "POST"
    assert share["params"]["files"][0]["name"] == "files"


async def test_the_worker_may_control_the_whole_origin(client):
    """Without this header a worker served from anywhere but / is scoped out."""
    resp = await client.get("/sw.js")
    assert resp.status == 200
    assert resp.headers["Service-Worker-Allowed"] == "/"


async def test_the_worker_is_never_cached(client):
    """A stale worker outlives every upgrade it was supposed to deliver."""
    resp = await client.get("/sw.js")
    assert "no-cache" in resp.headers["Cache-Control"]


@pytest.mark.parametrize("name", ["icon-192.png", "icon-512.png", "icon-maskable-512.png"])
async def test_the_icons_exist(client, name):
    resp = await client.get(f"/{name}")
    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert (await resp.read())[:8] == b"\x89PNG\r\n\x1a\n"


async def test_an_unknown_asset_is_not_a_path_into_the_package(client):
    resp = await client.get("/server.py")
    assert resp.status == 404


async def test_a_share_that_reaches_the_server_explains_itself(client):
    """Only happens with no worker: the POST carries no credential at all."""
    resp = await client.post("/share", data={"text": "hello"})
    assert resp.status == 200
    assert "Open GnomeSpeak first" in await resp.text()


async def test_the_page_links_the_manifest(client):
    page = await (await client.get("/")).text()
    assert 'rel="manifest"' in page
    assert "/sw.js" in page


async def test_the_policy_allows_the_worker_and_manifest(client):
    """Both are blocked by the page's own default-src 'none' unless named."""
    policy = (await client.get("/")).headers["Content-Security-Policy"]
    assert "worker-src 'self'" in policy
    assert "manifest-src 'self'" in policy


async def test_the_installed_icon_offers_quick_actions(client):
    """Long-pressing the home-screen icon should reach the screens people open."""
    import json

    manifest = json.loads(await (await client.get("/manifest.webmanifest")).text())
    urls = {s["url"] for s in manifest.get("shortcuts", [])}
    assert urls == {"/?go=input", "/?go=clipboard", "/?go=screen", "/?go=notifs"}


async def test_every_quick_action_names_a_screen_the_page_knows(client):
    """A shortcut to a view that does not exist opens the home screen silently."""
    import json
    import re

    manifest = json.loads(await (await client.get("/manifest.webmanifest")).text())
    page = await (await client.get("/")).text()
    known = re.search(r"const DEEP_LINKS = \{(.*?)\};", page, re.S).group(1)
    for shortcut in manifest.get("shortcuts", []):
        name = shortcut["url"].split("go=")[1]
        assert f"{name}:" in known, f"no view for {name}"
