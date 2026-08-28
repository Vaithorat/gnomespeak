"""HTTP server and web UI for VoiceTalk remote control.

Two ways in, deliberately unequal:

  * On the LAN, the startup token in the URL is enough. It travels in a
    bookmark and a QR code, which is fine for a network you already control.
  * From anywhere else -- a Cloudflare Tunnel, a phone on mobile data -- the
    token is not accepted at all. The caller must present a paired-device
    credential, and a device is paired once, from a code that only ever
    appears on this PC's own terminal.

That split is the whole security model: exposing the public URL leaks nothing,
because the URL is not a credential off-network.
"""

import asyncio
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional
from aiohttp import web

from vt.actions import HAS_DBUS, execute_action, no_dbus_message
from vt.auth import (
    CODE_TTL,
    AuthError,
    AuthManager,
    clean_name,
    format_code,
    is_private_ip,
    resolve_client_ip,
)
from vt.sources.apps import get_installed_targets
from vt.sources.youtube import related_videos, search as search_youtube
from vt.state import get_snapshot
from vt.model import Snapshot

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False


# The token is read from location.search in the browser rather than
# interpolated server-side: reflecting it into this page made "?t=');..." a
# script-injection hole that could read the stored token back out. Any other
# query parameter is carried through -- a pairing link can arrive as
# "?t=...&p=..." and the pairing code must survive this redirect.
_TOKEN_CAPTURE_PAGE = """<html><head><meta charset="utf-8"><script nonce="__NONCE__">
(function () {
  var p = new URLSearchParams(window.location.search);
  var t = p.get("t");
  if (t) { try { localStorage.setItem("vt_token", t); } catch (e) {} }
  p.delete("t");
  var q = p.toString();
  window.location.replace(window.location.pathname + (q ? "?" + q : ""));
})();
</script></head><body>Redirecting...</body></html>"""

# Sent on every response. The page loads no third-party anything -- no fonts,
# no images, no analytics -- so 'none' by default costs nothing and turns a
# future stray <img src=evil> into a console error instead of a beacon.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def content_security_policy(nonce: str) -> str:
    return (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; "
        f"style-src 'nonce-{nonce}'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "frame-ancestors 'none'"
    )


@web.middleware
async def security_headers_middleware(request: web.Request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if not response.headers.get("Content-Security-Policy"):
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    # Only meaningful once the connection really is TLS; a browser ignores HSTS
    # over plain http, and cloudflared is the thing that knows which it was.
    if request.headers.get("X-Forwarded-Proto", "").lower() == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


class VoiceTalkServer:
    """HTTP server for the VoiceTalk web remote."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        token: Optional[str] = None,
        *,
        require_pairing: bool = False,
        trust_proxy: bool = False,
        public_url: str = "",
        tunnel: bool = False,
        tunnel_name: str = "",
        devices_path=None,
        audit_path=None,
        codes_path=None,
    ):
        self.host = host
        self.port = port
        # "" explicitly disables auth (--no-token); None means "generate one".
        self.token = "" if token == "" else (token or secrets.token_urlsafe(16))
        self.public_url = public_url.rstrip("/")
        self.tunnel = tunnel
        self.tunnel_name = tunnel_name
        self.auth = AuthManager(
            devices_path=devices_path,
            audit_path=audit_path,
            codes_path=codes_path,
            require_pairing=require_pairing,
            trust_proxy=trust_proxy,
        )
        self._snapshot_cache: Snapshot = Snapshot()
        self._snapshot_ts = 0.0
        self._ui_cache: Optional[str] = None
        # Set by run_server when --pair was asked for, so the banner can print
        # a pairing code and its QR alongside the URL.
        self.pending_pair_code: str = ""
        # One worker thread, not a pool: snapshot collection and action
        # execution both talk to python-dbus over a shared connection, so they
        # must stay serialized. A single worker keeps that ordering while
        # taking the blocking subprocess and D-Bus calls off the event loop --
        # a command with a 10s timeout used to stall every other request.
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vt-worker")
        self._refresh_task: Optional[asyncio.Task] = None

    # --- auth ---------------------------------------------------------------

    def _client(self, request: web.Request):
        """(ip, is_remote) for a request. Remote means "must pair a device"."""
        ip, via_proxy = resolve_client_ip(
            request.remote or "", request.headers, self.auth.trust_proxy
        )
        return ip, via_proxy or not is_private_ip(ip)

    def _needs_pairing(self, remote: bool) -> bool:
        """Whether this caller's only route in is to pair a device."""
        return self.auth.require_pairing or remote

    def _unauthorized(self, remote: bool) -> web.Response:
        return web.json_response(
            {
                "ok": False,
                "error": "unauthorized",
                "needs_pairing": self._needs_pairing(remote),
                "message": "Unauthorized",
            },
            status=401,
        )

    def _too_many(self, retry_after: float) -> web.Response:
        wait = int(retry_after) + 1
        return web.json_response(
            {
                "ok": False,
                "error": "rate_limited",
                "retry_after": wait,
                "message": f"Too many failed attempts. Try again in {wait}s.",
            },
            status=429,
            headers={"Retry-After": str(wait)},
        )

    def _authorize(self, request: web.Request):
        """Decide whether a request may proceed.

        Returns (principal, error_response) with exactly one of them set.
        """
        auth = self.auth
        ip, remote = self._client(request)
        key = f"auth:{ip}"

        locked = auth.auth_limiter.retry_after(key)
        if locked > 0:
            return None, self._too_many(locked)

        device_id = request.headers.get("X-VT-Device", "")
        secret = request.headers.get("X-VT-Secret", "")
        if device_id or secret:
            entry = auth.devices.verify(device_id, secret)
            if entry is not None:
                auth.auth_limiter.record_success(key)
                auth.devices.touch(entry["id"], ip)
                return {
                    "kind": "device",
                    "id": entry["id"],
                    "name": entry.get("name", "device"),
                    "ip": ip,
                }, None
            retry = auth.auth_limiter.record_failure(key)
            auth.audit.record("auth.reject", reason="bad_device", ip=ip, device=device_id[:32])
            return None, (self._too_many(retry) if retry > 0 else self._unauthorized(remote))

        if auth.require_pairing:
            return None, self._unauthorized(remote)

        if remote:
            # The startup token rides in a URL and ends up in a bookmark and a
            # QR code. That is an acceptable credential for a network you own
            # and a bad one to hand the open internet, so off-network callers
            # pair a device or get nothing -- including under --no-token.
            auth.audit.record("auth.reject", reason="remote_without_device", ip=ip)
            return None, self._unauthorized(remote)

        if not self.token:
            return {"kind": "open", "id": "", "name": "local", "ip": ip}, None

        supplied = request.headers.get("X-VT-Token", "")
        if supplied and secrets.compare_digest(supplied, self.token):
            auth.auth_limiter.record_success(key)
            return {"kind": "token", "id": "", "name": "lan", "ip": ip}, None
        if supplied:
            retry = auth.auth_limiter.record_failure(key)
            auth.audit.record("auth.reject", reason="bad_token", ip=ip)
            if retry > 0:
                return None, self._too_many(retry)
        return None, self._unauthorized(remote)

    async def _run_blocking(self, fn, *args):
        """Run a blocking callable on the single worker thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._worker, fn, *args)

    async def _refresh_snapshot(self):
        """Refresh the snapshot in the background every 1 Hz."""
        while True:
            try:
                self._snapshot_cache = await self._run_blocking(get_snapshot)
                self._snapshot_ts = time.time()
            except Exception as e:
                print(f"Error refreshing snapshot: {e}")
            await asyncio.sleep(1.0)

    # --- pages --------------------------------------------------------------

    def _ui_source(self) -> str:
        if self._ui_cache is None:
            ui_path = Path(__file__).parent / "ui" / "index.html"
            try:
                self._ui_cache = ui_path.read_text()
            except OSError:
                self._ui_cache = "<html><body>VoiceTalk remote control</body></html>"
        return self._ui_cache

    def _html_response(self, text: str) -> web.Response:
        # A per-response nonce is what lets the CSP forbid inline script in
        # general while still allowing this page's own single block. The nonce
        # is server-generated randomness, so interpolating it is safe in a way
        # that reflecting the token never was.
        nonce = secrets.token_urlsafe(16)
        body = (
            text.replace("<script>", f'<script nonce="{nonce}">')
                .replace("<style>", f'<style nonce="{nonce}">')
                .replace("__NONCE__", nonce)
        )
        return web.Response(
            text=body,
            content_type="text/html",
            headers={"Content-Security-Policy": content_security_policy(nonce)},
        )

    async def handle_root(self, request: web.Request) -> web.Response:
        """Serve the root page with token extraction."""
        if request.query.get("t") and self.token:
            # Hide the token from history by storing it and reloading without it.
            return self._html_response(_TOKEN_CAPTURE_PAGE)
        return self._html_response(self._ui_source())

    # --- api ----------------------------------------------------------------

    async def handle_api_session(self, request: web.Request) -> web.Response:
        """GET /api/session — who am I, and do I need to pair?

        Always 200: the UI needs to tell "wrong credential" apart from "no
        credential for this origin yet" to decide between an error banner and
        the pairing screen, and a bare 401 cannot carry that.
        """
        _, remote = self._client(request)
        principal, error = self._authorize(request)
        if principal is not None:
            return web.json_response({
                "authenticated": True,
                "kind": principal["kind"],
                "device_id": principal["id"],
                "name": principal["name"],
                "remote": remote,
                "device_count": len(self.auth.devices),
            })
        return web.json_response({
            "authenticated": False,
            "needs_pairing": self._needs_pairing(remote),
            "remote": remote,
            "rate_limited": error is not None and error.status == 429,
        })

    async def handle_api_pair(self, request: web.Request) -> web.Response:
        """POST /api/pair — trade a one-time code for a device credential."""
        auth = self.auth
        ip, _ = self._client(request)
        for key, limiter in (
            (f"pair:{ip}", auth.pair_limiter),
            ("pair:*", auth.global_pair_limiter),
        ):
            wait = limiter.retry_after(key)
            if wait > 0:
                auth.audit.record("pair.throttled", ip=ip)
                return self._too_many(wait)

        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        code = str(data.get("code") or "")
        name = clean_name(str(data.get("name") or "phone"))

        if not auth.codes.redeem(code):
            auth.pair_limiter.record_failure(f"pair:{ip}")
            auth.global_pair_limiter.record_failure("pair:*")
            auth.audit.record("pair.reject", ip=ip, name=name)
            return web.json_response(
                {
                    "ok": False,
                    "error": "invalid_code",
                    "message": "That pairing code is wrong, expired, or already used.",
                },
                status=403,
            )

        try:
            device_id, secret = auth.devices.register(name)
        except AuthError as e:
            return web.json_response(
                {"ok": False, "error": "store", "message": str(e)}, status=409
            )

        auth.pair_limiter.record_success(f"pair:{ip}")
        auth.audit.record("pair.ok", ip=ip, device=device_id, name=name)
        # Printed, not just logged: an unexpected line here is the user's cue
        # that someone else just used a code they left lying around.
        print(f"\n  ✓ Paired device '{name}' ({device_id}) from {ip}\n")
        return web.json_response(
            {"ok": True, "device_id": device_id, "secret": secret, "name": name}
        )

    async def handle_api_pair_self(self, request: web.Request) -> web.Response:
        """POST /api/pair/self — an authenticated session mints its own device.

        This is what makes the LAN path zero-friction: the browser that already
        holds the startup token upgrades itself to a real credential without
        anyone typing a code.
        """
        principal, error = self._authorize(request)
        if error is not None:
            return error
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        name = clean_name(str(data.get("name") or "this browser"))
        try:
            device_id, secret = self.auth.devices.register(name)
        except AuthError as e:
            return web.json_response(
                {"ok": False, "error": "store", "message": str(e)}, status=409
            )
        self.auth.audit.record(
            "pair.self", ip=principal["ip"], device=device_id, name=name, via=principal["kind"]
        )
        return web.json_response(
            {"ok": True, "device_id": device_id, "secret": secret, "name": name}
        )

    async def handle_api_devices(self, request: web.Request) -> web.Response:
        """GET /api/devices — list paired devices (never their secrets)."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        return web.json_response({
            "devices": self.auth.devices.list_devices(),
            "current": principal["id"],
        })

    async def handle_api_devices_revoke(self, request: web.Request) -> web.Response:
        """POST /api/devices/revoke — drop a device credential immediately."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        target = str(data.get("id") or "")
        removed = self.auth.devices.revoke(target)
        self.auth.audit.record(
            "device.revoke", ip=principal["ip"], device=target,
            by=principal["id"] or principal["kind"], ok=removed,
        )
        if not removed:
            return web.json_response(
                {"ok": False, "message": "No such device"}, status=404
            )
        print(f"\n  ✓ Revoked device {target}\n")
        return web.json_response({"ok": True, "message": "Device revoked"})

    async def handle_api_state(self, request: web.Request) -> web.Response:
        """GET /api/state — return the current snapshot."""
        _, error = self._authorize(request)
        if error is not None:
            return error
        return web.json_response(self._snapshot_cache.to_dict())

    async def handle_api_apps(self, request: web.Request) -> web.Response:
        """GET /api/apps — installed applications, optionally filtered by ?q=.

        Separate from /api/state on purpose: there are hundreds of installed
        apps and they change about once a week, so pushing them to every phone
        at 1 Hz would dwarf the state that actually moves. The UI fetches this
        once, when the user opens the list.
        """
        _, error = self._authorize(request)
        if error is not None:
            return error

        query = request.query.get("q", "")
        targets = await self._run_blocking(get_installed_targets, query)
        return web.json_response({"apps": [t.to_dict() for t in targets]})

    async def handle_api_youtube(self, request: web.Request) -> web.Response:
        """GET /api/youtube — search YouTube videos by query ?q=.

        Returns {"results": [...], "error": "..."}. The error carries the reason
        a search could not run -- a missing yt-dlp, most often -- because the UI
        rendering that as "no results found" is how a missing dependency came to
        look like a network fault.
        """
        _, error = self._authorize(request)
        if error is not None:
            return error

        query = request.query.get("q", "").strip()
        if not query:
            return web.json_response({"results": [], "error": ""})

        results, err = await self._run_blocking(search_youtube, query, 15)
        return web.json_response({"results": results, "error": err})

    async def handle_api_related(self, request: web.Request) -> web.Response:
        """GET /api/youtube/related — what to watch after the current video.

        The URL is optional: with none, the video open in the browser is used,
        because not having to know what is playing is the point of the feature.
        """
        _, error = self._authorize(request)
        if error is not None:
            return error

        url = request.query.get("url", "").strip()
        results, err = await self._run_blocking(related_videos, url, 15)
        return web.json_response({"results": results, "error": err})

    async def handle_api_do(self, request: web.Request) -> web.Response:
        """POST /api/do — execute an action."""
        principal, error = self._authorize(request)
        if error is not None:
            return error

        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"ok": False, "message": "Invalid JSON"},
                status=400,
            )

        target_id = data.get("target")
        action_id = data.get("action")
        value = data.get("value")

        if not target_id or not action_id:
            return web.json_response(
                {"ok": False, "message": "Missing 'target' or 'action'"},
                status=400,
            )

        result = await self._run_blocking(execute_action, target_id, action_id, value)
        # Every action is recorded with who asked for it. This is the log that
        # answers "did someone else do that?", so it is written for successes
        # too, not only for the refusals.
        self.auth.audit.record(
            "action",
            ip=principal["ip"],
            who=principal["name"],
            kind=principal["kind"],
            device=principal["id"],
            target=str(target_id)[:120],
            action=str(action_id)[:60],
            ok=bool(result.get("ok")),
        )
        return web.json_response(result)

    # --- lifecycle ----------------------------------------------------------

    def make_app(self) -> web.Application:
        app = web.Application(middlewares=[security_headers_middleware])
        app.router.add_get("/", self.handle_root)
        app.router.add_get("/api/session", self.handle_api_session)
        app.router.add_post("/api/pair", self.handle_api_pair)
        app.router.add_post("/api/pair/self", self.handle_api_pair_self)
        app.router.add_get("/api/devices", self.handle_api_devices)
        app.router.add_post("/api/devices/revoke", self.handle_api_devices_revoke)
        app.router.add_get("/api/state", self.handle_api_state)
        app.router.add_get("/api/apps", self.handle_api_apps)
        app.router.add_get("/api/youtube", self.handle_api_youtube)
        app.router.add_get("/api/youtube/related", self.handle_api_related)
        app.router.add_post("/api/do", self.handle_api_do)
        return app

    def pairing_url(self, code: str) -> str:
        """Link that pairs a phone in one scan: it carries the code itself."""
        base = self.public_url or f"http://{self.host}:{self.port}"
        return f"{base}/?p={code}"

    def _print_pairing(self, code: str):
        url = self.pairing_url(code)
        print("  ── Pair a device ──────────────────────────────")
        print(f"  Code:  {format_code(code)}   (valid {int(CODE_TTL // 60)} min, one device)")
        print(f"  Link:  {url}")
        if not self.public_url:
            print("  Note:  no public URL set -- this link only works on the LAN.")
            print("         vt pair --url https://<your-tunnel> for a remote one.")
        if HAS_QRCODE:
            try:
                qr = qrcode.QRCode(version=1, box_size=1, border=1)
                qr.add_data(url)
                qr.make(fit=True)
                print()
                qr.print_ascii(invert=True)
            except Exception as e:
                print(f"  Error generating QR code: {e}")
        print()

    def _on_tunnel_url(self, url: str):
        """cloudflared announced a public hostname."""
        from vt.tunnel import save_public_url

        self.public_url = url.rstrip("/")
        save_public_url(self.public_url)
        print("\n  ── Cloudflare Tunnel is up ────────────────────")
        print(f"  Public URL: {self.public_url}")
        print("  The URL alone controls nothing -- pair a device below.\n")
        self._print_pairing(self.auth.codes.issue("tunnel"))

    def _print_banner(self):
        base = f"http://{self.host}:{self.port}/"
        url = f"{base}?t={self.token}" if self.token else base
        print("\n  ╔════════════════════════════════════════════╗")
        print("  ║          VoiceTalk Remote Control          ║")
        print("  ╚════════════════════════════════════════════╝\n")

        if self.auth.require_pairing:
            print("  Mode: pairing required (token auth off)")
            print(f"  Local URL: {base}")
            print("  Pair a phone with:  vt pair\n")
        else:
            print(f"  URL: {url}")
            if not self.token:
                print("  WARNING: token auth disabled -- anyone on this network can control this PC.")
                print("           (Off-network callers still need a paired device.)")
            print()
            print("  📱 On your phone:")
            print("     1. Open this URL in any browser")
            print("     2. Bookmark it (token saved in localStorage)")
            print("     3. Control your PC!\n")

        if self.pending_pair_code:
            self._print_pairing(self.pending_pair_code)

        paired = len(self.auth.devices)
        print(f"  Paired devices: {paired}   (vt devices)")
        if self.auth.trust_proxy:
            print("  Proxy headers: trusted from loopback (Cloudflare Tunnel mode)")
        if self.public_url:
            print(f"  Public URL: {self.public_url}")
        print()

        if HAS_QRCODE and not self.auth.require_pairing:
            try:
                qr = qrcode.QRCode(version=1, box_size=1, border=1)
                qr.add_data(url)
                qr.make(fit=True)
                print("  📲 Scan this QR code on your phone:\n")
                qr.print_ascii(invert=True)
                print()
            except Exception as e:
                print(f"  Error generating QR code: {e}\n")
        elif not HAS_QRCODE:
            print("  💡 Tip: To scan a QR code, install: pip install qrcode[pil]\n")

        if not HAS_DBUS:
            print("  WARNING: " + no_dbus_message() + "\n")

        print("  Press Ctrl+C to stop.\n")

    async def run(self):
        """Start the server."""
        app = self.make_app()

        # Start the snapshot refresh task. Hold the reference: the event loop
        # only keeps a weak one, so a bare create_task can be collected mid-flight.
        self._refresh_task = asyncio.create_task(self._refresh_snapshot())

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        self._print_banner()
        self.auth.audit.record("server.start", host=self.host, port=self.port,
                               require_pairing=self.auth.require_pairing)

        tunnel_proc = None
        tunnel_task = None
        if self.tunnel:
            from vt import tunnel as tunnel_mod

            try:
                tunnel_proc, tunnel_task = await tunnel_mod.start(
                    self.port, self._on_tunnel_url, name=self.tunnel_name
                )
                if self.tunnel_name:
                    print(f"  ⏳ Starting named tunnel '{self.tunnel_name}'...")
                    print("     Pair against your own hostname: vt pair --url https://...\n")
                else:
                    print("  ⏳ Starting Cloudflare Tunnel (this takes a few seconds)...\n")
            except FileNotFoundError as e:
                print(f"  ✗ {e}\n")

        # Keep running until interrupted
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            print("\n  Shutting down...")
            self.auth.audit.record("server.stop")
            if self._refresh_task:
                self._refresh_task.cancel()
            if tunnel_task:
                tunnel_task.cancel()
            if tunnel_proc and tunnel_proc.returncode is None:
                tunnel_proc.terminate()
                try:
                    await asyncio.wait_for(tunnel_proc.wait(), timeout=5)
                except (asyncio.TimeoutError, ProcessLookupError):
                    pass
            if self.tunnel and not self.tunnel_name:
                # A quick tunnel's hostname dies with the process. Leaving it on
                # disk would have `vt pair` keep minting links for a name that no
                # longer resolves. A named tunnel's hostname outlives the run, so
                # that one is left alone.
                from vt.tunnel import clear_public_url
                clear_public_url()
            await runner.cleanup()
            self._worker.shutdown(wait=False)


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    token: Optional[str] = None,
    open_browser: bool = False,
    *,
    require_pairing: bool = False,
    trust_proxy: bool = False,
    public_url: str = "",
    tunnel: bool = False,
    tunnel_name: str = "",
    pair_on_start: bool = False,
):
    """Convenience function to run the server."""
    server = VoiceTalkServer(
        host,
        port,
        token,
        require_pairing=require_pairing,
        trust_proxy=trust_proxy,
        public_url=public_url,
        tunnel=tunnel,
        tunnel_name=tunnel_name,
    )
    if pair_on_start:
        server.pending_pair_code = server.auth.codes.issue("startup")
    if open_browser:
        import threading
        import webbrowser
        base = f"http://{host}:{port}/"
        target = f"{base}?t={server.token}" if server.token else base
        threading.Timer(1.0, lambda: webbrowser.open(target)).start()
    asyncio.run(server.run())
