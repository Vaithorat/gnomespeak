"""Tests for using a transferred picture as the desktop background.

GSettings will accept a URI pointing at anything at all, and a background that
silently fails to load looks exactly like the feature not working -- so the
checks that a file exists and is really an image are the feature, not the
wrapper around it.
"""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt.server import VoiceTalkServer
from vt.sources import wallpaper

AUTH = {"X-VT-Token": "test-token"}

PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
       b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
       b"\x00\x00IEND\xaeB`\x82")


@pytest.fixture
def transfer(tmp_path, monkeypatch):
    monkeypatch.setenv("GNOMESPEAK_TRANSFER_DIR", str(tmp_path / "transfer"))
    (tmp_path / "transfer").mkdir()
    return tmp_path / "transfer"


@pytest.fixture
def gsettings(monkeypatch):
    calls = []

    class Result:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(wallpaper.subprocess, "run",
                        lambda argv, **kw: calls.append(argv) or Result())
    return calls


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


def test_both_the_light_and_dark_keys_are_set(tmp_path, gsettings):
    """Setting only one leaves the wallpaper changing back with the theme."""
    picture = tmp_path / "photo.png"
    picture.write_bytes(PNG)

    assert wallpaper.set_from(picture)["ok"] is True
    assert [argv[3] for argv in gsettings] == list(wallpaper.KEYS)
    assert all(argv[4] == picture.resolve().as_uri() for argv in gsettings)


def test_a_file_that_is_not_an_image_is_refused(tmp_path, gsettings):
    text = tmp_path / "notes.txt"
    text.write_text("hello")

    result = wallpaper.set_from(text)

    assert result["ok"] is False and "not an image" in result["message"]
    assert gsettings == [], "gsettings was called for something that is not a picture"


def test_a_file_that_is_gone_is_refused(tmp_path, gsettings):
    assert wallpaper.set_from(tmp_path / "nothing.png")["ok"] is False
    assert gsettings == []


def test_an_image_with_a_lying_extension_is_still_accepted(tmp_path, gsettings):
    """The bytes decide, not the name."""
    picture = tmp_path / "photo.txt"
    picture.write_bytes(PNG)
    assert wallpaper.set_from(picture)["ok"] is True


def test_a_machine_without_gsettings_says_so(tmp_path, monkeypatch):
    picture = tmp_path / "photo.png"
    picture.write_bytes(PNG)

    def missing(argv, **kw):
        raise FileNotFoundError()

    monkeypatch.setattr(wallpaper.subprocess, "run", missing)
    assert "gsettings" in wallpaper.set_from(picture)["message"]


def test_gsettings_refusing_is_reported(tmp_path, monkeypatch):
    picture = tmp_path / "photo.png"
    picture.write_bytes(PNG)

    class Result:
        returncode, stdout, stderr = 1, "", "No such schema\n"

    monkeypatch.setattr(wallpaper.subprocess, "run", lambda argv, **kw: Result())
    result = wallpaper.set_from(picture)
    assert result["ok"] is False and "No such schema" in result["message"]


async def test_the_endpoint_sets_a_transferred_picture(client, transfer, gsettings):
    (transfer / "photo.png").write_bytes(PNG)
    resp = await client.post("/api/files/wallpaper", json={"name": "photo.png"}, headers=AUTH)
    assert (await resp.json())["ok"] is True
    assert len(gsettings) == 2


async def test_a_file_outside_the_transfer_folder_is_not_reachable(client, transfer, gsettings):
    resp = await client.post("/api/files/wallpaper",
                             json={"name": "../../.bashrc"}, headers=AUTH)
    assert resp.status == 404
    assert gsettings == []


async def test_setting_the_wallpaper_is_audited(client, transfer, gsettings):
    (transfer / "photo.png").write_bytes(PNG)
    await client.post("/api/files/wallpaper", json={"name": "photo.png"}, headers=AUTH)
    assert "wallpaper.set" in [e["event"] for e in client.vt.auth.audit.tail(10)]


async def test_a_guest_may_not_change_how_the_pc_looks(client, transfer, gsettings):
    (transfer / "photo.png").write_bytes(PNG)
    device_id, secret = client.vt.auth.devices.register("Visitor", scope="guest")
    resp = await client.post(
        "/api/files/wallpaper", json={"name": "photo.png"},
        headers={"X-VT-Device": device_id, "X-VT-Secret": secret},
    )
    assert resp.status == 403
    assert gsettings == []
