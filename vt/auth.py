"""Device pairing, credential storage, rate limiting, and audit logging.

All of this exists so the server can sit behind a public URL -- a Cloudflare
Tunnel, typically -- without that URL alone being enough to control the PC.
On the LAN the single startup token is still the whole story. A request that
arrives from off-network has to carry a paired-device credential instead, and
a device is paired exactly once, from a code that only appears on the PC's own
terminal.
"""

import hashlib
import ipaddress
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ambiguous glyphs (0/O, 1/I/L) are left out: a pairing code gets read off a
# terminal and typed into a phone whenever the QR will not scan.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 10
CODE_TTL = 600.0

DEVICE_SECRET_BYTES = 32
MAX_DEVICES = 32
MAX_NAME_LENGTH = 48

# A rejected credential is never a typo the user will fix by retrying, so the
# window can be wide and the allowance small without getting in anyone's way.
FAIL_LIMIT = 5
FAIL_WINDOW = 900.0
LOCKOUT = 900.0

# Guessing a code is 31**10 work per attempt, so the per-IP limit is what
# actually matters. The global one only exists to close off a botnet spreading
# those guesses across thousands of source addresses.
GLOBAL_PAIR_LIMIT = 30
GLOBAL_PAIR_WINDOW = 3600.0
GLOBAL_PAIR_LOCKOUT = 600.0

AUDIT_MAX_BYTES = 5 * 1024 * 1024

# Headers a reverse proxy uses to report the real client. cloudflared sets the
# first one; the others are here for nginx or Caddy in front of vt.
PROXY_IP_HEADERS = ("CF-Connecting-IP", "X-Real-IP", "X-Forwarded-For")


class AuthError(Exception):
    """A credential store could not be read or written."""


def config_dir() -> Path:
    """Directory holding devices.json, alongside commands.toml."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "voicetalk"


def state_dir() -> Path:
    """Directory holding the audit log."""
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "voicetalk"


# --- credentials ------------------------------------------------------------

def _hash_secret(secret: str) -> str:
    """Hash a device secret for storage.

    Plain SHA-256 rather than a slow KDF on purpose: the secret is 32 random
    bytes we generated, not a password anyone chose, so there is no dictionary
    to grind and nothing for bcrypt's work factor to buy.
    """
    return hashlib.sha256((secret or "").encode("utf-8")).hexdigest()


# Compared against when the device id is unknown, so a bad id and a bad secret
# cost the same wall-clock time.
_DUMMY_HASH = _hash_secret("")


def clean_name(name: str) -> str:
    """Normalize a user-supplied device name for storage and display."""
    text = "".join(c for c in (name or "") if c.isprintable()).strip()
    return text[:MAX_NAME_LENGTH] or "device"


def format_code(code: str) -> str:
    """Group a code for display: RRMFH-2QK9X reads back far better than the run."""
    half = len(code) // 2
    return f"{code[:half]}-{code[half:]}"


def normalize_code(text: str) -> str:
    """Strip a typed code down to its alphabet, so dashes and case do not matter."""
    return "".join(c for c in (text or "").upper() if c in CODE_ALPHABET)


class DeviceStore:
    """Paired devices, persisted to a 0600 JSON file."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else config_dir() / "devices.json"
        self._devices: dict = {}
        self._load()

    def _load(self):
        try:
            raw = json.loads(self.path.read_text())
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            # A corrupt store must not quietly become an empty one. That would
            # unpair every phone, and the only symptom would be the phones
            # asking to pair again -- which reads as a bug, not a warning.
            raise AuthError(f"{self.path} is unreadable: {e}") from e
        for entry in raw.get("devices", []):
            if isinstance(entry, dict) and entry.get("id") and entry.get("secret_hash"):
                self._devices[str(entry["id"])] = entry

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"version": 1, "devices": list(self._devices.values())}, indent=2
        )
        tmp = self.path.with_name(self.path.name + ".tmp")
        # 0600 is set by os.open before any content lands. These are not
        # password hashes, but the file does record where and when the PC gets
        # used, and a later chmod would leave a window where it did not.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(payload)
        os.replace(tmp, self.path)

    def register(self, name: str) -> tuple:
        """Create a device and return (device_id, secret). The secret is
        returned once and never stored in recoverable form."""
        if len(self._devices) >= MAX_DEVICES:
            raise AuthError(f"device limit reached ({MAX_DEVICES}); revoke one first")
        device_id = secrets.token_hex(8)
        secret = secrets.token_urlsafe(DEVICE_SECRET_BYTES)
        self._devices[device_id] = {
            "id": device_id,
            "name": clean_name(name),
            "secret_hash": _hash_secret(secret),
            "created": time.time(),
            "last_seen": 0.0,
            "last_ip": "",
        }
        self._save()
        return device_id, secret

    def verify(self, device_id: str, secret: str) -> Optional[dict]:
        """Return the device entry when the credential is valid, else None."""
        entry = self._devices.get(device_id or "")
        supplied = _hash_secret(secret)
        if entry is None:
            secrets.compare_digest(supplied, _DUMMY_HASH)
            return None
        if not secrets.compare_digest(supplied, str(entry.get("secret_hash", ""))):
            return None
        return entry

    def touch(self, device_id: str, ip: str):
        """Record that a device was just seen."""
        entry = self._devices.get(device_id)
        if entry is None:
            return
        now = time.time()
        # The UI polls at 1 Hz. Writing the file on every request would mean a
        # disk write per second per phone, forever, to record a timestamp
        # nobody reads at that resolution.
        if now - float(entry.get("last_seen") or 0) < 60 and entry.get("last_ip") == ip:
            return
        entry["last_seen"] = now
        entry["last_ip"] = ip
        try:
            self._save()
        except OSError:
            pass

    def revoke(self, device_id: str) -> bool:
        if device_id not in self._devices:
            return False
        del self._devices[device_id]
        self._save()
        return True

    def revoke_all(self) -> int:
        count = len(self._devices)
        self._devices = {}
        self._save()
        return count

    def list_devices(self) -> list:
        """Devices as safe-to-serve dicts -- no secret_hash."""
        out = []
        for entry in self._devices.values():
            out.append({
                "id": entry["id"],
                "name": entry.get("name", "device"),
                "created": entry.get("created", 0.0),
                "last_seen": entry.get("last_seen", 0.0),
                "last_ip": entry.get("last_ip", ""),
            })
        out.sort(key=lambda d: d["created"])
        return out

    def __len__(self):
        return len(self._devices)


class PairingCodes:
    """Short-lived, single-use codes that authorize one device registration.

    Backed by a file rather than process memory because `vt pair` runs in a
    second terminal, not inside the server: an in-memory code issued by the CLI
    would be invisible to the process that has to redeem it. Concurrent writes
    can lose a code -- one user, two terminals, so the worst case is reissuing.
    """

    def __init__(self, path: Optional[Path] = None, ttl: float = CODE_TTL):
        self.path = Path(path) if path else config_dir() / "pairing.json"
        self.ttl = ttl

    def _read(self) -> dict:
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        now = time.time()
        live = {}
        for code, meta in (raw.get("codes") or {}).items():
            if isinstance(meta, dict) and float(meta.get("expires") or 0) > now:
                live[code] = meta
        return live

    def _write(self, codes: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"version": 1, "codes": codes}, f)
        os.replace(tmp, self.path)

    def issue(self, label: str = "") -> str:
        codes = self._read()
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        codes[code] = {"expires": time.time() + self.ttl, "label": label}
        self._write(codes)
        return code

    def redeem(self, text: str) -> bool:
        """Consume a code. False if unknown or expired; a code works once."""
        supplied = normalize_code(text)
        if len(supplied) != CODE_LENGTH:
            return False
        codes = self._read()
        # Every live code is compared, and the loop does not break on a hit:
        # a plain dict lookup would leak through timing whether a guessed
        # prefix was on the right track.
        matched = None
        for known in codes:
            if secrets.compare_digest(known, supplied):
                matched = known
        if matched is None:
            return False
        del codes[matched]
        self._write(codes)
        return True

    def active(self) -> list:
        return [
            {"code": code, "expires": meta["expires"], "label": meta.get("label", "")}
            for code, meta in sorted(self._read().items(), key=lambda kv: kv[1]["expires"])
        ]

    def clear(self) -> int:
        count = len(self._read())
        self._write({})
        return count


class RateLimiter:
    """Per-key failure counter with a lockout, keyed by client IP."""

    def __init__(self, limit: int = FAIL_LIMIT, window: float = FAIL_WINDOW,
                 lockout: float = LOCKOUT):
        self.limit = limit
        self.window = window
        self.lockout = lockout
        self._fails: dict = {}
        self._locked: dict = {}

    def _sweep(self, now: float):
        for key in [k for k, until in self._locked.items() if until <= now]:
            del self._locked[key]
        for key in [k for k, hits in self._fails.items()
                    if not hits or now - hits[-1] > self.window]:
            del self._fails[key]

    def retry_after(self, key: str) -> float:
        """Seconds left on the lockout, 0.0 when the key is free to try."""
        return max(0.0, self._locked.get(key, 0.0) - time.time())

    def record_failure(self, key: str) -> float:
        now = time.time()
        hits = [t for t in self._fails.get(key, []) if now - t < self.window]
        hits.append(now)
        self._fails[key] = hits
        if len(hits) >= self.limit:
            self._locked[key] = now + self.lockout
            self._fails[key] = []
        self._sweep(now)
        return self.retry_after(key)

    def record_success(self, key: str):
        self._fails.pop(key, None)
        self._locked.pop(key, None)


class AuditLog:
    """Append-only JSONL record of every authenticated action and auth failure."""

    def __init__(self, path: Optional[Path] = None, max_bytes: int = AUDIT_MAX_BYTES):
        self.path = Path(path) if path else state_dir() / "audit.log"
        self.max_bytes = max_bytes

    def _rotate_if_needed(self):
        try:
            if self.path.stat().st_size < self.max_bytes:
                return
        except OSError:
            return
        os.replace(self.path, self.path.with_name(self.path.name + ".1"))

    def record(self, event: str, **fields):
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": event,
        }
        entry.update(fields)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "a") as f:
                f.write(json.dumps(entry, separators=(",", ":"), default=str) + "\n")
        except OSError:
            # Losing an audit line must never turn into a failed request; the
            # log is evidence, not a dependency.
            pass

    def tail(self, count: int = 50) -> list:
        try:
            lines = self.path.read_text().splitlines()
        except OSError:
            return []
        out = []
        for line in lines[-count:]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


# --- network helpers --------------------------------------------------------

def _parse_ip(ip: str):
    try:
        # Strip a zone id (fe80::1%wlan0); ip_address rejects it.
        return ipaddress.ip_address((ip or "").split("%")[0])
    except ValueError:
        return None


def is_loopback_ip(ip: str) -> bool:
    addr = _parse_ip(ip)
    if addr is None:
        return False
    if addr.is_loopback:
        return True
    mapped = getattr(addr, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def is_private_ip(ip: str) -> bool:
    """True for loopback, RFC1918, and link-local addresses -- 'came from my
    own network', which is what the startup token is trusted for."""
    addr = _parse_ip(ip)
    if addr is None:
        return False
    if addr.is_loopback or addr.is_private or addr.is_link_local:
        return True
    # A dual-stack bind reports a LAN client as ::ffff:192.168.1.5, and the
    # is_private above does not unwrap that on every Python version.
    mapped = getattr(addr, "ipv4_mapped", None)
    return bool(mapped and (mapped.is_private or mapped.is_loopback or mapped.is_link_local))


def resolve_client_ip(peer: str, headers, trust_proxy: bool):
    """Return (client_ip, via_proxy) for a request.

    The proxy headers are read only for a loopback peer, which is what
    cloudflared is. Honouring them from anywhere would let a caller name their
    own client IP in a request header and walk around every rate limit here.

    via_proxy matters on its own, separately from the address it produced. A
    request that arrived through the tunnel came from outside this house even
    if it claims a 10.x source, so callers treat "via_proxy" as "remote" and do
    not re-derive that from the IP. Otherwise a forged CF-Connecting-IP would
    be a straight bypass of pairing, and the only thing standing in its way
    would be Cloudflare's edge remembering to overwrite the header.
    """
    if not trust_proxy or not is_loopback_ip(peer):
        return peer or "", False
    for name in PROXY_IP_HEADERS:
        value = (headers.get(name) or "").split(",")[0].strip()
        if value:
            return value, True
    return peer or "", False


class AuthManager:
    """Everything the server needs to decide whether a request may proceed."""

    def __init__(self, devices_path=None, audit_path=None, codes_path=None,
                 require_pairing: bool = False, trust_proxy: bool = False):
        self.devices = DeviceStore(devices_path)
        self.codes = PairingCodes(codes_path)
        self.audit = AuditLog(audit_path)
        self.auth_limiter = RateLimiter()
        self.pair_limiter = RateLimiter()
        self.global_pair_limiter = RateLimiter(
            limit=GLOBAL_PAIR_LIMIT,
            window=GLOBAL_PAIR_WINDOW,
            lockout=GLOBAL_PAIR_LOCKOUT,
        )
        # When set, the startup token stops being accepted anywhere and even a
        # LAN browser has to pair first.
        self.require_pairing = require_pairing
        self.trust_proxy = trust_proxy
