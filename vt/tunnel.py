"""Run the web remote behind a Cloudflare Tunnel.

cloudflared dials out from this machine and Cloudflare hands back a public
https URL, so nothing has to be forwarded on the router and no port is opened
to the internet. The tunnel is only transport: what actually keeps strangers
out is that vt refuses the startup token on anything arriving through it (see
vt/server.py), so the public URL on its own controls nothing.
"""

import asyncio
import re
import shutil

# Quick tunnels get a generated hostname. A named tunnel resolves to whatever
# hostname the user configured, which cloudflared never prints, so those need
# --public-url instead.
QUICK_URL_RE = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")

INSTALL_HINT = (
    "cloudflared is not installed.\n"
    "  Debian/Ubuntu:  sudo apt install cloudflared\n"
    "  or download:    https://github.com/cloudflare/cloudflared/releases\n"
    "  Arch:           sudo pacman -S cloudflared\n"
    "  Fedora:         sudo dnf install cloudflared"
)


def cloudflared_path():
    """Path to the cloudflared binary, or None."""
    return shutil.which("cloudflared")


def quick_tunnel_args(port: int, binary: str) -> list:
    return [
        binary,
        "tunnel",
        "--no-autoupdate",
        "--url",
        f"http://127.0.0.1:{port}",
    ]


def named_tunnel_args(name: str, binary: str) -> list:
    return [binary, "tunnel", "--no-autoupdate", "run", name]


async def start(port: int, on_url=None, name: str = "", quiet: bool = True):
    """Spawn cloudflared and return (process, reader_task).

    on_url is called with the public URL the moment cloudflared prints one.
    Only quick tunnels announce a URL; a named tunnel's hostname lives in the
    user's Cloudflare config and never appears in this output.
    """
    binary = cloudflared_path()
    if not binary:
        raise FileNotFoundError(INSTALL_HINT)

    args = named_tunnel_args(name, binary) if name else quick_tunnel_args(port, binary)
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async def pump():
        seen = False
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", "replace").rstrip()
            match = QUICK_URL_RE.search(line)
            if match and not seen:
                seen = True
                if on_url:
                    on_url(match.group(0))
            elif not quiet:
                print(f"  [cloudflared] {line}")
            elif "ERR" in line or "error" in line.lower():
                # Errors are surfaced even in quiet mode: a tunnel that failed
                # to come up otherwise looks exactly like one still starting.
                print(f"  [cloudflared] {line}")

    return proc, asyncio.create_task(pump())


def _remote_file():
    from vt.auth import config_dir
    return config_dir() / "remote.json"


def save_public_url(url: str):
    """Remember the tunnel URL so `vt pair` in another terminal can build a
    working pairing link without being told it again."""
    import json
    import os
    import time
    path = _remote_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"public_url": url, "saved_at": time.time()}, f)
        os.replace(tmp, path)
    except OSError:
        pass


def load_public_url() -> str:
    import json
    try:
        return str(json.loads(_remote_file().read_text()).get("public_url") or "")
    except (OSError, ValueError):
        return ""


def clear_public_url():
    """Forget the tunnel URL when the tunnel goes down.

    A quick tunnel's hostname dies with the cloudflared process, so leaving it
    on disk is worse than having nothing: `vt pair` would keep minting links
    for a hostname that no longer resolves, and the phone reports that as a DNS
    failure with nothing to say it was ever ours.
    """
    try:
        _remote_file().unlink()
    except OSError:
        pass


def public_url_is_live(url: str, timeout: float = 4.0) -> bool:
    """Whether anything still answers at this hostname.

    Cleanup on shutdown cannot be relied on -- a SIGKILL, a crash or a reboot
    all leave the file behind -- so the URL is checked before it is handed to a
    phone. Any HTTP reply counts, including a 502: that means the tunnel is up
    and only the local server is missing, which is a different problem with a
    different fix. Only a name that will not resolve, or a connection that will
    not open, counts as dead.
    """
    import urllib.error
    import urllib.request

    if not url:
        return False
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False
