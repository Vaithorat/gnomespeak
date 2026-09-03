"""Tests for ringing the PC, and for being able to stop it again.

Nothing here makes a sound: the player is swapped for `sleep`, which is the
same shape of process -- one that runs for a while and can be terminated --
without needing a speaker on the machine running the tests.
"""

import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

import vt.sources.ring as ring_mod
from vt.server import VoiceTalkServer
from vt.sources.system import execute as execute_system
from vt.sources.system import get_system_targets


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    """A player that makes no noise, and no desktop banner during a test run."""
    monkeypatch.setattr(ring_mod, "player_argv", lambda: ["sleep", "5"])
    monkeypatch.setattr(ring_mod, "_banner", lambda: True)
    monkeypatch.setattr(ring_mod, "_ringer", ring_mod._Ringer())
    yield
    ring_mod._ringer.stop()


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_ringing_returns_before_the_sound_finishes():
    started = time.monotonic()
    result = ring_mod.ring()
    assert result["ok"]
    # The player sleeps for five seconds; the call must not.
    assert time.monotonic() - started < 1.0
    assert wait_until(ring_mod.ringing)


def test_stop_silences_a_ring_in_progress():
    ring_mod.ring()
    assert wait_until(ring_mod.ringing)
    assert ring_mod.stop() == {"ok": True, "message": "Stopped ringing"}
    assert not ring_mod.ringing()


def test_stopping_a_quiet_pc_is_not_an_error():
    assert ring_mod.stop() == {"ok": True, "message": "It is not ringing"}


def test_a_second_ring_does_not_start_a_second_thread():
    ring_mod.ring()
    assert wait_until(ring_mod.ringing)
    assert ring_mod.ring()["message"] == "Already ringing"


def test_the_ring_stops_itself_at_the_deadline():
    ring_mod.ring(seconds=0.1)
    assert wait_until(lambda: not ring_mod.ringing(), timeout=5.0)


def test_a_pc_with_no_player_still_shows_a_banner(monkeypatch):
    monkeypatch.setattr(ring_mod, "player_argv", list)
    result = ring_mod.ring()
    assert result["ok"] and "banner" in result["message"]
    assert not ring_mod.ringing()


def ring_target():
    return next(t for t in get_system_targets() if t.id == "system:ring")


def test_the_button_says_ring_when_the_pc_is_quiet():
    assert [a.id for a in ring_target().actions] == ["ring"]
    assert ring_target().status == "ready"


def test_the_button_says_stop_while_the_pc_is_ringing():
    ring_mod.ring()
    assert wait_until(ring_mod.ringing)
    target = ring_target()
    assert [a.id for a in target.actions] == ["stop"]
    assert target.status == "ringing"


def test_the_system_source_dispatches_stop():
    execute_system("ring", "ring")
    assert wait_until(ring_mod.ringing)
    assert execute_system("ring", "stop")["ok"]
    assert not ring_mod.ringing()


def test_an_unknown_ring_action_is_refused():
    assert not execute_system("ring", "vibrate")["ok"]


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


async def open_live(client):
    reply = await client.post("/api/ws-ticket", headers={"X-VT-Token": "test-token"})
    ticket = (await reply.json())["ticket"]
    ws = await client.ws_connect(f"/ws?ticket={ticket}")
    await ws.receive_json()  # the opening state message
    return ws


async def test_the_live_channel_can_stop_a_ring(client):
    ws = await open_live(client)
    await ws.send_json({"type": "ring"})
    assert (await ws.receive_json())["ok"]
    assert wait_until(ring_mod.ringing)

    await ws.send_json({"type": "ring_stop"})
    reply = await ws.receive_json()
    assert reply["type"] == "ring_result" and reply["ok"]
    assert not ring_mod.ringing()
    await ws.close()


async def test_the_stop_flag_works_on_a_plain_ring_message(client):
    ws = await open_live(client)
    await ws.send_json({"type": "ring"})
    await ws.receive_json()
    assert wait_until(ring_mod.ringing)

    await ws.send_json({"type": "ring", "stop": True})
    assert (await ws.receive_json())["message"] == "Stopped ringing"
    assert not ring_mod.ringing()
    await ws.close()
