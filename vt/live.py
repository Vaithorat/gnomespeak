"""The live channel: one WebSocket per phone, patches instead of polls.

The UI was built on a 1 Hz GET of the whole snapshot. That is a full target
list -- players, windows, workspaces, system rows -- every second, on a phone
that is usually looking at one screen and usually seeing nothing change. Over a
Cloudflare tunnel on mobile data it is the single largest cost the product has,
and it also puts a hard floor of one second under every reaction: pressing pause
on the PC cannot show on the phone sooner than the next poll.

This module holds the two pieces that fix it and nothing else, so both can be
tested without a socket:

  * `TicketStore`, because a browser cannot set headers on a WebSocket
    handshake. The credential the REST routes require is exchanged, over an
    authenticated POST, for a single-use ticket with a few seconds to live.
    A URL is the only place a WebSocket can carry anything, and a URL is the
    one place a long-lived device secret must never go.
  * `LiveHub`, which turns a sequence of snapshots into per-connection patches.

The poll is not removed. A browser that cannot hold a socket, or a network that
eats one, falls back to it -- which is why `/api/state` keeps serving the same
snapshot to anyone who never opens a socket.
"""

import asyncio
import secrets
import time

# Long enough to survive a slow handshake over a tunnel, short enough that a
# ticket in a proxy log or a browser history is worthless by the time anyone
# reads it. Tickets are single-use on top of this.
TICKET_TTL = 30.0


class TicketStore:
    """Single-use, short-lived tickets standing in for a credential in a URL."""

    def __init__(self, ttl: float = TICKET_TTL):
        self.ttl = ttl
        self._tickets: dict[str, tuple[float, dict]] = {}

    def issue(self, principal: dict) -> str:
        self._prune()
        ticket = secrets.token_urlsafe(24)
        self._tickets[ticket] = (time.monotonic() + self.ttl, dict(principal))
        return ticket

    def redeem(self, ticket: str):
        """The principal that was issued this ticket, or None. Consumes it."""
        self._prune()
        entry = self._tickets.pop(ticket, None)
        if entry is None:
            return None
        expires, principal = entry
        if expires < time.monotonic():
            return None
        return principal

    def _prune(self):
        now = time.monotonic()
        for ticket, (expires, _) in list(self._tickets.items()):
            if expires < now:
                del self._tickets[ticket]

    def __len__(self) -> int:
        self._prune()
        return len(self._tickets)


class PhoneRegistry:
    """What the phones on the live channel have said about themselves.

    Only possible over a socket: a poll asks the PC about the PC, and nothing
    in it ever travels the other way. The entries live and die with their
    connection, so a phone that closes the tab stops being on the PC's screen.
    """

    # Below this, and not charging, the PC says something once. The phone's own
    # warning is easy to miss from across the room, which is the entire reason
    # this direction exists.
    LOW_BATTERY = 0.15

    def __init__(self):
        self._phones: dict = {}

    def report(self, connection, name: str, level: float, charging: bool) -> bool:
        """Record a phone's battery. True when this crossed into "low".

        Only the crossing, never the state: a phone sitting at 8% reports every
        few seconds, and a notification per report would be worse than none.
        """
        level = max(0.0, min(1.0, float(level)))
        charging = bool(charging)
        previous = self._phones.get(connection)
        was_low = bool(previous and previous.get("low"))
        low = level <= self.LOW_BATTERY and not charging

        self._phones[connection] = {
            "name": name or "Phone",
            "level": level,
            "charging": charging,
            "ts": time.time(),
            "low": low,
        }
        return low and not was_low

    def forget(self, connection) -> None:
        self._phones.pop(connection, None)

    def entries(self) -> list:
        return list(self._phones.values())


def diff_targets(previous: dict, current: dict) -> tuple:
    """(changed targets, removed ids) between two id -> target-dict maps.

    Changed means new or not equal. Comparing the dicts whole rather than
    field by field is what keeps this honest as targets grow fields: a new key
    that nothing here knows about still counts as a change.
    """
    changed = [t for tid, t in current.items() if previous.get(tid) != t]
    removed = [tid for tid in previous if tid not in current]
    return changed, removed


class LiveHub:
    """Fans snapshot changes out to every open connection.

    A connection is anything with an async `send_json(dict)`; the socket lives
    in the server, so this can be driven by a list in a test.

    Every message carries a sequence number, and every patch also carries the
    sequence it applies to. A connection that is not on that sequence -- one
    that joined mid-tick, or whose send failed once -- is sent a whole snapshot
    instead of a patch it could not apply. The client therefore never has to
    detect that it has drifted; drift is not representable.
    """

    def __init__(self):
        self._clients: dict = {}          # client -> last seq that client holds
        self._targets: dict = {}          # id -> target dict, as last published
        self._order: list = []
        self._ts: float = 0.0
        self._seq: int = 0

    # --- membership ---------------------------------------------------------

    async def add(self, client) -> None:
        """Register a connection and hand it the current state."""
        self._clients[client] = self._seq
        await client.send_json(self.state_message())

    def remove(self, client) -> None:
        self._clients.pop(client, None)

    def __len__(self) -> int:
        return len(self._clients)

    # --- messages -----------------------------------------------------------

    def state_message(self) -> dict:
        """The whole snapshot, as sent on connect and after any drift."""
        return {
            "type": "state",
            "seq": self._seq,
            "ts": self._ts,
            "targets": [self._targets[tid] for tid in self._order if tid in self._targets],
        }

    def seed(self, snapshot) -> None:
        """Adopt a snapshot without sending anything.

        The server already keeps a snapshot refreshed on a timer, and a hub
        that started empty would send every connection a state message saying
        the PC has nothing on it, one tick before the truth arrived.
        """
        data = snapshot.to_dict()
        self._targets = {t["id"]: t for t in data["targets"]}
        self._order = [t["id"] for t in data["targets"]]
        self._ts = data["ts"]

    async def publish(self, snapshot) -> int:
        """Send what changed since the last publish. Returns clients reached."""
        data = snapshot.to_dict()
        current = {t["id"]: t for t in data["targets"]}
        order = [t["id"] for t in data["targets"]]
        changed, removed = diff_targets(self._targets, current)
        reordered = order != self._order

        base = self._seq
        self._targets = current
        self._order = order
        self._ts = data["ts"]

        if not changed and not removed and not reordered:
            # Nothing moved on the PC. Saying so costs a message per second per
            # phone, which is the poll again wearing a socket. The heartbeat
            # aiohttp already sends is what keeps the connection honest.
            return 0

        self._seq += 1
        patch = {
            "type": "patch",
            "seq": self._seq,
            "base": base,
            "ts": self._ts,
            "changed": changed,
            "removed": removed,
            "order": order,
        }
        state = self.state_message()

        reached = 0
        for client, held in list(self._clients.items()):
            message = patch if held == base else state
            try:
                await client.send_json(message)
            except Exception:
                # A phone that walked out of range. The socket's own close will
                # arrive eventually; dropping it here stops it from holding up
                # everyone else in the meantime.
                self._clients.pop(client, None)
                continue
            self._clients[client] = self._seq
            reached += 1
        return reached

    async def broadcast(self, message: dict) -> int:
        """Send one message to every connection, outside the patch sequence.

        Notifications are events, not state: they happen once, they are not
        part of the snapshot, and replaying them on reconnect would show a
        banner twice. So they travel beside the patches rather than in them,
        and a client that misses one has lost an event rather than drifted.
        """
        reached = 0
        for client in list(self._clients):
            try:
                await client.send_json(message)
            except Exception:
                self._clients.pop(client, None)
                continue
            reached += 1
        return reached

    async def close_all(self) -> None:
        for client in list(self._clients):
            close = getattr(client, "close", None)
            if close is None:
                continue
            try:
                result = close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass
        self._clients.clear()
