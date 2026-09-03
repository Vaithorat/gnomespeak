"""Tests for album art: what the server will fetch, and what it refuses."""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt.server import VoiceTalkServer
from vt.sources import art

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
HEADERS = {"X-VT-Token": "test-token"}


@pytest.fixture(autouse=True)
def clean():
    art._cache.clear()
    art._known.clear()
    yield
    art._cache.clear()
    art._known.clear()


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


def test_a_key_is_stable_and_reversible():
    key = art.key_for("file:///music/cover.png")
    assert key == art.key_for("file:///music/cover.png")
    assert art.url_for(key) == "file:///music/cover.png"


def test_an_unpublished_key_maps_to_nothing():
    """The phone names keys, so only what a player advertised is fetchable."""
    assert art.url_for("deadbeefdeadbeef") == ""


def test_no_art_is_no_key():
    assert art.key_for("") == ""


def test_a_local_image_is_read(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(PNG)
    data, content_type = art.fetch(cover.as_uri())
    assert data == PNG and content_type == "image/png"


def test_a_file_that_is_not_an_image_is_refused(tmp_path):
    """A player can name any path; only actual image bytes get served."""
    secret = tmp_path / "notes.txt"
    secret.write_text("not a picture")
    assert art.fetch(secret.as_uri()) == (b"", "")


def test_an_oversized_file_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(art, "MAX_BYTES", 8)
    big = tmp_path / "cover.png"
    big.write_bytes(PNG)
    assert art.fetch(big.as_uri()) == (b"", "")


def test_a_data_url_is_not_fetched():
    assert art.fetch("data:image/png;base64,AAAA") == (b"", "")


def test_a_missing_file_is_not_an_error(tmp_path):
    assert art.fetch((tmp_path / "gone.png").as_uri()) == (b"", "")


def test_the_second_fetch_is_cached(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(PNG)
    url = cover.as_uri()
    art.fetch(url)
    cover.unlink()
    assert art.fetch(url)[0] == PNG


async def test_art_requires_a_credential(client):
    assert (await client.get("/api/art?k=abc")).status == 401


async def test_an_unknown_key_is_a_404(client):
    assert (await client.get("/api/art?k=abc", headers=HEADERS)).status == 404


async def test_a_known_key_serves_the_image(client, tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(PNG)
    key = art.key_for(cover.as_uri())

    resp = await client.get(f"/api/art?k={key}", headers=HEADERS)

    assert resp.status == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert await resp.read() == PNG


async def test_the_policy_lets_a_blob_image_render(client):
    """Art and screenshots are object URLs, and img-src must say so.

    An <img src> cannot carry the credential these endpoints require, so the
    page fetches the bytes and hands the <img> a blob: URL. With img-src
    limited to 'self' and data:, every one of those rendered as the browser's
    broken-image placeholder.
    """
    policy = (await client.get("/")).headers["Content-Security-Policy"]
    img = [part for part in policy.split("; ") if part.startswith("img-src")][0]
    assert "blob:" in img
