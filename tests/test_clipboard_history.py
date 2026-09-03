"""Tests for the last few things copied on the PC.

The feature is small; the limits are the point. Nothing reaches disk, the list
stays short, the watch starts only when the screen asks for it, and there is a
button that forgets everything -- because a clipboard sometimes holds a
password and the history would otherwise outlive the moment.
"""

import time

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt.server import VoiceTalkServer
from vt.sources.clipboard_history import ClipboardHistory, MAX_ENTRIES, MAX_TEXT

AUTH = {"X-VT-Token": "test-token"}


@pytest.fixture
async def client(tmp_path, monkeypatch):
    server = VoiceTalkServer(
        "127.0.0.1", 0, token="test-token",
        devices_path=tmp_path / "devices.json",
        audit_path=tmp_path / "audit.log",
        codes_path=tmp_path / "pairing.json",
    )
    # A history that never starts a thread against the developer's real clipboard.
    from vt.sources import clipboard_history

    fresh = ClipboardHistory(reader=lambda: {"ok": True, "text": ""})
    monkeypatch.setattr(clipboard_history, "_history", fresh)
    async with TestClient(TestServer(server.make_app())) as c:
        c.vt = server
        c.history = fresh
        yield c


def test_a_clip_is_kept():
    history = ClipboardHistory(reader=lambda: {"ok": True, "text": ""})
    assert history.record("hello") is True
    assert [e["text"] for e in history.entries()] == ["hello"]


def test_copying_the_same_thing_twice_keeps_one():
    history = ClipboardHistory(reader=lambda: {"ok": True, "text": ""})
    history.record("hello")
    assert history.record("hello") is False
    assert len(history.entries()) == 1


def test_copying_an_old_thing_again_moves_it_to_the_top():
    """A, B, A means A is the newest thing, and the phone should see that."""
    history = ClipboardHistory(reader=lambda: {"ok": True, "text": ""})
    history.record("a")
    history.record("b")
    history.record("a")
    assert [e["text"] for e in history.entries()] == ["a", "b", "a"]


def test_whitespace_is_not_a_clip():
    history = ClipboardHistory(reader=lambda: {"ok": True, "text": ""})
    assert history.record("   \n ") is False
    assert history.entries() == []


def test_the_list_stays_short():
    history = ClipboardHistory(reader=lambda: {"ok": True, "text": ""})
    for i in range(MAX_ENTRIES + 10):
        history.record(f"clip {i}")
    assert len(history.entries()) == MAX_ENTRIES


def test_a_document_is_stored_as_a_preview():
    history = ClipboardHistory(reader=lambda: {"ok": True, "text": ""})
    history.record("x" * (MAX_TEXT + 500))
    entry = history.entries()[0]
    assert len(entry["text"]) == MAX_TEXT
    assert entry["truncated"] is True
    assert entry["length"] == MAX_TEXT + 500


def test_forgetting_leaves_nothing():
    history = ClipboardHistory(reader=lambda: {"ok": True, "text": ""})
    history.record("a password")
    assert history.clear() == 1
    assert history.entries() == []


def test_the_watch_picks_up_what_was_copied():
    clips = iter(["one", "one", "two"])
    current = {"text": "one"}

    def reader():
        current["text"] = next(clips, current["text"])
        return {"ok": True, "text": current["text"]}

    history = ClipboardHistory(reader=reader, poll_seconds=0.01)
    history.start()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and len(history.entries()) < 2:
        time.sleep(0.02)
    history.stop()

    assert [e["text"] for e in history.entries()] == ["two", "one"]
    assert not history.running


def test_a_clipboard_that_cannot_be_read_says_why():
    history = ClipboardHistory(
        reader=lambda: {"ok": False, "message": "wl-paste is not installed"},
        poll_seconds=0.01,
    )
    history.start()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not history.error:
        time.sleep(0.02)
    history.stop()
    assert "wl-paste" in history.error


def test_starting_twice_runs_one_watch():
    history = ClipboardHistory(reader=lambda: {"ok": True, "text": ""}, poll_seconds=0.05)
    history.start()
    history.start()
    running = history._thread
    assert history.start() and history._thread is running
    history.stop()


async def test_the_endpoint_lists_what_was_copied(client):
    client.history.record("from the PC")
    body = await (await client.get("/api/clipboard/history", headers=AUTH)).json()
    assert [e["text"] for e in body["entries"]] == ["from the PC"]


async def test_what_the_phone_sends_joins_the_history(client, monkeypatch):
    monkeypatch.setattr(
        "vt.sources.clipboard.write_text",
        lambda text: {"ok": True, "message": "Copied"},
    )
    await client.post("/api/clipboard", json={"text": "from the phone"}, headers=AUTH)
    assert [e["text"] for e in client.history.entries()] == ["from the phone"]


async def test_a_failed_write_does_not_join_the_history(client, monkeypatch):
    monkeypatch.setattr(
        "vt.sources.clipboard.write_text",
        lambda text: {"ok": False, "message": "no clipboard tool"},
    )
    await client.post("/api/clipboard", json={"text": "never arrived"}, headers=AUTH)
    assert client.history.entries() == []


async def test_forgetting_is_audited(client):
    client.history.record("a password")
    body = await (await client.delete("/api/clipboard/history", headers=AUTH)).json()
    assert body["cleared"] == 1
    assert "clipboard.history.clear" in [e["event"] for e in client.vt.auth.audit.tail(10)]


async def test_the_history_needs_a_credential(client):
    assert (await client.get("/api/clipboard/history")).status == 401
    assert (await client.delete("/api/clipboard/history")).status == 401
