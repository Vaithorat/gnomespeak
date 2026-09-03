"""Web Push: reaching a phone whose page is closed.

This is the one row where an app beat us. A browser tab that is not open runs
no code, so notification mirroring and the PC's own alerts only ever arrived
while someone was looking. Web Push is the browser's answer to exactly that:
the page registers a subscription, the server posts to the endpoint the
browser handed back, and the service worker wakes up to show the notification.
No app, no store -- still a URL and a pairing code.

The encryption is RFC 8291 (aes128gcm) and the authorization is RFC 8292
(VAPID), both implemented here against `cryptography` rather than by pulling in
a push library: the library available today pins a newer `cryptography` than
this project's other tools accept, and the two specifications together are
about a hundred lines. The RFC's own worked example is in the test suite, so
this is checked against the standard rather than against itself.

`cryptography` is an optional dependency (`pip install gnomespeak[push]`).
Without it every function here degrades to "not available" with a reason,
exactly like the rest of the sources.
"""

import base64
import json
import os
import struct
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

try:
    from cryptography.hazmat.primitives import hashes, hmac, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTO = True
except ImportError:  # pragma: no cover - exercised on machines without it
    HAS_CRYPTO = False

# A record size larger than any notification this sends, so every message is a
# single record and the padding rules stay trivial.
RECORD_SIZE = 4096

# How long the push service should hold a message for a phone that is off.
DEFAULT_TTL = 12 * 3600

# VAPID's "sub" claim has to be a contact for whoever runs the server. This is
# a local desktop, not a service with an abuse address, so the value says that
# rather than inventing an email nobody reads.
VAPID_SUBJECT = "mailto:gnomespeak@localhost"

MISSING = (
    "Push needs the cryptography package. Install it with "
    "`pip install gnomespeak[push]` (or your distribution's python3-cryptography)."
)


def available() -> bool:
    return HAS_CRYPTO


# --- base64url --------------------------------------------------------------

def b64d(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode())


def b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


# --- key material -----------------------------------------------------------

def _config_dir() -> Path:
    from vt.auth import config_dir

    return config_dir()


def keys_path() -> Path:
    return _config_dir() / "push-keys.json"


_keys_lock = threading.Lock()


def vapid_keys() -> dict:
    """The server's push identity, generated once and kept 0600.

    The public half is handed to every phone that subscribes; the private half
    signs the request that proves this server is the one they subscribed to.
    """
    if not HAS_CRYPTO:
        return {}
    path = keys_path()
    with _keys_lock:
        try:
            stored = json.loads(path.read_text())
            if stored.get("private") and stored.get("public"):
                return stored
        except (OSError, ValueError):
            pass

        private = ec.generate_private_key(ec.SECP256R1())
        raw = private.private_numbers().private_value.to_bytes(32, "big")
        public = private.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint,
        )
        keys = {"private": b64e(raw), "public": b64e(public)}
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(keys, handle)
        return keys


def public_key() -> str:
    """The base64url key a browser needs to subscribe, or "" without crypto."""
    return vapid_keys().get("public", "")


def _private_key(keys: dict):
    return ec.derive_private_key(int.from_bytes(b64d(keys["private"]), "big"), ec.SECP256R1())


# --- RFC 8291 encryption ----------------------------------------------------

def _hmac_sha256(key: bytes, message: bytes) -> bytes:
    mac = hmac.HMAC(key, hashes.SHA256())
    mac.update(message)
    return mac.finalize()


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    """HKDF with a single output block, which is all this needs."""
    prk = _hmac_sha256(salt, ikm)
    return _hmac_sha256(prk, info + b"\x01")[:length]


def encrypt(payload: bytes, p256dh: str, auth: str,
            salt: bytes = None, ephemeral=None) -> bytes:
    """One aes128gcm record for a subscription, as RFC 8291 describes it.

    `salt` and `ephemeral` exist so the RFC's own worked example can be
    reproduced exactly; in use both are freshly random per message.
    """
    if not HAS_CRYPTO:
        raise RuntimeError(MISSING)

    ua_public_bytes = b64d(p256dh)
    auth_secret = b64d(auth)
    salt = salt if salt is not None else os.urandom(16)
    private = ephemeral if ephemeral is not None else ec.generate_private_key(ec.SECP256R1())

    as_public_bytes = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public_bytes)
    shared = private.exchange(ec.ECDH(), ua_public)

    # The key derivation is what binds the message to this subscription: the
    # receiver's key and the sender's ephemeral key both go into the info
    # string, so a message cannot be replayed at another subscription.
    key_info = b"WebPush: info\x00" + ua_public_bytes + as_public_bytes
    ikm = _hkdf(auth_secret, shared, key_info, 32)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)

    # 0x02 is the delimiter for the last record; there is only ever one here.
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    header = salt + struct.pack("!IB", RECORD_SIZE, len(as_public_bytes)) + as_public_bytes
    return header + ciphertext


# --- RFC 8292 authorization -------------------------------------------------

def vapid_header(endpoint: str, subject: str = VAPID_SUBJECT, expires_in: int = 12 * 3600) -> str:
    """The Authorization header proving who is sending this."""
    keys = vapid_keys()
    if not keys:
        raise RuntimeError(MISSING)
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        "exp": int(time.time()) + expires_in,
        "sub": subject,
    }
    header = {"typ": "JWT", "alg": "ES256"}
    signing_input = (
        b64e(json.dumps(header, separators=(",", ":")).encode()).encode()
        + b"."
        + b64e(json.dumps(claims, separators=(",", ":")).encode()).encode()
    )

    signature = _private_key(keys).sign(signing_input, ec.ECDSA(hashes.SHA256()))
    # JOSE wants the raw r||s pair, not the DER structure OpenSSL produces.
    r, s = asym_utils.decode_dss_signature(signature)
    raw = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    token = signing_input.decode() + "." + b64e(raw)
    return f"vapid t={token},k={keys['public']}"


# --- sending ----------------------------------------------------------------

def build_request(subscription: dict, payload: dict, ttl: int = DEFAULT_TTL):
    """The POST a push service should receive: encrypted body, signed headers.

    Separate from `send` so the bytes can be built and inspected -- and posted
    at a stand-in service in a test -- without anything reaching the network by
    accident.
    """
    import urllib.request

    endpoint = subscription["endpoint"]
    keys = subscription["keys"]
    body = encrypt(json.dumps(payload).encode(), keys["p256dh"], keys["auth"])
    return urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": vapid_header(endpoint),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(ttl),
            "Urgency": "normal",
        },
    )


def send(subscription: dict, payload: dict, ttl: int = DEFAULT_TTL, timeout: float = 10.0) -> dict:
    """Post one message. {"ok", "status", "gone"}; `gone` means unsubscribe.

    Uses urllib rather than a client library: it is one POST, and this file
    already carries the only two things that were hard.
    """
    import urllib.error
    import urllib.request

    if not HAS_CRYPTO:
        return {"ok": False, "status": 0, "gone": False, "message": MISSING}
    endpoint = str((subscription or {}).get("endpoint") or "")
    keys = (subscription or {}).get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        return {"ok": False, "status": 0, "gone": True, "message": "Not a usable subscription"}

    try:
        request = build_request(subscription, payload, ttl)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"ok": True, "status": response.status, "gone": False, "message": ""}
    except urllib.error.HTTPError as e:
        # 404 and 410 are the push service saying this subscription is dead --
        # the browser was uninstalled, or the user cleared site data. Anything
        # else may be temporary and the subscription is kept.
        return {"ok": False, "status": e.code, "gone": e.code in (404, 410),
                "message": f"Push service said {e.code}"}
    except Exception as e:
        return {"ok": False, "status": 0, "gone": False, "message": f"Could not send it: {e}"}


# --- who is subscribed ------------------------------------------------------

class SubscriptionStore:
    """Push subscriptions, one per phone, persisted 0600 beside the devices.

    Keyed by endpoint because that is what the browser gives back and what the
    push service dropping one refers to; the device id rides along so a phone
    that is already looking at the page can be skipped.
    """

    def __init__(self, path: Path = None):
        self.path = Path(path) if path else _config_dir() / "push-subscriptions.json"
        self._lock = threading.Lock()

    def _read(self) -> dict:
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}
        entries = raw.get("subscriptions")
        return entries if isinstance(entries, dict) else {}

    def _write(self, entries: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump({"version": 1, "subscriptions": entries}, handle)
        os.replace(tmp, self.path)

    def add(self, subscription: dict, device_id: str = "", name: str = "") -> bool:
        endpoint = str((subscription or {}).get("endpoint") or "")
        keys = (subscription or {}).get("keys") or {}
        if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
            return False
        with self._lock:
            entries = self._read()
            entries[endpoint] = {
                "endpoint": endpoint,
                "keys": {"p256dh": str(keys["p256dh"]), "auth": str(keys["auth"])},
                "device": device_id,
                "name": name,
                "created": time.time(),
            }
            self._write(entries)
        return True

    def remove(self, endpoint: str) -> bool:
        with self._lock:
            entries = self._read()
            if endpoint not in entries:
                return False
            del entries[endpoint]
            self._write(entries)
        return True

    def all(self) -> list:
        return list(self._read().values())

    def for_device(self, device_id: str) -> list:
        return [e for e in self._read().values() if e.get("device") == device_id]

    def __len__(self) -> int:
        return len(self._read())
