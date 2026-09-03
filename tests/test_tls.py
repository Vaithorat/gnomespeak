"""Tests for HTTPS on the local network.

Off the LAN the tunnel already provides TLS; this is the hop between the phone
and the PC on the same Wi-Fi, where the token used to travel in the clear. The
certificate is self-signed, so the fingerprint printed at startup is the whole
security story -- these tests are mostly about it being the right one, and
about the certificate actually naming this machine.
"""

import datetime
import ssl

import pytest
from aiohttp import web

from vt import tls

pytestmark = pytest.mark.skipif(not tls.available(), reason="cryptography is not installed")


def test_a_certificate_is_made_for_this_machine(tmp_path):
    result = tls.ensure(tmp_path)
    assert result["ok"] is True and result["created"] is True
    assert "127.0.0.1" in result["names"] and "localhost" in result["names"]
    assert (tmp_path / "tls-cert.pem").exists()


def test_the_private_key_is_private(tmp_path):
    tls.ensure(tmp_path)
    assert oct((tmp_path / "tls-key.pem").stat().st_mode)[-3:] == "600"


def test_it_is_made_once_and_reused(tmp_path):
    first = tls.ensure(tmp_path)
    second = tls.ensure(tmp_path)
    assert second["created"] is False
    assert second["fingerprint"] == first["fingerprint"]


def test_a_certificate_for_another_machine_is_replaced(tmp_path):
    """Moving between networks must not leave a name nobody matches."""
    first = tls.ensure(tmp_path, host="10.0.0.5")
    second = tls.ensure(tmp_path, host="10.9.9.9")
    assert second["created"] is True
    assert second["fingerprint"] != first["fingerprint"]


def test_the_fingerprint_is_the_one_a_phone_shows(tmp_path):
    import hashlib

    from cryptography import x509

    result = tls.ensure(tmp_path)
    cert = x509.load_pem_x509_certificate((tmp_path / "tls-cert.pem").read_bytes())
    der = cert.public_bytes(__import__("cryptography").hazmat.primitives.serialization.Encoding.DER)
    expected = ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest())
    assert result["fingerprint"] == expected


def test_it_lasts_about_two_years(tmp_path):
    from cryptography import x509

    tls.ensure(tmp_path)
    cert = x509.load_pem_x509_certificate((tmp_path / "tls-cert.pem").read_bytes())
    life = cert.not_valid_after_utc - cert.not_valid_before_utc
    assert datetime.timedelta(days=700) < life < datetime.timedelta(days=760)


def test_an_expired_certificate_is_replaced(tmp_path, monkeypatch):
    tls.ensure(tmp_path)
    monkeypatch.setattr(tls, "covers", lambda pem, names: False)
    assert tls.ensure(tmp_path)["created"] is True


def test_names_never_include_a_bind_wildcard():
    """0.0.0.0 is how the server listens, not a name anything can verify."""
    assert "0.0.0.0" not in tls.names_for("0.0.0.0")


async def test_a_browser_can_actually_connect(tmp_path):
    """A real TLS handshake against a real server, verified against the cert."""
    result = tls.context(tmp_path, host="127.0.0.1")
    assert result["ok"] is True

    app = web.Application()

    async def hello(request):
        return web.json_response({"ok": True})

    app.router.add_get("/", hello)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=result["context"])
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    try:
        import aiohttp

        trust = ssl.create_default_context(cafile=str(tmp_path / "tls-cert.pem"))
        connector = aiohttp.TCPConnector(ssl=trust)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(f"https://127.0.0.1:{port}/") as response:
                assert response.status == 200
                assert (await response.json())["ok"] is True
    finally:
        await runner.cleanup()


async def test_an_untrusting_client_is_refused(tmp_path):
    """The certificate is this machine's own, so nothing trusts it by default."""
    import aiohttp

    result = tls.context(tmp_path, host="127.0.0.1")
    app = web.Application()
    async def empty(request):
        return web.json_response({})

    app.router.add_get("/", empty)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=result["context"])
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    try:
        async with aiohttp.ClientSession() as session:
            with pytest.raises(aiohttp.ClientConnectorCertificateError):
                await session.get(f"https://127.0.0.1:{port}/")
    finally:
        await runner.cleanup()


def test_without_cryptography_it_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(tls, "HAS_CRYPTO", False)
    result = tls.ensure(tmp_path)
    assert result["ok"] is False and "cryptography" in result["message"]


# --- the pairing link -------------------------------------------------------

async def test_a_pairing_link_uses_https_when_the_server_does(tmp_path):
    """`vt pair` runs in another terminal, so it asks the port, not the server."""
    from vt import cli

    result = tls.context(tmp_path, host="127.0.0.1")
    app = web.Application()

    async def empty(request):
        return web.json_response({})

    app.router.add_get("/", empty)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=result["context"])
    await site.start()
    port = site._server.sockets[0].getsockname()[1]

    try:
        # The probe blocks, and the server it is probing lives in this loop, so
        # it has to run off the loop -- which is where it runs in real life
        # anyway, `vt pair` being a separate process.
        import asyncio

        answered = await asyncio.get_running_loop().run_in_executor(
            None, lambda: cli._serves_https("127.0.0.1", port)
        )
        assert answered is True
    finally:
        await runner.cleanup()


async def test_a_plain_server_is_not_mistaken_for_https():
    from aiohttp.test_utils import TestClient, TestServer

    from vt import cli

    app = web.Application()

    async def empty(request):
        return web.json_response({})

    app.router.add_get("/", empty)
    async with TestClient(TestServer(app)) as client:
        import asyncio

        answered = await asyncio.get_running_loop().run_in_executor(
            None, lambda: cli._serves_https("127.0.0.1", client.server.port)
        )
        assert answered is False


def test_a_port_with_nothing_on_it_is_not_https():
    from vt import cli

    assert cli._serves_https("127.0.0.1", 1) is False
