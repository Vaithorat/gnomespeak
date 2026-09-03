"""Tests for the PC noticing that the phone is nearly flat.

The rule is that a crossing is an event and a level is a state: a phone sitting
at 8% reports every few seconds, and a banner per report would be worse than no
banner at all.
"""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt.live import PhoneRegistry
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


def test_a_healthy_battery_says_nothing():
    phones = PhoneRegistry()
    assert phones.report("ws", "Pixel", 0.8, False) is False


def test_crossing_into_low_is_reported_once():
    phones = PhoneRegistry()
    assert phones.report("ws", "Pixel", 0.20, False) is False
    assert phones.report("ws", "Pixel", 0.12, False) is True
    assert phones.report("ws", "Pixel", 0.11, False) is False
    assert phones.report("ws", "Pixel", 0.08, False) is False


def test_a_phone_on_charge_is_not_low():
    phones = PhoneRegistry()
    assert phones.report("ws", "Pixel", 0.05, True) is False


def test_plugging_in_and_out_can_report_again():
    """Charging clears the state, so the next fall is a new crossing."""
    phones = PhoneRegistry()
    phones.report("ws", "Pixel", 0.10, False)
    phones.report("ws", "Pixel", 0.10, True)
    assert phones.report("ws", "Pixel", 0.09, False) is True


def test_two_phones_are_tracked_apart():
    phones = PhoneRegistry()
    assert phones.report("a", "Pixel", 0.10, False) is True
    assert phones.report("b", "Nokia", 0.10, False) is True
    assert phones.report("a", "Pixel", 0.09, False) is False


def test_a_phone_that_left_starts_over():
    phones = PhoneRegistry()
    phones.report("ws", "Pixel", 0.10, False)
    phones.forget("ws")
    assert phones.report("ws", "Pixel", 0.10, False) is True


def test_the_level_is_still_what_the_row_shows():
    phones = PhoneRegistry()
    phones.report("ws", "Pixel", 0.42, False)
    entry = phones.entries()[0]
    assert entry["level"] == 0.42 and entry["name"] == "Pixel"


async def test_a_low_battery_raises_a_banner_on_the_pc(client, monkeypatch):
    shown = []
    monkeypatch.setattr("vt.server.notify",
                        lambda summary, body="", urgency="normal": shown.append((summary, body)))

    reply = await client.post("/api/ws-ticket", headers={"X-VT-Token": "test-token"})
    ticket = (await reply.json())["ticket"]
    ws = await client.ws_connect(f"/ws?ticket={ticket}")
    await ws.receive_json()

    await ws.send_json({"type": "battery", "level": 0.09, "charging": False})
    await ws.send_json({"type": "ping"})
    await ws.receive_json()   # the pong, by which time the battery was handled
    await ws.close()

    assert len(shown) == 1
    assert "battery low" in shown[0][0]
    assert "9%" in shown[0][1]


async def test_a_healthy_battery_raises_nothing(client, monkeypatch):
    shown = []
    monkeypatch.setattr("vt.server.notify",
                        lambda summary, body="", urgency="normal": shown.append(summary))

    reply = await client.post("/api/ws-ticket", headers={"X-VT-Token": "test-token"})
    ticket = (await reply.json())["ticket"]
    ws = await client.ws_connect(f"/ws?ticket={ticket}")
    await ws.receive_json()

    await ws.send_json({"type": "battery", "level": 0.85, "charging": False})
    await ws.send_json({"type": "ping"})
    await ws.receive_json()
    await ws.close()

    assert shown == []


# --- and the other direction: the PC telling the phone -----------------------

def battery(monkeypatch, percent, charging):
    monkeypatch.setattr(
        "vt.sources.system.battery_state",
        lambda: {"percent": percent, "charging": charging, "present": True},
    )


async def test_the_pc_tells_the_phone_when_it_is_nearly_flat(client, monkeypatch):
    battery(monkeypatch, 9, False)
    assert client.vt._battery_alert()["kind"] == "battery"


async def test_it_says_so_once(client, monkeypatch):
    battery(monkeypatch, 9, False)
    assert client.vt._battery_alert()
    assert client.vt._battery_alert() == {}


async def test_a_charging_pc_is_not_low(client, monkeypatch):
    battery(monkeypatch, 5, True)
    assert client.vt._battery_alert() == {}


async def test_plugging_in_and_out_alerts_again(client, monkeypatch):
    battery(monkeypatch, 9, False)
    client.vt._battery_alert()
    battery(monkeypatch, 9, True)
    client.vt._battery_alert()
    battery(monkeypatch, 8, False)
    assert client.vt._battery_alert()


async def test_a_desktop_with_no_battery_says_nothing(client, monkeypatch):
    monkeypatch.setattr("vt.sources.system.battery_state", dict)
    assert client.vt._battery_alert() == {}


async def test_the_alert_reaches_a_connected_phone(client, monkeypatch):
    battery(monkeypatch, 9, False)
    reply = await client.post("/api/ws-ticket", headers={"X-VT-Token": "test-token"})
    ticket = (await reply.json())["ticket"]
    ws = await client.ws_connect(f"/ws?ticket={ticket}")
    await ws.receive_json()

    await client.vt.live.broadcast(client.vt._battery_alert())
    message = await ws.receive_json()
    await ws.close()

    assert message["type"] == "alert"
    assert "9%" in message["message"]
