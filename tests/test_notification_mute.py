"""Tests for silencing one app's notifications.

A mute is "not tonight", not a settings screen: it lives in memory, it dies
with the server, and it drops the app's notifications before they reach the
socket, the poll, or the list -- because a mute that only hid rows on the phone
would still be spending a message on every one of them.
"""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt.server import VoiceTalkServer
from vt.sources.notifications_mirror import NotificationMirror

AUTH = {"X-VT-Token": "test-token"}


def notify(mirror, app, summary="Something", serial=0):
    mirror._record([app, "icon", summary, ""], serial=serial)


@pytest.fixture
async def client(tmp_path, monkeypatch):
    server = VoiceTalkServer(
        "127.0.0.1", 0, token="test-token",
        devices_path=tmp_path / "devices.json",
        audit_path=tmp_path / "audit.log",
        codes_path=tmp_path / "pairing.json",
    )
    from vt.sources import notifications_mirror

    fresh = NotificationMirror()
    fresh._started = True          # nothing to start: no dbus-monitor in a test
    monkeypatch.setattr(notifications_mirror, "_mirror", fresh)
    async with TestClient(TestServer(server.make_app())) as c:
        c.vt = server
        c.mirror = fresh
        yield c


def test_a_muted_app_stops_arriving():
    mirror = NotificationMirror()
    mirror.mute("Slack")
    notify(mirror, "Slack")
    notify(mirror, "Firefox")
    assert [e["app"] for e in mirror.entries()] == ["Firefox"]


def test_muting_clears_the_backlog_that_app_just_made():
    mirror = NotificationMirror()
    notify(mirror, "Slack", "one")
    notify(mirror, "Slack", "two")
    notify(mirror, "Firefox", "keep me")

    mirror.mute("Slack")

    assert [e["summary"] for e in mirror.entries()] == ["keep me"]


def test_a_muted_app_never_reaches_the_listener():
    """The point is the message not being sent, not the row being hidden."""
    pushed = []
    mirror = NotificationMirror()
    mirror.on_entry = pushed.append
    mirror.mute("Slack")

    notify(mirror, "Slack")

    assert pushed == []


def test_unmuting_lets_it_back():
    mirror = NotificationMirror()
    mirror.mute("Slack")
    assert mirror.unmute("Slack") is True
    notify(mirror, "Slack")
    assert [e["app"] for e in mirror.entries()] == ["Slack"]


def test_muting_twice_is_not_an_error():
    mirror = NotificationMirror()
    assert mirror.mute("Slack") is True
    assert mirror.mute("Slack") is False
    assert mirror.muted() == ["Slack"]


def test_unmuting_something_that_was_not_muted():
    mirror = NotificationMirror()
    assert mirror.unmute("Slack") is False


def test_an_empty_name_mutes_nothing():
    mirror = NotificationMirror()
    assert mirror.mute("  ") is False
    assert mirror.muted() == []


async def test_the_endpoint_mutes_and_unmutes(client):
    resp = await client.post("/api/notifications/mute",
                             json={"app": "Slack"}, headers=AUTH)
    body = await resp.json()
    assert body["ok"] is True and body["muted"] == ["Slack"]

    resp = await client.post("/api/notifications/mute",
                             json={"app": "Slack", "muted": False}, headers=AUTH)
    assert (await resp.json())["muted"] == []


async def test_the_list_says_what_is_muted(client):
    client.mirror.mute("Slack")
    body = await (await client.get("/api/notifications", headers=AUTH)).json()
    assert body["muted"] == ["Slack"]


async def test_muting_needs_an_app(client):
    resp = await client.post("/api/notifications/mute", json={}, headers=AUTH)
    assert resp.status == 400


async def test_muting_is_audited(client):
    await client.post("/api/notifications/mute", json={"app": "Slack"}, headers=AUTH)
    assert "notifications.mute" in [e["event"] for e in client.vt.auth.audit.tail(10)]


async def test_muting_needs_a_credential(client):
    assert (await client.post("/api/notifications/mute", json={"app": "Slack"})).status == 401
