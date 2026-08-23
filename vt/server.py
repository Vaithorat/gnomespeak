"""HTTP server and web UI for VoiceTalk remote control."""

import asyncio
import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional
from aiohttp import web

from vt.actions import HAS_DBUS, execute_action, no_dbus_message
from vt.sources.apps import get_installed_targets
from vt.sources.youtube import search as search_youtube
from vt.state import get_snapshot
from vt.model import Snapshot

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False


# The token is read from location.search in the browser rather than
# interpolated server-side: reflecting it into this page made "?t=');..." a
# script-injection hole that could read the stored token back out.
_TOKEN_CAPTURE_PAGE = """<html><head><meta charset="utf-8"><script>
(function () {
  var t = new URLSearchParams(window.location.search).get("t");
  if (t) { try { localStorage.setItem("vt_token", t); } catch (e) {} }
  window.location.replace(window.location.pathname);
})();
</script></head><body>Redirecting...</body></html>"""


class VoiceTalkServer:
    """HTTP server for the VoiceTalk web remote."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, token: Optional[str] = None):
        self.host = host
        self.port = port
        # "" explicitly disables auth (--no-token); None means "generate one".
        self.token = "" if token == "" else (token or secrets.token_urlsafe(16))
        self._snapshot_cache: Snapshot = Snapshot()
        self._snapshot_ts = 0.0
        # One worker thread, not a pool: snapshot collection and action
        # execution both talk to python-dbus over a shared connection, so they
        # must stay serialized. A single worker keeps that ordering while
        # taking the blocking subprocess and D-Bus calls off the event loop --
        # a command with a 10s timeout used to stall every other request.
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vt-worker")
        self._refresh_task: Optional[asyncio.Task] = None

    def _check_token(self, request: web.Request) -> bool:
        """Validate the token from the request header."""
        if not self.token:
            return True  # No token required
        header = request.headers.get("X-VT-Token", "")
        # Constant-time comparison
        return secrets.compare_digest(header, self.token)

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

    async def handle_root(self, request: web.Request) -> web.Response:
        """Serve the root page with token extraction."""
        token_param = request.query.get("t")
        if token_param and self.token:
            # Hide the token from history by storing it and reloading without it.
            # The token is read from location.search in the browser rather than
            # interpolated here: reflecting it into the page made "?t=');..." a
            # script-injection hole that could read the stored token back out.
            return web.Response(
                text=_TOKEN_CAPTURE_PAGE,
                content_type="text/html",
            )
        # Serve the main page
        ui_path = Path(__file__).parent / "ui" / "index.html"
        if ui_path.exists():
            with open(ui_path, "r") as f:
                return web.Response(text=f.read(), content_type="text/html")
        return web.Response(text="VoiceTalk remote control", content_type="text/html")

    async def handle_api_state(self, request: web.Request) -> web.Response:
        """GET /api/state — return the current snapshot."""
        if not self._check_token(request):
            return web.Response(status=401, text="Unauthorized")

        return web.json_response(self._snapshot_cache.to_dict())

    async def handle_api_apps(self, request: web.Request) -> web.Response:
        """GET /api/apps — installed applications, optionally filtered by ?q=.

        Separate from /api/state on purpose: there are hundreds of installed
        apps and they change about once a week, so pushing them to every phone
        at 1 Hz would dwarf the state that actually moves. The UI fetches this
        once, when the user opens the list.
        """
        if not self._check_token(request):
            return web.Response(status=401, text="Unauthorized")

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
        if not self._check_token(request):
            return web.Response(status=401, text="Unauthorized")

        query = request.query.get("q", "").strip()
        if not query:
            return web.json_response({"results": [], "error": ""})

        results, error = await self._run_blocking(search_youtube, query, 15)
        return web.json_response({"results": results, "error": error})

    async def handle_api_do(self, request: web.Request) -> web.Response:
        """POST /api/do — execute an action."""
        if not self._check_token(request):
            return web.Response(status=401, text="Unauthorized")

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
        return web.json_response(result)

    async def run(self):
        """Start the server."""
        app = web.Application()
        app.router.add_get("/", self.handle_root)
        app.router.add_get("/api/state", self.handle_api_state)
        app.router.add_get("/api/apps", self.handle_api_apps)
        app.router.add_get("/api/youtube", self.handle_api_youtube)
        app.router.add_post("/api/do", self.handle_api_do)

        # Start the snapshot refresh task. Hold the reference: the event loop
        # only keeps a weak one, so a bare create_task can be collected mid-flight.
        self._refresh_task = asyncio.create_task(self._refresh_snapshot())

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()

        base = f"http://{self.host}:{self.port}/"
        url = f"{base}?t={self.token}" if self.token else base
        print(f"\n  ╔════════════════════════════════════════════╗")
        print(f"  ║          VoiceTalk Remote Control          ║")
        print(f"  ╚════════════════════════════════════════════╝\n")
        print(f"  URL: {url}")
        if not self.token:
            print("  WARNING: token auth disabled -- anyone on this network can control this PC.")
        print()
        print(f"  📱 On your phone:")
        print(f"     1. Open this URL in any browser")
        print(f"     2. Bookmark it (token saved in localStorage)")
        print(f"     3. Control your PC!\n")

        # Print QR code if available
        if HAS_QRCODE:
            try:
                qr = qrcode.QRCode(version=1, box_size=1, border=1)
                qr.add_data(url)
                qr.make(fit=True)
                print(f"  📲 Scan this QR code on your phone:\n")
                qr.print_ascii(invert=True)
                print()
            except Exception as e:
                print(f"  Error generating QR code: {e}\n")
        else:
            print(f"  💡 Tip: To scan a QR code, install: pip install qrcode[pil]\n")

        if not HAS_DBUS:
            print("  WARNING: " + no_dbus_message() + "\n")

        print("  Press Ctrl+C to stop.\n")

        # Keep running until interrupted
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            print("\n  Shutting down...")
            if self._refresh_task:
                self._refresh_task.cancel()
            await runner.cleanup()
            self._worker.shutdown(wait=False)


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    token: Optional[str] = None,
    open_browser: bool = False,
):
    """Convenience function to run the server."""
    server = VoiceTalkServer(host, port, token)
    if open_browser:
        import threading, webbrowser
        base = f"http://{host}:{port}/"
        target = f"{base}?t={server.token}" if server.token else base
        threading.Timer(1.0, lambda: webbrowser.open(target)).start()
    asyncio.run(server.run())
