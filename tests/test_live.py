"""Tests for the live channel: tickets, patches, and the socket route.

No real phone and no real socket in the hub tests: a connection is anything
with `send_json`, which is the whole reason the fan-out lives apart from the
server. The route tests do open a socket, through aiohttp's test client, to
prove the ticket is the only way in.
"""

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt.live import LiveHub, TicketStore, diff_targets
from vt.model import Action, Snapshot, Target
from vt.server import VoiceTalkServer


def make_server(tmp_path, **kwargs) -> VoiceTalkServer:
    kwargs.setdefault("token", "test-token")
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


class FakeClient:
    """A connection that records what it was sent."""

    def __init__(self, fail: bool = False):
        self.sent = []
        self.fail = fail
        self.closed = False

    async def send_json(self, message):
        if self.fail:
            raise ConnectionResetError("gone")
        self.sent.append(message)

    async def close(self):
        self.closed = True


def snapshot(*targets) -> Snapshot:
    return Snapshot(targets=list(targets), ts=1.0)


def player(title="Cars 2", status="playing") -> Target:
    return Target(
        id="mpris:firefox", kind="player", title=title, status=status,
        actions=[Action(id="play_pause", label="Pause")],
    )


# --- tickets ----------------------------------------------------------------

def test_a_ticket_yields_its_principal_once():
    store = TicketStore()
    ticket = store.issue({"kind": "device", "id": "abc", "name": "phone", "ip": "10.0.0.2"})

    first = store.redeem(ticket)
    assert first["id"] == "abc"
    # Single use is what makes a ticket safe in a URL: replaying one out of a
    # proxy log gets a second caller nothing.
    assert store.redeem(ticket) is None


def test_an_expired_ticket_is_refused():
    store = TicketStore(ttl=-1.0)
    assert store.redeem(store.issue({"id": "abc"})) is None


def test_an_unknown_ticket_is_refused():
    assert TicketStore().redeem("not-a-ticket") is None


def test_expired_tickets_do_not_accumulate():
    store = TicketStore(ttl=-1.0)
    for _ in range(5):
        store.issue({"id": "abc"})
    assert len(store) == 0


# --- diffing ----------------------------------------------------------------

def test_diff_reports_only_what_moved():
    before = {"a": {"id": "a", "status": "playing"}, "b": {"id": "b"}}
    after = {"a": {"id": "a", "status": "paused"}, "c": {"id": "c"}}
    changed, removed = diff_targets(before, after)
    assert [t["id"] for t in changed] == ["a", "c"]
    assert removed == ["b"]


def test_diff_sees_a_field_it_was_never_told_about():
    """Targets grow fields; a diff that listed them would silently miss one."""
    changed, removed = diff_targets({"a": {"id": "a"}}, {"a": {"id": "a", "battery": 40}})
    assert changed and removed == []


# --- the hub ----------------------------------------------------------------

async def test_a_new_connection_is_handed_the_whole_state():
    hub = LiveHub()
    hub.seed(snapshot(player()))
    phone = FakeClient()

    await hub.add(phone)

    assert phone.sent[0]["type"] == "state"
    assert [t["id"] for t in phone.sent[0]["targets"]] == ["mpris:firefox"]


async def test_a_change_arrives_as_a_patch_not_a_snapshot():
    hub = LiveHub()
    hub.seed(snapshot(player(status="playing")))
    phone = FakeClient()
    await hub.add(phone)

    await hub.publish(snapshot(player(status="paused")))

    patch = phone.sent[-1]
    assert patch["type"] == "patch"
    assert patch["changed"][0]["status"] == "paused"
    assert patch["removed"] == []


async def test_an_unchanged_snapshot_sends_nothing():
    """The whole point: a quiet PC costs no traffic at all."""
    hub = LiveHub()
    hub.seed(snapshot(player()))
    phone = FakeClient()
    await hub.add(phone)
    before = len(phone.sent)

    reached = await hub.publish(snapshot(player()))

    assert reached == 0
    assert len(phone.sent) == before


async def test_a_disappearing_target_is_named_in_removed():
    hub = LiveHub()
    hub.seed(snapshot(player()))
    phone = FakeClient()
    await hub.add(phone)

    await hub.publish(snapshot())

    assert phone.sent[-1]["removed"] == ["mpris:firefox"]


async def test_a_client_that_joined_mid_stream_gets_a_snapshot():
    """A patch it cannot apply would leave it wrong with no way to notice."""
    hub = LiveHub()
    hub.seed(snapshot(player(status="playing")))
    early = FakeClient()
    await hub.add(early)
    await hub.publish(snapshot(player(status="paused")))

    late = FakeClient()
    late.sent.clear()
    hub._clients[late] = -1          # a client that missed a publish
    await hub.publish(snapshot(player(title="Cars 3", status="paused")))

    assert late.sent[-1]["type"] == "state"
    assert early.sent[-1]["type"] == "patch"


async def test_reordering_alone_is_published():
    """The phone renders in the order it is given; order is state too."""
    hub = LiveHub()
    a = Target(id="a", kind="app", title="A")
    b = Target(id="b", kind="app", title="B")
    hub.seed(snapshot(a, b))
    phone = FakeClient()
    await hub.add(phone)

    await hub.publish(snapshot(b, a))

    assert phone.sent[-1]["order"] == ["b", "a"]


async def test_a_dead_connection_is_dropped_not_retried():
    hub = LiveHub()
    hub.seed(snapshot(player()))
    dead = FakeClient(fail=True)
    hub._clients[dead] = 0

    await hub.publish(snapshot(player(status="paused")))

    assert len(hub) == 0


async def test_close_all_closes_every_connection():
    hub = LiveHub()
    phone = FakeClient()
    await hub.add(phone)

    await hub.close_all()

    assert phone.closed and len(hub) == 0


# --- the route --------------------------------------------------------------

async def test_a_ticket_requires_a_credential(client):
    resp = await client.post("/api/ws-ticket")
    assert resp.status == 401


async def test_the_socket_refuses_a_missing_ticket(client):
    resp = await client.get("/ws")
    assert resp.status == 401


async def test_the_socket_refuses_a_reused_ticket(client):
    ticket = (await (await client.post(
        "/api/ws-ticket", headers={"X-VT-Token": "test-token"}
    )).json())["ticket"]

    async with client.ws_connect(f"/ws?ticket={ticket}") as ws:
        assert (await ws.receive_json())["type"] == "state"

    resp = await client.get(f"/ws?ticket={ticket}")
    assert resp.status == 401


async def test_the_socket_delivers_a_change(client):
    ticket = (await (await client.post(
        "/api/ws-ticket", headers={"X-VT-Token": "test-token"}
    )).json())["ticket"]

    async with client.ws_connect(f"/ws?ticket={ticket}") as ws:
        await ws.receive_json()
        await client.vt.live.publish(snapshot(player()))
        message = await asyncio.wait_for(ws.receive_json(), timeout=5)

    assert message["changed"][0]["id"] == "mpris:firefox"


async def test_resync_asks_for_the_whole_state_back(client):
    ticket = (await (await client.post(
        "/api/ws-ticket", headers={"X-VT-Token": "test-token"}
    )).json())["ticket"]

    async with client.ws_connect(f"/ws?ticket={ticket}") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "resync"})
        assert (await asyncio.wait_for(ws.receive_json(), timeout=5))["type"] == "state"


async def test_pointer_input_rides_the_socket(client, monkeypatch):
    calls = []

    def fake_execute(op, data):
        calls.append((op, data))
        return {"ok": True}

    import vt.sources.remote_input as remote_input
    monkeypatch.setattr(remote_input, "execute", fake_execute)

    ticket = (await (await client.post(
        "/api/ws-ticket", headers={"X-VT-Token": "test-token"}
    )).json())["ticket"]

    async with client.ws_connect(f"/ws?ticket={ticket}") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "input", "op": "move", "dx": 3, "dy": -2, "id": 7})
        reply = await asyncio.wait_for(ws.receive_json(), timeout=5)

    assert calls[0][0] == "move"
    assert reply["type"] == "input_result" and reply["id"] == 7


async def test_typing_over_the_socket_is_audited(client, monkeypatch):
    """The socket must not become the unaudited way in."""
    import vt.sources.remote_input as remote_input
    monkeypatch.setattr(remote_input, "execute", lambda op, data: {"ok": True})

    ticket = (await (await client.post(
        "/api/ws-ticket", headers={"X-VT-Token": "test-token"}
    )).json())["ticket"]

    async with client.ws_connect(f"/ws?ticket={ticket}") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "input", "op": "type", "text": "hello", "id": 1})
        await asyncio.wait_for(ws.receive_json(), timeout=5)

    assert "input" in client.vt.auth.audit.path.read_text()


async def test_the_poll_still_serves_the_same_snapshot(client):
    """A browser that never opens a socket must not lose anything."""
    resp = await client.get("/api/state", headers={"X-VT-Token": "test-token"})
    assert resp.status == 200
    assert "targets" in await resp.json()


# --- phone battery and ringing ----------------------------------------------

async def test_a_phone_battery_becomes_a_target(client):
    ticket = (await (await client.post(
        "/api/ws-ticket", headers={"X-VT-Token": "test-token"}
    )).json())["ticket"]

    async with client.ws_connect(f"/ws?ticket={ticket}") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "battery", "level": 0.42, "charging": True})
        await ws.send_json({"type": "ping"})
        await asyncio.wait_for(ws.receive_json(), timeout=5)
        targets = client.vt._phone_targets()

    assert targets[0].subtitle == "42% · charging"


async def test_a_phone_that_leaves_stops_being_a_target(client):
    ticket = (await (await client.post(
        "/api/ws-ticket", headers={"X-VT-Token": "test-token"}
    )).json())["ticket"]

    async with client.ws_connect(f"/ws?ticket={ticket}") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "battery", "level": 0.9, "charging": False})
        await ws.send_json({"type": "ping"})
        await asyncio.wait_for(ws.receive_json(), timeout=5)

    for _ in range(50):
        await asyncio.sleep(0.02)
        if not client.vt._phone_targets():
            break
    assert client.vt._phone_targets() == []


async def test_ringing_reaches_the_pc(client, monkeypatch):
    import vt.sources.ring as ring_mod
    monkeypatch.setattr(ring_mod, "ring", lambda: {"ok": True, "message": "Ringing the PC"})

    ticket = (await (await client.post(
        "/api/ws-ticket", headers={"X-VT-Token": "test-token"}
    )).json())["ticket"]

    async with client.ws_connect(f"/ws?ticket={ticket}") as ws:
        await ws.receive_json()
        await ws.send_json({"type": "ring"})
        reply = await asyncio.wait_for(ws.receive_json(), timeout=5)

    assert reply["type"] == "ring_result" and reply["ok"]


# --- notifications on the socket ---------------------------------------------

async def test_broadcast_reaches_every_client():
    hub = LiveHub()
    a, b = FakeClient(), FakeClient()
    await hub.add(a)
    await hub.add(b)
    a.sent.clear()
    b.sent.clear()

    reached = await hub.broadcast({"type": "notification", "entries": []})

    assert reached == 2
    assert a.sent == b.sent == [{"type": "notification", "entries": []}]


async def test_a_broadcast_does_not_move_the_patch_sequence():
    hub = LiveHub()
    client = FakeClient()
    await hub.add(client)
    before = hub.state_message()["seq"]

    await hub.broadcast({"type": "notification", "entries": [{"seq": 1}]})

    assert hub.state_message()["seq"] == before


async def test_a_client_that_died_is_dropped_by_a_broadcast():
    hub = LiveHub()
    gone = FakeClient(fail=True)
    hub._clients[gone] = 0

    assert await hub.broadcast({"type": "notification", "entries": []}) == 0
    assert len(hub) == 0


def test_the_mirror_hands_each_notification_to_its_listener():
    from vt.sources.notifications_mirror import NotificationMirror

    seen = []
    mirror = NotificationMirror()
    mirror.on_entry = seen.append
    mirror._record(["Firefox", "icon", "A summary", "A body"], serial=7)

    assert [e["summary"] for e in seen] == ["A summary"]


def test_a_listener_that_throws_does_not_stop_the_reader():
    from vt.sources.notifications_mirror import NotificationMirror

    def explode(entry):
        raise RuntimeError("the loop is gone")

    mirror = NotificationMirror()
    mirror.on_entry = explode
    mirror._record(["Firefox", "icon", "A summary", ""], serial=7)

    assert len(mirror.entries()) == 1


async def test_a_notification_is_pushed_to_the_socket(client, monkeypatch):
    monkeypatch.setattr(client.vt, "NOTIFICATION_SETTLE", 0.01)
    reply = await client.post("/api/ws-ticket", headers={"X-VT-Token": "test-token"})
    ticket = (await reply.json())["ticket"]
    ws = await client.ws_connect(f"/ws?ticket={ticket}")
    await ws.receive_json()  # the opening state message

    entry = {"seq": 4, "ts": 1.0, "app": "Firefox", "icon": "", "summary": "Hi",
             "body": "", "id": 0}
    client.vt._queue_notification(entry)
    # The id lands during the settle, exactly as the daemon's reply does.
    entry["id"] = 11

    message = await ws.receive_json()
    assert message["type"] == "notification"
    assert message["entries"][0]["summary"] == "Hi"
    # Pushed after the settle, so the phone gets an id it can dismiss with.
    assert message["entries"][0]["id"] == 11
    await ws.close()


async def test_nothing_is_pushed_when_no_phone_is_connected(client):
    client.vt._queue_notification({"seq": 1, "summary": "Hi"})
    await client.vt._notification_task
    assert client.vt._pending_notifications == []
