"""Tests for the Cloudflare Tunnel URL that pairing links are built on.

A quick tunnel's hostname is deleted the moment cloudflared stops, so a URL
remembered from an earlier run resolves to nothing. Handed to a phone as a QR
code it fails as "server DNS address could not be found", with nothing on
screen to connect that back to a tunnel that is no longer running.
"""

import json
import urllib.error

import pytest

from vt import tunnel


@pytest.fixture
def remote_file(tmp_path, monkeypatch):
    path = tmp_path / "remote.json"
    monkeypatch.setattr(tunnel, "_remote_file", lambda: path)
    return path


def test_save_and_load_round_trip(remote_file):
    tunnel.save_public_url("https://abc-def.trycloudflare.com")
    assert tunnel.load_public_url() == "https://abc-def.trycloudflare.com"


def test_save_records_when(remote_file):
    tunnel.save_public_url("https://abc-def.trycloudflare.com")
    assert json.loads(remote_file.read_text())["saved_at"] > 0


def test_clear_forgets_the_url(remote_file):
    tunnel.save_public_url("https://abc-def.trycloudflare.com")
    tunnel.clear_public_url()
    assert tunnel.load_public_url() == ""


def test_clear_is_fine_when_nothing_was_saved(remote_file):
    tunnel.clear_public_url()  # must not raise
    assert tunnel.load_public_url() == ""


def test_missing_file_loads_as_empty(remote_file):
    assert tunnel.load_public_url() == ""


def test_corrupt_file_loads_as_empty(remote_file):
    remote_file.write_text("{not json")
    assert tunnel.load_public_url() == ""


# --- liveness ---------------------------------------------------------------

def test_a_name_that_will_not_resolve_is_dead(monkeypatch):
    """The exact failure a stopped quick tunnel produces: NXDOMAIN, which the
    phone reports as "server DNS address could not be found"."""
    import socket
    import urllib.request

    def nxdomain(url, timeout=None):
        raise urllib.error.URLError(socket.gaierror(-2, "Name or service not known"))

    monkeypatch.setattr(urllib.request, "urlopen", nxdomain)
    assert tunnel.public_url_is_live("https://gone.trycloudflare.com") is False


def test_a_reachable_url_is_live(monkeypatch):
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda url, timeout=None: object())
    assert tunnel.public_url_is_live("https://live.trycloudflare.com") is True


def test_a_502_still_counts_as_live(monkeypatch):
    """The tunnel is up and only the local server is missing -- a different
    problem, with a different fix, and not one a new hostname would solve."""
    import urllib.request

    def bad_gateway(url, timeout=None):
        raise urllib.error.HTTPError(url, 502, "Bad Gateway", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", bad_gateway)
    assert tunnel.public_url_is_live("https://live.trycloudflare.com") is True


def test_empty_url_is_dead():
    assert tunnel.public_url_is_live("") is False


# --- what `vt pair` builds its link on --------------------------------------

class _Args:
    url = None
    port = 8765
    minutes = 10
    label = "test"
    no_check = False


def test_pair_falls_back_to_lan_when_the_tunnel_is_gone(remote_file, monkeypatch, capsys):
    from vt import cli

    tunnel.save_public_url("https://gone.trycloudflare.com")
    monkeypatch.setattr(tunnel, "public_url_is_live", lambda url, timeout=4.0: False)
    monkeypatch.setattr(cli, "_lan_url", lambda port: "http://192.168.1.5:8765")

    cli.cmd_pair(_Args())
    out = capsys.readouterr().out

    assert "http://192.168.1.5:8765/?p=" in out
    assert "gone.trycloudflare.com" not in out.split("Link:")[1].split("\n")[0]
    assert "no longer answers" in out
    # And the dead hostname does not survive to trip up the next run.
    assert tunnel.load_public_url() == ""


def test_pair_uses_a_live_tunnel_url(remote_file, monkeypatch, capsys):
    from vt import cli

    tunnel.save_public_url("https://live.trycloudflare.com")
    monkeypatch.setattr(tunnel, "public_url_is_live", lambda url, timeout=4.0: True)

    cli.cmd_pair(_Args())
    out = capsys.readouterr().out

    assert "https://live.trycloudflare.com/?p=" in out
    assert "no longer answers" not in out
    assert tunnel.load_public_url() == "https://live.trycloudflare.com"


def test_explicit_url_skips_the_check(remote_file, monkeypatch, capsys):
    from vt import cli

    def never(url, timeout=4.0):
        raise AssertionError("--url must not be probed")

    monkeypatch.setattr(tunnel, "public_url_is_live", never)
    args = _Args()
    args.url = "https://my-own.example.com/"

    cli.cmd_pair(args)
    assert "https://my-own.example.com/?p=" in capsys.readouterr().out


def test_no_check_trusts_the_saved_url(remote_file, monkeypatch, capsys):
    from vt import cli

    def never(url, timeout=4.0):
        raise AssertionError("--no-check must not probe")

    tunnel.save_public_url("https://saved.trycloudflare.com")
    monkeypatch.setattr(tunnel, "public_url_is_live", never)
    args = _Args()
    args.no_check = True

    cli.cmd_pair(args)
    assert "https://saved.trycloudflare.com/?p=" in capsys.readouterr().out


def test_lan_only_note_when_nothing_was_ever_saved(remote_file, monkeypatch, capsys):
    from vt import cli

    monkeypatch.setattr(cli, "_lan_url", lambda port: "http://192.168.1.5:8765")
    cli.cmd_pair(_Args())
    out = capsys.readouterr().out

    assert "LAN-only" in out
    assert "no longer answers" not in out
