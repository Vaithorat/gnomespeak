"""HTTPS on the local network, with a certificate this machine makes itself.

Off the LAN everything already rides the tunnel's TLS. On the LAN it does not:
the token travels in a header over plain HTTP, and anyone on the same Wi-Fi can
read it. That is the one place where the pitch -- "expose your desktop, safely"
-- was weaker than it sounded.

A self-signed certificate is the only kind a desktop can make for itself, and
it comes with the cost stated plainly: the phone shows a warning the first
time, and the fingerprint printed at startup is what the person is meant to
check before accepting it. That is a worse first minute than plain HTTP and a
much better hour after it, so it is opt-in (`vt serve --tls`) rather than the
default.

The certificate covers this machine's LAN address, its hostname and loopback,
lasts two years, and is regenerated when the address it was made for changes --
otherwise moving between networks would silently produce a name mismatch on
top of the warning that is already there.
"""

import datetime
import ipaddress
import os
import socket
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    HAS_CRYPTO = True
except ImportError:  # pragma: no cover - exercised on machines without it
    HAS_CRYPTO = False

VALID_DAYS = 730

MISSING = (
    "HTTPS on the LAN needs the cryptography package. Install it with "
    "`pip install gnomespeak[push]` (the same extra), or run without --tls."
)


def available() -> bool:
    return HAS_CRYPTO


def lan_ip() -> str:
    """This machine's address on the network it can reach, or ""."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # No packet is sent; connect() on a UDP socket only picks a route,
            # which is exactly the question being asked.
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return ""


def names_for(host: str = "") -> list:
    """The names and addresses the certificate should cover, in order."""
    names = []
    for candidate in (host, lan_ip(), socket.gethostname(), "localhost", "127.0.0.1"):
        if candidate and candidate not in names and candidate not in ("0.0.0.0", "::"):
            names.append(candidate)
    return names


def _san(names: list) -> list:
    entries = []
    for name in names:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            entries.append(x509.DNSName(name))
    return entries


def cert_paths(base: Path) -> tuple:
    return base / "tls-cert.pem", base / "tls-key.pem"


def fingerprint(cert_pem: bytes) -> str:
    """The SHA-256 fingerprint, grouped the way a phone shows it."""
    if not HAS_CRYPTO:
        return ""
    digest = x509.load_pem_x509_certificate(cert_pem).fingerprint(hashes.SHA256())
    return ":".join(f"{byte:02X}" for byte in digest)


def covers(cert_pem: bytes, names: list) -> bool:
    """Whether an existing certificate still names this machine."""
    if not HAS_CRYPTO:
        return False
    try:
        cert = x509.load_pem_x509_certificate(cert_pem)
        if cert.not_valid_after_utc <= datetime.datetime.now(datetime.timezone.utc):
            return False
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except Exception:
        return False
    present = {str(entry) for entry in san.get_values_for_type(x509.DNSName)}
    present |= {str(entry) for entry in san.get_values_for_type(x509.IPAddress)}
    return all(name in present for name in names)


def ensure(base: Path, host: str = "") -> dict:
    """The certificate for this machine, made once and reused.

    Returns {ok, cert, key, fingerprint, names, created} -- `created` says
    whether this call is the one that made it, which is what the banner uses to
    decide whether to shout about the fingerprint.
    """
    if not HAS_CRYPTO:
        return {"ok": False, "message": MISSING}

    cert_path, key_path = cert_paths(base)
    names = names_for(host)
    try:
        existing = cert_path.read_bytes()
        if key_path.exists() and covers(existing, names):
            return {"ok": True, "cert": cert_path, "key": key_path,
                    "fingerprint": fingerprint(existing), "names": names, "created": False}
    except OSError:
        pass

    private = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, names[0][:64] if names else "gnomespeak"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "GnomeSpeak"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private.public_key())
        .serial_number(x509.random_serial_number())
        # A minute of leeway for a phone whose clock is a little behind.
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(_san(names)), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private, hashes.SHA256())
    )

    base.mkdir(parents=True, exist_ok=True)
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    cert_path.write_bytes(cert_pem)
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key_pem)

    return {"ok": True, "cert": cert_path, "key": key_path,
            "fingerprint": fingerprint(cert_pem), "names": names, "created": True}


def context(base: Path, host: str = "") -> dict:
    """An ssl.SSLContext for the server, or a reason it cannot have one."""
    import ssl

    result = ensure(base, host)
    if not result.get("ok"):
        return result
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(result["cert"], result["key"])
    # TLS 1.2 is the floor: every phone browser in use speaks it, and anything
    # older is a downgrade nobody here needs.
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return dict(result, context=ctx)
