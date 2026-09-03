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
from urllib.parse import urlsplit
from aiohttp import WSMsgType, web

from vt import shell
from vt.actions import HAS_DBUS, execute_action, no_dbus_message
from vt.auth import (
    CODE_TTL,
    DEFAULT_SCOPE,
    AuthError,
    AuthManager,
    capability_for,
    clean_name,
    format_code,
    is_private_ip,
    resolve_client_ip,
    scope_allows,
    scope_name,
)
from vt.live import TICKET_TTL, LiveHub, PhoneRegistry, TicketStore
from vt.push import SubscriptionStore
from vt.notify import notify
from vt.sources.apps import get_installed_targets
from vt.sources.youtube import related_videos, search as search_youtube
from vt.state import get_snapshot, snapshot_order
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

# Files the installed web app needs before any credential exists: the browser
# fetches them on its own, and none of them says anything about the PC.
STATIC_ASSETS = {
    "manifest.webmanifest": ("application/manifest+json", "no-cache"),
    "sw.js": ("application/javascript", "no-cache"),
    "icon-192.png": ("image/png", "public, max-age=604800"),
    "icon-512.png": ("image/png", "public, max-age=604800"),
    "icon-maskable-512.png": ("image/png", "public, max-age=604800"),
    "apple-touch-icon.png": ("image/png", "public, max-age=604800"),
}

_SHARE_FALLBACK_PAGE = (
    "<html><head><meta charset=\"utf-8\"><title>GnomeSpeak</title></head>"
    "<body style=\"font:16px system-ui;padding:2rem\">"
    "<h1>Open GnomeSpeak first</h1>"
    "<p>A share can only be delivered by the installed app, which holds this "
    "phone's credential. Open GnomeSpeak once, then share again.</p></body></html>"
)

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


def probe_origin(url: str) -> str:
    """The bare origin of a URL worth probing, or "" when it is not one.

    Only http and https, only a host, and never any credentials the caller
    tried to smuggle in the URL -- a probe is a question about a machine, not
    a way to have this desktop send something somewhere.
    """
    try:
        parsed = urlsplit((url or "").strip())
    except Exception:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}"


def content_security_policy(nonce: str) -> str:
    return (
        "default-src 'none'; "
        f"script-src 'nonce-{nonce}'; "
        f"style-src 'nonce-{nonce}'; "
        # blob: as well as 'self': album art and screenshots are fetched with a
        # credential and handed to the <img> as an object URL, because an
        # <img src> cannot carry a header and the credential must not travel in
        # a URL. Without blob: here every one of those images renders as the
        # browser's broken-image placeholder.
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "manifest-src 'self'; "
        "worker-src 'self'; "
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


# How long the collector waits after an action before reading the desktop
# again. Collecting the instant a D-Bus call returns reads the state from
# before the player acted on it; waiting too long is latency the phone feels on
# every tap. Measured against the roadmap's 300 ms budget, of which snapshot
# collection itself is most.
ACTION_SETTLE = 0.10


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
        push_path=None,
        tls: bool = False,
    ):
        self.host = host
        self.port = port
        # HTTPS on the LAN, with a certificate this machine makes for itself.
        # Off the LAN the tunnel already provides TLS, so this is about the
        # hop between the phone and the PC on the same Wi-Fi.
        self.tls = tls
        self.tls_info: dict = {}
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
        # The live channel. Both are cheap when nothing connects: the hub holds
        # the last snapshot it published and no timers of its own.
        self.live = LiveHub()
        self.tickets = TicketStore()
        self.phones = PhoneRegistry()
        # Where to reach a phone whose page is closed, and which phones do not
        # need it right now because they are looking at the page.
        self.push_subscriptions = SubscriptionStore(push_path)
        self._connected_devices: set = set()
        # Set by anything that just changed the desktop, so the collector runs
        # then rather than at the end of its second. Created lazily-free: an
        # Event binds to no loop until it is awaited, so building the server
        # outside one (every test does) stays fine.
        self._wake = asyncio.Event()
        # Notifications that arrived on the reader thread and have not been
        # pushed yet. They wait a moment before going out: the daemon's reply
        # carries the id that makes a notification dismissable, and it lands a
        # few milliseconds after the call the mirror read.
        # Whether the PC's own battery was already low on the last tick, so a
        # phone is told when it crosses rather than every second afterwards.
        self._battery_was_low = False
        # The target an action just touched, so the collector can answer for
        # that row before it answers for everything.
        self._wake_target = ""
        self._pending_notifications: list = []
        self._notification_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
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
        # A second worker, used only for the sources that touch no D-Bus:
        # wpctl, /proc, /sys. Those are the rows people press most -- volume
        # above all -- and this is what stops one of them waiting behind a
        # collection that is already running. Anything that talks to D-Bus
        # stays on the single worker above, because that connection is shared.
        self._fast_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vt-fast")
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
                    "scope": scope_name(str(entry.get("scope") or DEFAULT_SCOPE)),
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
            return {"kind": "open", "id": "", "name": "local", "ip": ip,
                    "scope": DEFAULT_SCOPE}, None

        supplied = request.headers.get("X-VT-Token", "")
        if supplied and secrets.compare_digest(supplied, self.token):
            auth.auth_limiter.record_success(key)
            return {"kind": "token", "id": "", "name": "lan", "ip": ip,
                    "scope": DEFAULT_SCOPE}, None
        if supplied:
            retry = auth.auth_limiter.record_failure(key)
            auth.audit.record("auth.reject", reason="bad_token", ip=ip)
            if retry > 0:
                return None, self._too_many(retry)
        return None, self._unauthorized(remote)

    def _forbidden(self, principal: dict, capability: str):
        """None when this principal may use `capability`, else a 403.

        A scope is not authentication: the device is who it says it is, and is
        being told that this particular thing is not theirs to do. Saying so
        with 403 rather than 401 keeps the phone from throwing its credential
        away and asking to pair again.
        """
        if scope_allows(principal.get("scope", DEFAULT_SCOPE), capability):
            return None
        self.auth.audit.record(
            "scope.reject", ip=principal.get("ip", ""), who=principal.get("name", ""),
            device=principal.get("id", ""), ok=False, detail=capability,
        )
        return web.json_response(
            {
                "ok": False,
                "error": "forbidden",
                "message": f"This device is not allowed to do that ({capability}).",
            },
            status=403,
        )

    async def _run_blocking(self, fn, *args):
        """Run a blocking callable on the single worker thread."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._worker, fn, *args)

    # Targets whose source reads files and subprocesses rather than D-Bus, so a
    # refresh of one can safely run beside a collection that is already going.
    FAST_PREFIXES = ("system:audio", "system:mic", "audio:", "stream:", "app:",
                     "disk:", "system:machine")

    async def _run_refresh(self, target_id: str, fn, *args):
        """Run a partial refresh, off the shared worker where that is safe."""
        loop = asyncio.get_running_loop()
        worker = (self._fast_worker
                  if target_id.startswith(self.FAST_PREFIXES) else self._worker)
        return await loop.run_in_executor(worker, fn, *args)

    async def _refresh_snapshot(self):
        """Refresh the snapshot in the background every 1 Hz.

        The same timer feeds both routes in: pollers read the cache, socket
        clients are pushed whatever changed. Collecting once for both is what
        keeps a second phone from doubling the D-Bus traffic.
        """
        first = True
        while True:
            try:
                # A phone that just pressed pause should not wait out the rest
                # of the tick to see it. An action wakes this loop, and the
                # short sleep afterwards is the desktop's own reaction time --
                # collecting the instant the D-Bus call returns reads the state
                # from before the player acted on it.
                if self._wake.is_set():
                    self._wake.clear()
                    await asyncio.sleep(ACTION_SETTLE)
                    # Answer the row that was pressed first, from its own
                    # source alone: collecting everything to report one change
                    # is most of the delay the phone feels. The full collection
                    # below runs straight afterwards and corrects anything else
                    # that moved.
                    if await self._publish_partial(self._wake_target):
                        self._wake_target = ""
                # Timers first: a job that fires must be in the snapshot that
                # follows it, not the one before.
                await self._run_blocking(self._run_due_jobs)
                snapshot = await self._run_blocking(get_snapshot)
                snapshot.targets.extend(self._phone_targets())
                self._snapshot_cache = snapshot
                self._snapshot_ts = time.time()
                if first and not len(self.live):
                    # Adopt, do not publish: with nobody connected there is
                    # nobody to tell, and a hub seeded from the empty startup
                    # Snapshot would otherwise call every target on the PC new.
                    # A phone that connected inside the first second is a
                    # client, so that case publishes like any other.
                    self.live.seed(self._snapshot_cache)
                    first = False
                else:
                    first = False
                    await self.live.publish(self._snapshot_cache)
                alert = await self._run_blocking(self._battery_alert)
                if alert:
                    if len(self.live):
                        await self.live.broadcast(alert)
                    await self.push_out({
                        "title": "This PC's battery is low",
                        "body": alert.get("message", ""),
                        "tag": "battery",
                        "url": "/",
                    })
            except Exception as e:
                print(f"Error refreshing snapshot: {e}")
            try:
                # Sleeps a second, or until an action says the desktop just
                # changed -- whichever comes first.
                await asyncio.wait_for(self._wake.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

    def _battery_alert(self) -> dict:
        """The PC's battery crossing into "low", once, or {}.

        The phone is told because the PC's own warning is on the screen the
        user has walked away from -- and only on the crossing, because a laptop
        sitting at 9% reports the same number every second.
        """
        from vt.sources.system import LOW_BATTERY_PERCENT, battery_state

        state = battery_state()
        if not state:
            return {}
        low = state["percent"] <= LOW_BATTERY_PERCENT and not state["charging"]
        was_low, self._battery_was_low = self._battery_was_low, low
        if low and not was_low:
            return {"type": "alert", "kind": "battery", "percent": state["percent"],
                    "message": f"This PC is at {state['percent']}% and not charging."}
        return {}

    async def _settle_and_publish(self, target_id: str) -> None:
        """Wait for the desktop to react, then push the row that was pressed."""
        await asyncio.sleep(ACTION_SETTLE)
        if self._wake_target != target_id:
            return
        try:
            if await self._publish_partial(target_id):
                self._wake_target = ""
        except Exception as e:
            print(f"Error publishing {target_id}: {e}")

    async def _publish_partial(self, target_id: str) -> bool:
        """Refresh one source and push it. False when there is nothing to push."""
        if not target_id or not len(self.live):
            return False
        from vt.state import refresh_for

        refreshed = await self._run_refresh(target_id, refresh_for, target_id)
        if refreshed is None:
            return False
        prefixes, targets = refreshed

        snapshot = self._snapshot_cache
        kept = [t for t in snapshot.targets
                if not any(t.id.startswith(prefix) for prefix in prefixes)]
        merged = Snapshot(targets=kept + targets, ts=time.time())
        # Sorted the same way a full collection is, so the phone is not handed
        # a different order for a moment.
        merged.targets.sort(key=snapshot_order)
        merged.targets.extend(self._phone_targets())
        self._snapshot_cache = merged
        self._snapshot_ts = merged.ts
        await self.live.publish(merged)
        return True

    def _run_due_jobs(self) -> None:
        """Run any scheduled action whose time has come, and log what ran."""
        from vt.schedule import scheduler

        for job, result in scheduler().run_due():
            self.auth.audit.record(
                "schedule.fire", who="timer", device="", ok=bool(result.get("ok")),
                detail=f"{job['target']} {job['action']}: {result.get('message', '')}",
            )

    # --- notifications on the socket ----------------------------------------

    # How long a new notification waits before being pushed. Long enough for
    # the daemon's reply -- and so for the id that makes "Dismiss" work --
    # short enough that the phone still buzzes while the PC's banner is up.
    NOTIFICATION_SETTLE = 0.3

    def _watch_notifications(self, feed) -> None:
        """Have the mirror push to the live channel instead of being polled."""
        if feed.on_entry is None:
            feed.on_entry = self._notification_arrived

    def _notification_arrived(self, entry: dict) -> None:
        """Called on the mirror's reader thread. Hands over to the loop."""
        loop = self._loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(self._queue_notification, entry)
        except RuntimeError:
            pass

    def _queue_notification(self, entry: dict) -> None:
        self._pending_notifications.append(entry)
        if self._notification_task is None or self._notification_task.done():
            self._notification_task = asyncio.create_task(self._flush_notifications())

    async def _flush_notifications(self) -> None:
        await asyncio.sleep(self.NOTIFICATION_SETTLE)
        entries, self._pending_notifications = self._pending_notifications, []
        if not entries:
            return
        # The entries are the mirror's own dicts, so the id attached during the
        # wait is already in them by the time they are copied out here.
        if len(self.live):
            await self.live.broadcast({"type": "notification", "entries": list(entries)})

        # And to the phones that are not looking: this is the whole point of
        # push, and the reason a closed page stopped being a dead end.
        newest = entries[-1]
        await self.push_out({
            "title": newest.get("summary") or newest.get("app") or "Notification",
            "body": newest.get("body") or newest.get("app") or "",
            "tag": f"notification-{newest.get('seq', 0)}",
            "url": "/?go=notifs",
        })

    async def push_out(self, payload: dict) -> int:
        """Send one payload to every subscribed phone that is not connected.

        Returns how many were reached. A push service saying the subscription
        is gone means the browser dropped it, so it is forgotten here rather
        than retried forever.
        """
        from vt import push

        if not push.available():
            return 0
        pending = [entry for entry in self.push_subscriptions.all()
                   if entry.get("device") not in self._connected_devices]
        if not pending:
            return 0

        sent = 0
        for entry in pending:
            result = await self._run_blocking(push.send, entry, payload)
            if result.get("ok"):
                sent += 1
            elif result.get("gone"):
                self.push_subscriptions.remove(entry["endpoint"])
                self.auth.audit.record(
                    "push.dropped", device=entry.get("device", ""), ok=False,
                    detail=result.get("message", ""),
                )
        return sent

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

    # --- installable web app ------------------------------------------------

    def _ui_file(self, name: str) -> Path:
        return Path(__file__).parent / "ui" / name

    async def handle_asset(self, request: web.Request) -> web.Response:
        """Serve one of the app's own static files by name.

        Unauthenticated on purpose: the icon and the manifest are what the
        browser fetches before anyone has typed a credential, and they say
        nothing about the PC.
        """
        name = request.path.lstrip("/")
        if name not in STATIC_ASSETS:
            raise web.HTTPNotFound()
        path = self._ui_file(name)
        if not path.exists():
            raise web.HTTPNotFound()
        content_type, cache = STATIC_ASSETS[name]
        return web.Response(
            body=path.read_bytes(),
            content_type=content_type,
            headers={
                "Cache-Control": cache,
                # The worker controls the whole origin, not just /ui.
                "Service-Worker-Allowed": "/",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            },
        )

    async def handle_share(self, request: web.Request) -> web.Response:
        """POST /share — the Android share sheet, when no worker caught it.

        The service worker normally intercepts this and hands the payload to
        the page, which has the credential. Reaching the server means there is
        no worker yet, and a share POST cannot be authorized: it carries no
        headers. So say that, rather than showing a browser error.
        """
        return self._html_response(_SHARE_FALLBACK_PAGE)

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

        terms = auth.codes.redeem_terms(code)
        if terms is None:
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
            device_id, secret = auth.devices.register(
                name, scope=terms["scope"], expires_in=terms["device_ttl"]
            )
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
        if principal["kind"] == "device":
            # A device already has a credential, and minting a second one here
            # would hand a guest a full-scope, never-expiring replacement for
            # the limited one it was given. This route exists for the browser
            # that holds the LAN token and nothing else.
            return web.json_response(
                {
                    "ok": False,
                    "error": "forbidden",
                    "message": "This device is already paired.",
                },
                status=403,
            )
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
        refused = self._forbidden(principal, "admin")
        if refused is not None:
            return refused
        return web.json_response({
            "devices": self.auth.devices.list_devices(),
            "current": principal["id"],
        })

    async def handle_api_devices_revoke(self, request: web.Request) -> web.Response:
        """POST /api/devices/revoke — drop a device credential immediately."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "admin")
        if refused is not None:
            return refused
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

    # --- clipboard, input, notifications, files -----------------------------

    async def handle_api_clipboard(self, request: web.Request) -> web.Response:
        """GET /api/clipboard — what is on the PC's clipboard right now."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        # Reading is not the lesser half of this: the clipboard holds whatever
        # was copied last, which is sometimes a password.
        refused = self._forbidden(principal, "clipboard")
        if refused is not None:
            return refused
        from vt.sources.clipboard import read_text

        return web.json_response(await self._run_blocking(read_text))

    async def handle_api_clipboard_set(self, request: web.Request) -> web.Response:
        """POST /api/clipboard — put the phone's text on the PC's clipboard."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "clipboard")
        if refused is not None:
            return refused
        from vt.sources.clipboard import write_text

        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        text = str(data.get("text") or "")
        result = await self._run_blocking(write_text, text)
        if result.get("ok"):
            from vt.sources.clipboard_history import history

            # What the phone sent is now what the PC's clipboard holds, so it
            # belongs in the same list -- and it lands there whether or not the
            # poll happens to be running.
            history().record(text)
        # Logged like an action: pasting into the PC's clipboard is a change to
        # the PC, and the audit log is what answers "who did that?".
        self.auth.audit.record(
            "clipboard.set", ip=principal["ip"], who=principal["name"],
            device=principal["id"], ok=bool(result.get("ok")),
        )
        return web.json_response(result)

    async def handle_api_clipboard_history(self, request: web.Request) -> web.Response:
        """GET /api/clipboard/history — recent clips. DELETE — forget them."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "clipboard")
        if refused is not None:
            return refused
        from vt.sources.clipboard_history import history

        feed = history()
        if request.method == "DELETE":
            count = await self._run_blocking(feed.clear)
            # Worth a line in the log: clearing is the thing someone does after
            # copying a password, and "did that actually happen?" is the
            # question they ask next.
            self.auth.audit.record(
                "clipboard.history.clear", ip=principal["ip"], who=principal["name"],
                device=principal["id"], ok=True, detail=str(count),
            )
            return web.json_response({"ok": True, "cleared": count, "entries": []})

        # Started on first request, like the notification mirror: a session
        # that never opens this screen never runs the poll.
        feed.start()
        return web.json_response({
            "ok": True,
            "entries": feed.entries(),
            "running": feed.running,
            "error": feed.error,
        })

    async def handle_api_diagnostics(self, request: web.Request) -> web.Response:
        """GET /api/diagnostics — what works and what does not, for the phone.

        `vt doctor` answers the same question in a terminal, which is where the
        person debugging usually is not.
        """
        principal, error = self._authorize(request)
        if error is not None:
            return error
        # It names paths, packages and the state of the machine's services --
        # useful to whoever owns the PC, and nothing a visitor needs.
        refused = self._forbidden(principal, "system")
        if refused is not None:
            return refused
        from vt import diagnostics

        return web.json_response(await self._run_blocking(diagnostics.collect))

    async def handle_api_wake(self, request: web.Request) -> web.Response:
        """POST /api/wake — send a wake-on-LAN packet to another machine."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "system")
        if refused is not None:
            return refused
        from vt.sources.wake import wake

        try:
            data = await request.json()
        except Exception:
            data = {}
        result = await self._run_blocking(wake, str((data or {}).get("mac") or ""))
        self.auth.audit.record(
            "wake.send", ip=principal["ip"], who=principal["name"],
            device=principal["id"], ok=bool(result.get("ok")),
        )
        return web.json_response(result)

    async def handle_api_open(self, request: web.Request) -> web.Response:
        """POST /api/open — open a link from the phone in the PC's browser."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "open")
        if refused is not None:
            return refused
        from vt.sources.open_url import open_url

        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        result = await self._run_blocking(open_url, str(data.get("url") or ""))
        # Audited like any other change to the PC: something appeared on the
        # screen, and the log is what answers "who put it there?".
        self.auth.audit.record(
            "open.url", ip=principal["ip"], who=principal["name"],
            device=principal["id"], ok=bool(result.get("ok")),
            detail=result.get("url", ""),
        )
        return web.json_response(result)

    async def handle_api_input(self, request: web.Request) -> web.Response:
        """POST /api/input — pointer, scroll, typing and key chords.

        Separate from /api/do because it is not an action on a target: a
        trackpad streams deltas at 20 Hz, and every one of them would otherwise
        be one audit line and one snapshot lookup.
        """
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "input")
        if refused is not None:
            return refused
        from vt.sources.remote_input import execute as execute_input

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "message": "Invalid JSON"}, status=400)
        if not isinstance(data, dict):
            return web.json_response({"ok": False, "message": "Invalid JSON"}, status=400)

        op = str(data.get("op") or "")
        result = await self._run_blocking(execute_input, op, data)
        # Pointer motion is not recorded: at 20 Hz it would bury every other
        # line in the log. What was typed and which chords were sent are the
        # parts someone reading the log afterwards would want.
        if op in ("type", "keys"):
            typed = len(str(data.get("text") or ""))
            detail = str(data.get("keys") or "")[:60] if op == "keys" else f"{typed} chars"
            self.auth.audit.record(
                "input", ip=principal["ip"], who=principal["name"],
                device=principal["id"], op=op, detail=detail,
                ok=bool(result.get("ok")),
            )
        return web.json_response(result)

    async def handle_api_art(self, request: web.Request) -> web.Response:
        """GET /api/art?k= — album art for a key some player published."""
        _, error = self._authorize(request)
        if error is not None:
            return error
        from vt.sources.art import fetch, url_for

        art_url = url_for(request.query.get("k", ""))
        if not art_url:
            raise web.HTTPNotFound()
        data, content_type = await self._run_blocking(fetch, art_url)
        if not data:
            raise web.HTTPNotFound()
        return web.Response(
            body=data, content_type=content_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )

    async def handle_api_audit(self, request: web.Request) -> web.Response:
        """GET /api/audit — the recent security log, for reading on the phone.

        A log nobody can read is a log nobody checks, and the pitch here is
        "expose your desktop to the internet". Rejections belong on the phone
        as prominently as actions.
        """
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "admin")
        if refused is not None:
            return refused
        try:
            count = min(200, max(1, int(request.query.get("count", "60"))))
        except ValueError:
            count = 60
        entries = await self._run_blocking(self.auth.audit.tail, count)
        return web.json_response({"entries": entries})

    async def handle_api_screenshot(self, request: web.Request) -> web.Response:
        """GET /api/screenshot — one still frame, taken now, kept nowhere."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "screenshot")
        if refused is not None:
            return refused
        from vt.sources.screenshot import (
            available, capture, read_and_remove, unavailable_message,
        )

        if not await self._run_blocking(available):
            return web.json_response(
                {"ok": False, "message": unavailable_message()}, status=503
            )

        result = await self._run_blocking(capture)
        self.auth.audit.record(
            "screenshot", ip=principal["ip"], who=principal["name"],
            device=principal["id"], ok=bool(result.get("ok")),
        )
        if not result.get("ok"):
            return web.json_response(result, status=403)

        try:
            data = await self._run_blocking(read_and_remove, result["path"])
        except OSError as e:
            return web.json_response({"ok": False, "message": str(e)}, status=500)
        return web.Response(
            body=data, content_type="image/png", headers={"Cache-Control": "no-store"}
        )

    async def handle_api_notifications(self, request: web.Request) -> web.Response:
        """GET /api/notifications — desktop notifications since ?since=."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        # Messages, delivery codes, whatever an app decided to put on screen.
        # A visitor's phone has no business with any of it.
        refused = self._forbidden(principal, "notifications")
        if refused is not None:
            return refused
        from vt.sources.notifications_mirror import mirror

        feed = mirror()
        # Started on first request rather than at startup: a session that never
        # opens the notifications screen has no reason to run a bus monitor.
        started = feed.start()
        # From here on the mirror pushes as well as answering polls, so a phone
        # holding a socket hears about a notification when it happens rather
        # than up to three seconds later.
        self._watch_notifications(feed)
        try:
            since = int(request.query.get("since", "0"))
        except ValueError:
            since = 0
        return web.json_response({
            "ok": started,
            "entries": feed.entries(since),
            "error": feed.error,
            "running": feed.running,
            "muted": feed.muted(),
        })

    # A phone cannot check whether another PC is up: the browser refuses a
    # cross-origin request to an origin that has not opted in, and this page's
    # own CSP says connect-src 'self'. So the PC checks, and answers yes or no.
    MAX_PROBE_URLS = 10
    PROBE_TIMEOUT = 2.5

    async def handle_api_probe(self, request: web.Request) -> web.Response:
        """POST /api/probe — is each of these saved servers answering?

        Deliberately a yes or no. Not the status code, not a header, not a byte
        of the body: the answer is exactly what a switcher needs to grey out a
        machine, and nothing that would make this desktop a port scanner with a
        readable result.

        Reachable *from the PC*. A phone on mobile data may still not reach a
        machine the PC can see, which is why the page says where the answer
        came from rather than promising the phone can connect.
        """
        principal, error = self._authorize(request)
        if error is not None:
            return error
        # Asking this desktop whether an arbitrary host answers is a small
        # amount of reach, and a guest phone has none of it.
        refused = self._forbidden(principal, "system")
        if refused is not None:
            return refused
        try:
            data = await request.json()
        except Exception:
            data = {}
        urls = (data or {}).get("urls")
        if not isinstance(urls, list):
            return web.json_response({"ok": False, "message": "urls must be a list"}, status=400)

        wanted = [u for u in urls if isinstance(u, str)][: self.MAX_PROBE_URLS]
        results = await asyncio.gather(*(self._probe(url) for url in wanted))
        return web.json_response({"ok": True, "servers": list(results)})

    async def _probe(self, url: str) -> dict:
        """Whether one origin answers. Never says anything else about it."""
        origin = probe_origin(url)
        if not origin:
            return {"url": url, "reachable": False, "checked": False}
        import aiohttp

        try:
            timeout = aiohttp.ClientTimeout(total=self.PROBE_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # No credential travels with this: the point is whether the
                # machine answers at all, and 401 is an answer.
                async with session.get(f"{origin}/api/session", allow_redirects=False):
                    return {"url": url, "reachable": True, "checked": True}
        except Exception:
            return {"url": url, "reachable": False, "checked": True}

    async def handle_api_push_key(self, request: web.Request) -> web.Response:
        """GET /api/push/key — what a browser needs to subscribe."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "notifications")
        if refused is not None:
            return refused
        from vt import push

        if not push.available():
            return web.json_response({"ok": False, "available": False, "key": "",
                                      "subscribed": False, "message": push.MISSING})
        key = await self._run_blocking(push.public_key)
        return web.json_response({
            "ok": True,
            "available": True,
            "key": key,
            "subscribed": bool(self.push_subscriptions.for_device(principal["id"])),
        })

    async def handle_api_push_subscribe(self, request: web.Request) -> web.Response:
        """POST /api/push/subscribe — remember where to reach a closed page."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "notifications")
        if refused is not None:
            return refused
        try:
            data = await request.json()
        except Exception:
            data = {}
        subscription = (data or {}).get("subscription") or {}
        added = self.push_subscriptions.add(
            subscription, device_id=principal["id"], name=principal["name"]
        )
        if not added:
            return web.json_response(
                {"ok": False, "message": "That is not a usable subscription"}, status=400
            )
        self.auth.audit.record(
            "push.subscribe", ip=principal["ip"], who=principal["name"],
            device=principal["id"], ok=True,
        )
        return web.json_response({"ok": True, "message": "This phone will be told with the page closed"})

    async def handle_api_push_unsubscribe(self, request: web.Request) -> web.Response:
        """POST /api/push/unsubscribe — forget one, or this device's own."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "notifications")
        if refused is not None:
            return refused
        try:
            data = await request.json()
        except Exception:
            data = {}
        endpoint = str((data or {}).get("endpoint") or "")
        if endpoint:
            removed = self.push_subscriptions.remove(endpoint)
        else:
            # No endpoint given: the phone is saying "stop telling me", and it
            # may have lost track of the subscription it made.
            removed = False
            for entry in self.push_subscriptions.for_device(principal["id"]):
                removed = self.push_subscriptions.remove(entry["endpoint"]) or removed
        self.auth.audit.record(
            "push.unsubscribe", ip=principal["ip"], who=principal["name"],
            device=principal["id"], ok=removed,
        )
        return web.json_response({"ok": True, "removed": removed})

    async def handle_api_notifications_mute(self, request: web.Request) -> web.Response:
        """POST /api/notifications/mute — stop mirroring one app, or start again."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "notifications")
        if refused is not None:
            return refused
        from vt.sources.notifications_mirror import mirror

        try:
            data = await request.json()
        except Exception:
            data = {}
        app = str((data or {}).get("app") or "").strip()
        if not app:
            return web.json_response(
                {"ok": False, "message": "Which app?"}, status=400
            )
        feed = mirror()
        # `muted: false` is how the phone asks for an app back, so one endpoint
        # covers both directions and the phone never has to guess which it is.
        wants_mute = bool((data or {}).get("muted", True))
        if wants_mute:
            feed.mute(app)
            message = f"{app} muted for now"
        else:
            feed.unmute(app)
            message = f"{app} is back"
        self.auth.audit.record(
            "notifications.mute", ip=principal["ip"], who=principal["name"],
            device=principal["id"], ok=True, detail=f"{app}={'muted' if wants_mute else 'on'}",
        )
        return web.json_response({"ok": True, "message": message, "muted": feed.muted()})

    async def handle_api_notifications_dismiss(self, request: web.Request) -> web.Response:
        """POST /api/notifications/dismiss — clear one banner on the PC."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "notifications")
        if refused is not None:
            return refused
        from vt.sources.notifications_mirror import dismiss

        try:
            data = await request.json()
        except Exception:
            data = {}
        try:
            notification_id = int((data or {}).get("id") or 0)
        except (TypeError, ValueError):
            notification_id = 0
        if notification_id <= 0:
            return web.json_response(
                {"ok": False, "message": "That notification has no id to close"},
                status=400,
            )

        result = await self._run_blocking(dismiss, notification_id)
        self.auth.audit.record(
            "notification.dismiss", ip=principal["ip"], who=principal["name"],
            device=principal["id"], id=notification_id, ok=bool(result.get("ok")),
        )
        return web.json_response(result)

    async def handle_api_files(self, request: web.Request) -> web.Response:
        """GET /api/files — what has been transferred, newest first."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "files")
        if refused is not None:
            return refused
        from vt.sources.transfer import list_files, transfer_dir

        files = await self._run_blocking(list_files)
        return web.json_response({"files": files, "dir": str(transfer_dir())})

    async def _upload_field(self, request: web.Request):
        """The multipart part holding the file, or the response to send back."""
        try:
            reader = await request.multipart()
            field = await reader.next()
        except Exception:
            return web.json_response(
                {"ok": False, "message": "Malformed upload"}, status=400
            )
        while field is not None and field.name != "file":
            field = await reader.next()
        if field is None:
            return web.json_response(
                {"ok": False, "message": "No file in the upload"}, status=400
            )
        return field

    async def handle_api_upload(self, request: web.Request) -> web.Response:
        """POST /api/upload — receive a file from the phone.

        Streamed to disk a chunk at a time: a 100 MB upload read into memory
        first would be 100 MB of the server's RSS, on a machine that is also
        playing the video the phone is controlling.
        """
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "files")
        if refused is not None:
            return refused
        from vt.sources.transfer import MAX_BYTES, human_size, unique_path

        field = await self._upload_field(request)
        if isinstance(field, web.Response):
            return field

        path = await self._run_blocking(unique_path, field.filename or "upload")
        size = 0
        try:
            with open(path, "wb") as handle:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("too large")
                    handle.write(chunk)
        except ValueError:
            path.unlink(missing_ok=True)
            return web.json_response(
                {"ok": False, "message": f"File is larger than {human_size(MAX_BYTES)}"},
                status=413,
            )
        except Exception as e:
            path.unlink(missing_ok=True)
            return web.json_response({"ok": False, "message": f"Upload failed: {e}"}, status=500)

        self.auth.audit.record(
            "file.upload", ip=principal["ip"], who=principal["name"],
            device=principal["id"], name=path.name, bytes=size,
        )
        print(f"\n  ✓ Received {path.name} ({human_size(size)}) from {principal['name']} → {path.parent}\n")
        return web.json_response({
            "ok": True,
            "name": path.name,
            "size": size,
            "message": f"Sent {path.name} ({human_size(size)}) to the PC",
        })

    async def handle_api_download(self, request: web.Request) -> web.Response:
        """GET /api/files/{name} — send a transferred file back to the phone."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "files")
        if refused is not None:
            return refused
        from vt.sources.transfer import resolve

        path = await self._run_blocking(resolve, request.match_info.get("name", ""))
        if path is None:
            return web.json_response({"ok": False, "message": "No such file"}, status=404)
        self.auth.audit.record(
            "file.download", ip=principal["ip"], who=principal["name"],
            device=principal["id"], name=path.name,
        )
        return web.FileResponse(
            path,
            headers={
                "Content-Disposition": f'attachment; filename="{path.name}"',
                "Content-Type": "application/octet-stream",
            },
        )

    async def handle_api_file_wallpaper(self, request: web.Request) -> web.Response:
        """POST /api/files/wallpaper — use a transferred picture as the background."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        # The desktop's own appearance, not the file store: a guest who may
        # send a photo should not be able to change what the PC looks like.
        refused = self._forbidden(principal, "system")
        if refused is not None:
            return refused
        from vt.sources.transfer import resolve
        from vt.sources.wallpaper import set_from

        try:
            data = await request.json()
        except Exception:
            data = {}
        path = await self._run_blocking(resolve, str((data or {}).get("name") or ""))
        if path is None:
            return web.json_response({"ok": False, "message": "No such file"}, status=404)

        result = await self._run_blocking(set_from, path)
        self.auth.audit.record(
            "wallpaper.set", ip=principal["ip"], who=principal["name"],
            device=principal["id"], ok=bool(result.get("ok")), name=path.name,
        )
        return web.json_response(result)

    async def handle_api_file_open(self, request: web.Request) -> web.Response:
        """POST /api/files/open — open a received file on the PC."""
        principal, error = self._authorize(request)
        if error is not None:
            return error
        refused = self._forbidden(principal, "files")
        if refused is not None:
            return refused
        from vt.sources.transfer import open_in_desktop, resolve

        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        path = await self._run_blocking(resolve, str(data.get("name") or ""))
        if path is None:
            return web.json_response({"ok": False, "message": "No such file"}, status=404)
        result = await self._run_blocking(open_in_desktop, path)
        self.auth.audit.record(
            "file.open", ip=principal["ip"], who=principal["name"],
            device=principal["id"], name=path.name, ok=bool(result.get("ok")),
        )
        return web.json_response(result)

    # --- live channel -------------------------------------------------------

    def _phone_targets(self) -> list:
        """One row per connected phone that reports its own battery."""
        from vt.model import Target

        targets = []
        for index, phone in enumerate(self.phones.entries()):
            percent = int(phone["level"] * 100)
            targets.append(Target(
                id=f"phone:{index}",
                kind="system",
                title=phone["name"],
                subtitle=f"{percent}%" + (" · charging" if phone["charging"] else ""),
                icon="🔌" if phone["charging"] else "📱",
                status="charging" if phone["charging"] else "on battery",
            ))
        return targets

    async def handle_api_ws_ticket(self, request: web.Request) -> web.Response:
        """POST /api/ws-ticket — trade a credential for a socket ticket.

        A browser cannot put headers on a WebSocket handshake, and the device
        secret must never travel in a URL: it would land in proxy logs, browser
        history and the tunnel's own records, where it outlives the session by
        as long as those are kept. A ticket is good once, for seconds, for this
        caller only.
        """
        principal, error = self._authorize(request)
        if error is not None:
            return error
        ticket = self.tickets.issue(principal)
        return web.json_response({"ok": True, "ticket": ticket, "expires_in": int(TICKET_TTL)})

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """GET /ws — the live channel: snapshot patches out, input in."""
        principal = self.tickets.redeem(request.query.get("ticket", ""))
        if principal is None:
            ip, remote = self._client(request)
            self.auth.audit.record("auth.reject", reason="bad_ws_ticket", ip=ip)
            return self._unauthorized(remote)

        # aiohttp's own ping keeps a tunnel from reaping an idle socket, which
        # matters here precisely because a quiet PC sends nothing for minutes.
        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)
        await self.live.add(ws)
        # A phone looking at the page does not also need a push notification
        # for the same thing, so note that this device is here.
        device = principal.get("id") or ""
        if device:
            self._connected_devices.add(device)
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    data = message.json()
                except Exception:
                    continue
                if isinstance(data, dict):
                    await self._handle_live_message(ws, data, principal)
        finally:
            self.live.remove(ws)
            # A phone that closed the tab is not a phone whose battery the PC
            # still knows -- and is now a phone that wants push again.
            self.phones.forget(ws)
            if device:
                self._connected_devices.discard(device)
        return ws

    async def _handle_live_message(self, ws, data: dict, principal: dict) -> None:
        """One client -> server message on the live channel.

        Only two things travel this way. Pointer and scroll deltas, because at
        20 Hz a POST each is a request, a header set and an auth check per
        millimetre of thumb travel; and a resync, for a client that believes it
        has drifted.
        """
        kind = str(data.get("type") or "")
        if kind == "battery":
            went_low = self.phones.report(
                ws, principal.get("name", "Phone"),
                data.get("level") or 0.0, bool(data.get("charging")),
            )
            if went_low:
                # The phone's own warning is easy to miss from across the room,
                # which is the whole reason this direction exists. A banner,
                # not a sound: the PC is not the thing that needs finding.
                percent = int(float(data.get("level") or 0) * 100)
                await self._run_blocking(
                    notify,
                    f"{principal.get('name', 'Phone')} battery low",
                    f"{percent}% and not charging.",
                )
            # A phone that just changed its mind about its battery is a change
            # to the snapshot, and waiting out the tick would show it late.
            self._wake.set()
            return
        if kind in ("ring", "ring_stop"):
            if not scope_allows(principal.get("scope", DEFAULT_SCOPE), "system"):
                await ws.send_json({
                    "type": "ring_result", "ok": False,
                    "message": "This device is not allowed to do that (system).",
                })
                return
            from vt.sources import ring as ring_source

            # One message type either way, so a phone that loses the reply can
            # silence the PC with the flag rather than a second vocabulary.
            silence = kind == "ring_stop" or bool(data.get("stop"))
            call = ring_source.stop if silence else ring_source.ring
            await ws.send_json({"type": "ring_result", **await self._run_blocking(call)})
            self._wake.set()
            return
        if kind == "resync":
            await ws.send_json(self.live.state_message())
            return
        if kind == "ping":
            await ws.send_json({"type": "pong"})
            return
        if kind != "input":
            return

        if not scope_allows(principal.get("scope", DEFAULT_SCOPE), "input"):
            # The pad streams at 20 Hz, so this must not become 20 audit lines
            # a second: the REST route logs the refusal, and here the phone is
            # simply told once per message that it may not.
            if data.get("id") is not None:
                await ws.send_json({
                    "type": "input_result", "id": data["id"], "ok": False,
                    "message": "This device is not allowed to do that (input).",
                })
            return

        from vt.sources.remote_input import execute as execute_input

        op = str(data.get("op") or "")
        result = await self._run_blocking(execute_input, op, data)
        # Same rule as /api/input: motion is not worth a log line each, what was
        # typed is. Keeping the two paths identical is what stops the socket
        # from becoming a way to type unaudited.
        if op in ("type", "keys"):
            typed = len(str(data.get("text") or ""))
            detail = str(data.get("keys") or "")[:60] if op == "keys" else f"{typed} chars"
            self.auth.audit.record(
                "input", ip=principal["ip"], who=principal["name"],
                device=principal["id"], op=op, detail=detail,
                ok=bool(result.get("ok")), via="ws",
            )
        if data.get("id") is not None:
            await ws.send_json({"type": "input_result", "id": data["id"], **result})

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

        # Which permission this target belongs to: "turn the volume down" and
        # "shut the machine down" are both system rows and must not be one
        # permission.
        refused = self._forbidden(principal, capability_for(str(target_id)))
        if refused is not None:
            return refused

        result = await self._run_blocking(execute_action, target_id, action_id, value)
        # The phone that pressed this is watching for the result on the live
        # channel; waiting out the rest of the collector's second is what makes
        # a remote feel slow even when the PC reacted instantly.
        self._wake_target = str(target_id)
        self._wake.set()
        # Answer this row without waiting for the collector to be free: the
        # loop does the same thing a moment later, and whichever gets there
        # first clears the flag so the phone is not sent it twice.
        asyncio.create_task(self._settle_and_publish(str(target_id)))
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
        app.router.add_get("/api/clipboard", self.handle_api_clipboard)
        app.router.add_post("/api/clipboard", self.handle_api_clipboard_set)
        app.router.add_get("/api/clipboard/history", self.handle_api_clipboard_history)
        app.router.add_delete("/api/clipboard/history", self.handle_api_clipboard_history)
        app.router.add_get("/api/diagnostics", self.handle_api_diagnostics)
        app.router.add_post("/api/open", self.handle_api_open)
        app.router.add_post("/api/wake", self.handle_api_wake)
        app.router.add_post("/api/input", self.handle_api_input)
        app.router.add_get("/api/notifications", self.handle_api_notifications)
        app.router.add_post(
            "/api/notifications/dismiss", self.handle_api_notifications_dismiss
        )
        app.router.add_post("/api/notifications/mute", self.handle_api_notifications_mute)
        app.router.add_get("/api/push/key", self.handle_api_push_key)
        app.router.add_post("/api/push/subscribe", self.handle_api_push_subscribe)
        app.router.add_post("/api/push/unsubscribe", self.handle_api_push_unsubscribe)
        app.router.add_get("/api/audit", self.handle_api_audit)
        app.router.add_post("/api/probe", self.handle_api_probe)
        app.router.add_get("/api/screenshot", self.handle_api_screenshot)
        app.router.add_get("/api/art", self.handle_api_art)
        app.router.add_get("/api/files", self.handle_api_files)
        app.router.add_post("/api/upload", self.handle_api_upload)
        # Registered after /api/files so the literal path wins over the pattern.
        app.router.add_post("/api/files/open", self.handle_api_file_open)
        app.router.add_post("/api/files/wallpaper", self.handle_api_file_wallpaper)
        app.router.add_get("/api/files/{name}", self.handle_api_download)
        app.router.add_post("/api/do", self.handle_api_do)
        app.router.add_post("/api/ws-ticket", self.handle_api_ws_ticket)
        app.router.add_get("/ws", self.handle_ws)
        app.router.add_post("/share", self.handle_share)
        for name in STATIC_ASSETS:
            app.router.add_get(f"/{name}", self.handle_asset)
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

    def scheme(self) -> str:
        return "https" if self.tls else "http"

    def _print_how_to_get_in(self, base: str, url: str):
        """The half of the banner that says how a phone reaches this server."""
        if self.auth.require_pairing:
            print("  Mode: pairing required (token auth off)")
            print(f"  Local URL: {base}")
            print("  Pair a phone with:  vt pair\n")
            return
        print(f"  URL: {url}")
        if not self.token:
            print("  WARNING: token auth disabled -- anyone on this network can control this PC.")
            print("           (Off-network callers still need a paired device.)")
        print()
        print("  📱 On your phone:")
        print("     1. Open this URL in any browser")
        print("     2. Bookmark it (token saved in localStorage)")
        print("     3. Control your PC!\n")

    def _print_tls(self):
        """The fingerprint, and the warning that goes with a self-signed one."""
        print(f"  TLS: on, with this PC's own certificate ({self.tls_info['names'][0]})")
        print(f"  Fingerprint: {self.tls_info['fingerprint']}")
        print("  The phone will warn the first time; check that fingerprint, accept it once.")
        print()

    def _print_banner(self):
        base = f"{self.scheme()}://{self.host}:{self.port}/"
        url = f"{base}?t={self.token}" if self.token else base
        print("\n  ╔════════════════════════════════════════════╗")
        print("  ║          VoiceTalk Remote Control          ║")
        print("  ╚════════════════════════════════════════════╝\n")

        self._print_how_to_get_in(base, url)

        if self.tls and self.tls_info.get("ok"):
            self._print_tls()

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
        elif not shell.is_available():
            self._print_extension_note()

        print("  Press Ctrl+C to stop.\n")

    def _print_extension_note(self):
        """Say the extension is not loaded, and name the fix that fits.

        Stated once, at startup, as a note rather than an error: the server
        runs fine without the extension, it just serves fewer controls. Saying
        nothing is what left people tapping a touchpad that could never have
        worked -- and telling someone whose install is fine to rerun the
        installer is what made `make dev` read as contradicting the setup it
        had just run.
        """
        code, detail = shell.status()
        print("  Note: the GNOME extension is not loaded — no window, workspace,")
        print("        touchpad or typing control. Media, apps, volume and system")
        print("        controls work.")
        if code == "pending-login":
            print("        It is installed and enabled: log out and back in to load it.\n")
        elif code == "error":
            print(f"        {detail}\n")
        else:
            print(f"        {detail}.")
            print("        Fix: vt install-extension, then log out and back in.\n")

    async def run(self):
        """Start the server."""
        app = self.make_app()

        # Start the snapshot refresh task. Hold the reference: the event loop
        # only keeps a weak one, so a bare create_task can be collected mid-flight.
        self._loop = asyncio.get_running_loop()
        self._refresh_task = asyncio.create_task(self._refresh_snapshot())

        runner = web.AppRunner(app)
        await runner.setup()
        ssl_context = None
        if self.tls:
            from vt import tls as tls_mod
            from vt.auth import config_dir

            self.tls_info = await self._run_blocking(tls_mod.context, config_dir(), self.host)
            if not self.tls_info.get("ok"):
                print(f"\n  ✗ {self.tls_info.get('message', 'TLS is unavailable')}")
                print("     Starting without it.\n")
                self.tls = False
            else:
                ssl_context = self.tls_info["context"]
        site = web.TCPSite(runner, self.host, self.port, ssl_context=ssl_context)
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
            # The mirror holds a dbus-monitor subprocess; a daemon thread would
            # not keep the process alive, but the monitor would outlive it.
            from vt.sources.notifications_mirror import mirror
            mirror().stop()
            # Close live sockets before the runner goes: a phone then sees a
            # clean close and reconnects when the server comes back, rather
            # than sitting on a socket whose other end has quietly gone.
            await self.live.close_all()
            self._fast_worker.shutdown(wait=False)
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
    tls: bool = False,
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
        tls=tls,
    )
    if pair_on_start:
        server.pending_pair_code = server.auth.codes.issue("startup")
    if open_browser:
        import threading
        import webbrowser
        base = f"{server.scheme()}://{host}:{port}/"
        target = f"{base}?t={server.token}" if server.token else base
        threading.Timer(1.0, lambda: webbrowser.open(target)).start()
    asyncio.run(server.run())
