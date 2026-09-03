"""Tests for opening a link from the phone on the PC.

The interesting half is what is refused. A link arrives as free text from a
phone that may be passing on something it was sent, and a desktop's URL
handlers reach much further than a browser -- so anything that is not http or
https must not reach `xdg-open` at all.
"""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt.server import VoiceTalkServer
from vt.sources import open_url as mod

AUTH = {"X-VT-Token": "test-token"}


@pytest.fixture
def spawned(monkeypatch):
    """Record what would have been launched, and launch nothing."""
    calls = []
    monkeypatch.setattr(mod.subprocess, "Popen", lambda argv, **kw: calls.append(argv))
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


def test_a_full_url_is_kept_as_it_is():
    assert mod.normalise("https://example.com/a?b=c#d") == "https://example.com/a?b=c#d"


def test_a_bare_host_gets_https():
    assert mod.normalise("example.com") == "https://example.com"
    assert mod.normalise("docs.python.org/3/library/") == "https://docs.python.org/3/library/"


def test_javascript_and_data_are_refused():
    assert mod.normalise("javascript:alert(1)") == ""
    assert mod.normalise("data:text/html,<script>alert(1)</script>") == ""


def test_a_local_file_is_refused():
    """xdg-open on a file: URL would hand a local file to whatever opens it."""
    assert mod.normalise("file:///etc/passwd") == ""


def test_another_applications_scheme_is_refused():
    """A desktop registers handlers far beyond the browser; this is a link button."""
    assert mod.normalise("steam://run/440") == ""
    assert mod.normalise("ms-word:ofe|u|https://example.com/x.docx") == ""


def test_plain_text_is_not_a_link():
    assert mod.normalise("remember the milk") == ""
    assert mod.normalise("") == ""
    assert mod.normalise("   ") == ""


def test_a_url_with_a_newline_is_refused():
    """Whitespace is how two things get smuggled into one argument."""
    assert mod.normalise("https://example.com\nhttps://evil.example") == ""


def test_opening_runs_xdg_open_with_the_url_as_one_argument(spawned):
    result = mod.open_url("example.com")
    assert result["ok"] is True
    assert spawned == [["xdg-open", "https://example.com"]]


def test_a_refused_link_never_reaches_xdg_open(spawned):
    result = mod.open_url("javascript:alert(1)")
    assert result["ok"] is False
    assert spawned == []


def test_a_machine_without_xdg_open_says_so(monkeypatch):
    def missing(argv, **kw):
        raise FileNotFoundError()

    monkeypatch.setattr(mod.subprocess, "Popen", missing)
    assert "xdg-utils" in mod.open_url("https://example.com")["message"]


async def test_the_endpoint_opens_a_link(client, spawned):
    resp = await client.post("/api/open", json={"url": "https://example.com"}, headers=AUTH)
    assert (await resp.json())["ok"] is True
    assert spawned == [["xdg-open", "https://example.com"]]


async def test_the_endpoint_refuses_what_is_not_a_link(client, spawned):
    resp = await client.post("/api/open", json={"url": "file:///etc/shadow"}, headers=AUTH)
    assert (await resp.json())["ok"] is False
    assert spawned == []


async def test_opening_is_audited(client, spawned):
    await client.post("/api/open", json={"url": "https://example.com"}, headers=AUTH)
    events = [e["event"] for e in client.vt.auth.audit.tail(10)]
    assert "open.url" in events


async def test_opening_requires_a_credential(client, spawned):
    assert (await client.post("/api/open", json={"url": "https://example.com"})).status == 401
    assert spawned == []


# --- the CLI ----------------------------------------------------------------

def test_the_cli_opens_a_link(spawned, capsys):
    from argparse import Namespace

    from vt import cli

    cli.cmd_open(Namespace(url="example.com"))

    assert spawned == [["xdg-open", "https://example.com"]]
    assert "✓" in capsys.readouterr().out


def test_the_cli_refuses_what_is_not_a_link(spawned, capsys):
    import pytest as _pytest
    from argparse import Namespace

    from vt import cli

    with _pytest.raises(SystemExit):
        cli.cmd_open(Namespace(url="javascript:alert(1)"))
    assert spawned == []
