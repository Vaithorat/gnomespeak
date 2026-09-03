"""Tests for `vt doctor` in the page.

Two things matter here. Every row must carry what the phone needs to act --
what is true, what it costs, and what to do -- and one check that throws must
not take the rest of the page with it, because the moment someone opens this
screen is the moment something is already wrong.
"""

import pytest
from aiohttp.test_utils import TestClient, TestServer

from vt import diagnostics
from vt.server import VoiceTalkServer

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


def test_every_check_returns_the_shape_the_page_renders():
    for row in diagnostics.collect()["checks"]:
        assert set(row) == {"id", "title", "state", "detail", "fix", "lost"}
        assert row["state"] in (diagnostics.OK, diagnostics.WARN,
                                diagnostics.INFO, diagnostics.FAIL)
        assert row["title"] and row["detail"]


def test_check_ids_are_unique():
    ids = [row["id"] for row in diagnostics.collect()["checks"]]
    assert len(ids) == len(set(ids))


def test_a_check_that_throws_becomes_a_finding(monkeypatch):
    def explode():
        raise RuntimeError("the bus went away")

    monkeypatch.setattr(diagnostics, "CHECKS", (diagnostics._session, explode))
    result = diagnostics.collect()

    assert len(result["checks"]) == 2
    assert result["checks"][1]["state"] == diagnostics.FAIL
    assert "bus went away" in result["checks"][1]["detail"]


def test_the_summary_counts_what_is_broken(monkeypatch):
    monkeypatch.setattr(diagnostics, "CHECKS", (
        lambda: diagnostics._row("a", "A", diagnostics.OK, "fine"),
        lambda: diagnostics._row("b", "B", diagnostics.WARN, "half"),
        lambda: diagnostics._row("c", "C", diagnostics.FAIL, "gone"),
    ))
    result = diagnostics.collect()
    assert result["counts"] == {"ok": 1, "warn": 1, "info": 0, "fail": 1}
    assert result["summary"] == "1 broken, 1 degraded"


def test_a_healthy_machine_says_so(monkeypatch):
    monkeypatch.setattr(diagnostics, "CHECKS", (
        lambda: diagnostics._row("a", "A", diagnostics.OK, "fine"),
    ))
    assert diagnostics.collect()["summary"] == "everything checked is working"


def test_a_missing_clipboard_tool_says_what_is_lost(monkeypatch):
    monkeypatch.setattr("vt.sources.clipboard.backend", lambda: {})
    row = diagnostics._clipboard()
    assert row["state"] == diagnostics.WARN
    assert "clipboard sync" in row["lost"]
    assert "wl-clipboard" in row["fix"]


def test_an_extension_waiting_for_a_login_is_a_warning_with_the_fix(monkeypatch):
    monkeypatch.setattr("vt.shell.status",
                        lambda base=None: ("pending-login", "installed and enabled"))
    row = diagnostics._extension()
    assert row["state"] == diagnostics.WARN
    assert "log out" in row["fix"].lower()


def test_a_machine_with_no_gnome_shell_is_not_a_problem(monkeypatch):
    monkeypatch.setattr("vt.shell.status",
                        lambda base=None: ("no-shell", "no GNOME Shell on this machine"))
    assert diagnostics._extension()["state"] == diagnostics.INFO


async def test_the_endpoint_answers_the_phone(client):
    body = await (await client.get("/api/diagnostics", headers=AUTH)).json()
    assert body["ok"] is True
    assert body["summary"]
    assert any(row["id"] == "extension" for row in body["checks"])


async def test_diagnostics_need_a_credential(client):
    assert (await client.get("/api/diagnostics")).status == 401
