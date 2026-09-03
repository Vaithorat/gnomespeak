"""Tests for waking another PC.

The packet's shape is fixed by the hardware, so it is asserted byte for byte,
and the wording is asserted too: nothing acknowledges a magic packet, so the
answer may say "sent" and must never say "woken".
"""

import socket

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt.server import VoiceTalkServer
from vt.sources.wake import magic_packet, normalise_mac, wake

AUTH = {"X-VT-Token": "test-token"}


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


def test_the_packet_is_six_ones_then_the_mac_sixteen_times():
    packet = magic_packet("aa:bb:cc:dd:ee:ff")
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("aabbccddeeff") * 16


def test_dashes_and_capitals_are_the_same_mac():
    assert normalise_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"


def test_something_that_is_not_a_mac_makes_no_packet():
    for text in ("", "hello", "aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:ff:00", "zz:bb:cc:dd:ee:ff"):
        assert magic_packet(text) == b"", text


def test_sending_to_something_that_is_not_a_mac_is_refused():
    assert wake("hello")["ok"] is False


def test_the_packet_really_leaves_the_machine():
    """A real socket, a real datagram, read back off the loopback."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    listener.settimeout(2)
    port = listener.getsockname()[1]

    result = wake("aa:bb:cc:dd:ee:ff", broadcast="127.0.0.1", port=port)
    received, _ = listener.recvfrom(200)
    listener.close()

    assert result["ok"] is True
    assert received == magic_packet("aa:bb:cc:dd:ee:ff")


def test_the_answer_never_claims_the_machine_woke():
    """Nothing acknowledges a magic packet; a machine that ignored it looks the same."""
    message = wake("aa:bb:cc:dd:ee:ff", broadcast="127.0.0.1")["message"]
    assert "sent" in message.lower()
    assert "woke" not in message.lower()


def test_a_socket_error_is_a_message(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("network is unreachable")

    monkeypatch.setattr("vt.sources.wake.socket.socket", broken)
    result = wake("aa:bb:cc:dd:ee:ff")
    assert result["ok"] is False and "unreachable" in result["message"]


async def test_the_endpoint_sends_a_packet(client, monkeypatch):
    sent = []
    monkeypatch.setattr("vt.sources.wake.wake",
                        lambda mac: sent.append(mac) or {"ok": True, "message": "Sent"})
    resp = await client.post("/api/wake", json={"mac": "aa:bb:cc:dd:ee:ff"}, headers=AUTH)
    assert (await resp.json())["ok"] is True
    assert sent == ["aa:bb:cc:dd:ee:ff"]


async def test_waking_is_audited(client, monkeypatch):
    monkeypatch.setattr("vt.sources.wake.wake", lambda mac: {"ok": True, "message": "Sent"})
    await client.post("/api/wake", json={"mac": "aa:bb:cc:dd:ee:ff"}, headers=AUTH)
    assert "wake.send" in [e["event"] for e in client.vt.auth.audit.tail(10)]


async def test_a_guest_may_not_wake_other_machines(client, monkeypatch):
    monkeypatch.setattr("vt.sources.wake.wake", _must_not_run)
    device_id, secret = client.vt.auth.devices.register("Visitor", scope="guest")
    resp = await client.post(
        "/api/wake", json={"mac": "aa:bb:cc:dd:ee:ff"},
        headers={"X-VT-Device": device_id, "X-VT-Secret": secret},
    )
    assert resp.status == 403


def _must_not_run(*args, **kwargs):
    raise AssertionError("a packet was sent for a request that should have been refused")


def test_the_cli_sends_a_packet(monkeypatch, capsys):
    from argparse import Namespace

    from vt import cli

    sent = []
    monkeypatch.setattr("vt.sources.wake.wake",
                        lambda mac, broadcast, port: sent.append((mac, broadcast, port))
                        or {"ok": True, "message": "Sent"})

    cli.cmd_wake(Namespace(mac="aa:bb:cc:dd:ee:ff", broadcast="255.255.255.255", port=9))

    assert sent == [("aa:bb:cc:dd:ee:ff", "255.255.255.255", 9)]
    out = capsys.readouterr().out
    assert "Nothing acknowledges" in out


def test_the_cli_fails_on_a_bad_mac(monkeypatch):
    from argparse import Namespace

    from vt import cli

    with pytest.raises(SystemExit):
        cli.cmd_wake(Namespace(mac="nonsense", broadcast="255.255.255.255", port=9))
