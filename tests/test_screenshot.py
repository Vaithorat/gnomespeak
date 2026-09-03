"""Tests for the screenshot endpoint: auth, refusal, and never keeping the file."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt.server import VoiceTalkServer
from vt.sources import screenshot


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


HEADERS = {"X-VT-Token": "test-token"}


async def test_a_screenshot_requires_a_credential(client):
    assert (await client.get("/api/screenshot")).status == 401


async def test_no_portal_is_reported_not_crashed(client, monkeypatch):
    monkeypatch.setattr(screenshot, "available", lambda: False)
    resp = await client.get("/api/screenshot", headers=HEADERS)
    assert resp.status == 503
    assert "portal" in (await resp.json())["message"]


async def test_declining_on_the_pc_is_not_a_dbus_error(client, monkeypatch):
    monkeypatch.setattr(screenshot, "available", lambda: True)
    monkeypatch.setattr(
        screenshot, "capture",
        lambda *a, **k: {"ok": False, "message": "You declined the screenshot on the PC"},
    )
    resp = await client.get("/api/screenshot", headers=HEADERS)
    assert resp.status == 403
    assert "declined" in (await resp.json())["message"]


async def test_the_image_is_served_and_the_file_is_gone(client, monkeypatch, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\npretend")
    monkeypatch.setattr(screenshot, "available", lambda: True)
    monkeypatch.setattr(screenshot, "capture", lambda *a, **k: {"ok": True, "path": str(shot)})

    resp = await client.get("/api/screenshot", headers=HEADERS)

    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert (await resp.read()).startswith(b"\x89PNG")
    # Not a stream, and not an archive: nothing is left behind on the PC.
    assert not shot.exists()


async def test_a_screenshot_is_audited(client, monkeypatch, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"x")
    monkeypatch.setattr(screenshot, "available", lambda: True)
    monkeypatch.setattr(screenshot, "capture", lambda *a, **k: {"ok": True, "path": str(shot)})

    await client.get("/api/screenshot", headers=HEADERS)

    assert "screenshot" in client.vt.auth.audit.path.read_text()


def test_read_and_remove_leaves_nothing(tmp_path):
    path = tmp_path / "shot.png"
    path.write_bytes(b"data")
    assert screenshot.read_and_remove(str(path)) == b"data"
    assert not path.exists()


def test_capture_without_pygobject_explains_itself(monkeypatch):
    monkeypatch.setattr(screenshot, "HAS_GI", False)
    result = screenshot.capture()
    assert result["ok"] is False and "gi" in result["message"]
