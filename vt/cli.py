"""Command-line interface."""

import argparse
import shutil
import sys
import subprocess
from vt import package
from vt.actions import execute_action
from vt.state import get_snapshot


def cmd_status(args):
    """Print the current snapshot as a table."""
    snapshot = get_snapshot()
    if not snapshot.targets:
        print("No targets found.")
        return

    print(f"\nGnomeSpeak — {len(snapshot.targets)} target(s)\n")
    for target in snapshot.targets:
        icon = target.icon or "•"
        pos = ""
        if target.position is not None and target.length is not None:
            pos = f"  {int(target.position)}s / {int(target.length)}s"
        status = target.status.ljust(8) if target.status else ""
        subtitle = f"  [{target.subtitle}]" if target.subtitle else ""
        actions_str = ", ".join(a.id for a in target.actions)

        print(f"  {icon} {target.title.ljust(30)}{subtitle}")
        print(f"    kind={target.kind} status={status}{pos}")
        print(f"    id={target.id}")
        print(f"    actions: {actions_str}")
        if target.note:
            print(f"    note: {target.note}")
        print()


def cmd_do(args):
    """Invoke an action on a target."""
    if ":" not in args.target_id:
        print(f"Error: Invalid target ID format. Expected 'kind:id', got '{args.target_id}'")
        sys.exit(1)

    # Same dispatcher the web UI uses, so `vt do` reaches windows, apps, and
    # configured commands too -- it used to handle only audio and MPRIS.
    result = execute_action(args.target_id, args.action_id, args.value)
    if result["ok"]:
        print(f"✓ {result['message']}")
    else:
        print(f"✗ {result['message']}")
        sys.exit(1)


def cmd_commands(args):
    """List configured commands."""
    from vt.commands import CommandsConfig

    config = CommandsConfig()
    commands = config.get_commands()
    errors = config.get_errors()

    if not commands and not errors:
        print("\nNo commands configured.")
        print("  Create ~/.config/gnomespeak/commands.toml -- see commands.toml.example.\n")
        return

    if commands:
        print(f"\n{len(commands)} command(s):\n")
        for cmd in commands:
            confirm = "  [confirm]" if cmd.get("confirm") else ""
            print(f"  {cmd['id']:<16} {cmd['label']}{confirm}")
            print(f"  {'':<16} $ {' '.join(cmd['run'])}")
            print()

    if errors:
        print(f"{len(errors)} problem(s) in commands.toml:\n")
        for err in errors:
            print(f"  ! {err}")
        print()


def cmd_apps(args):
    """List installed applications, optionally filtered by a search query."""
    from vt.sources.apps import get_installed_targets

    query = " ".join(args.query or [])
    targets = get_installed_targets(query)

    if not targets:
        if query:
            print(f"\nNo installed app matches {query!r}.\n")
        else:
            print("\nNo installed apps found (no readable .desktop entries).\n")
        return

    heading = f"{len(targets)} installed app(s)"
    if query:
        heading += f" matching {query!r}"
    print(f"\n{heading}:\n")
    for target in targets:
        app_id = target.id.split(":", 1)[1]
        subtitle = f"  [{target.subtitle}]" if target.subtitle else ""
        print(f"  {app_id:<32} {target.title}{subtitle}")
    print("\n  Launch one with: vt do launcher:<id> launch\n")


def cmd_doctor(args):
    """Run preflight checks."""
    checks = []
    ok_count = 0
    warn_count = 0
    fail_count = 0

    # Check 1: Environment
    import os
    session_type = os.environ.get("XDG_SESSION_TYPE", "unknown").lower()
    if session_type == "wayland":
        checks.append(("✓", "Session", "Wayland"))
        ok_count += 1
    elif session_type == "x11":
        checks.append(("⚠", "Session", "X11 (untested)"))
        warn_count += 1
    else:
        checks.append(("⚠", "Session", session_type))
        warn_count += 1

    # Check 1b: AppArmor confinement. A vt started from a snap's built-in
    # terminal inherits that snap's label, and snap policy then blocks it from
    # reaching other snaps -- which shows up as media players silently missing.
    from vt.actions import confinement_label

    label = confinement_label()
    if not label:
        checks.append(("\u2713", "Confinement", "unconfined"))
        ok_count += 1
    else:
        checks.append(("\u26a0", "Confinement", f"{label}"))
        checks.append((" ", "", "other snaps (e.g. Firefox) may refuse D-Bus calls"))
        checks.append((" ", "", "fix: run vt from a normal terminal, not a snap's built-in one"))
        warn_count += 1

    # Check 2: D-Bus. Report the interpreter, since a venv built without
    # --system-site-packages is the usual reason this import fails.
    try:
        import dbus
        bus = dbus.SessionBus()
        checks.append(("✓", "D-Bus", "SessionBus connected"))
        ok_count += 1
    except ImportError:
        checks.append(("✗", "D-Bus", f"python-dbus not importable under {sys.executable}"))
        checks.append((" ", "", "fix: apt install python3-dbus, or rebuild the venv"))
        checks.append((" ", "", "     with: python3 -m venv --system-site-packages venv"))
        fail_count += 1
    except Exception as e:
        checks.append(("✗", "D-Bus", f"Error: {e}"))
        fail_count += 1

    # Check 3: wpctl
    try:
        result = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
            capture_output=True,
            timeout=2,
        )
        if result.returncode == 0:
            checks.append(("✓", "wpctl", "PipeWire available"))
            ok_count += 1
        else:
            checks.append(("⚠", "wpctl", "Command failed"))
            warn_count += 1
    except FileNotFoundError:
        checks.append(("⚠", "wpctl", "Not installed"))
        warn_count += 1
    except Exception as e:
        checks.append(("✗", "wpctl", str(e)))
        fail_count += 1

    # Check 4: MPRIS players. Listing the bus names is not enough -- under snap
    # confinement the names are visible but every property read comes back
    # AccessDenied, so the player is listed here and missing everywhere else.
    try:
        import dbus
        from vt.actions import ACCESS_DENIED, dbus_denied_message, dbus_error_name

        bus = dbus.SessionBus()
        names = [str(n) for n in bus.list_names() if str(n).startswith("org.mpris.MediaPlayer2.")]
        readable, denied = 0, False
        for name in names:
            try:
                obj = bus.get_object(name, "/org/mpris/MediaPlayer2", introspect=False)
                props = dbus.Interface(obj, "org.freedesktop.DBus.Properties")
                props.Get("org.mpris.MediaPlayer2.Player", "PlaybackStatus")
                readable += 1
            except dbus.DBusException as e:
                if dbus_error_name(e) == ACCESS_DENIED:
                    denied = True

        if denied:
            checks.append(("✗", "MPRIS", f"{len(names)} player(s) refusing access"))
            checks.append((" ", "", dbus_denied_message()))
            fail_count += 1
        elif readable:
            checks.append(("✓", "MPRIS", f"{readable} player(s) active"))
            ok_count += 1
        else:
            checks.append(("ℹ", "MPRIS", "No players active (start one to test)"))
            warn_count += 1
    except Exception:
        checks.append(("✗", "MPRIS", "D-Bus error"))
        fail_count += 1

    # Check 5: GNOME extension. Every name here comes from vt.shell, because
    # this check once hardcoded a bus name of its own -- and when the project
    # was renamed, this copy was the only one that changed. It then reported
    # "not active" on every machine, including the ones where the extension was
    # answering every call vt made.
    from vt import shell as shell_mod

    if not shell_mod.is_available():
        code, message = shell_mod.status()
        if code == "broken":
            # Naming the on-disk state is the difference between "you never
            # installed it" and "your install broke when the project was
            # renamed" -- which from the phone look identical.
            problems = shell_mod.install_problems()
            checks.append(("⚠", "Extension", "Not active — " + problems[0]))
            for extra in problems[1:]:
                checks.append((" ", "", extra))
            checks.append((" ", "", "fix: vt install-extension, then log out and back in"))
        elif code == "disabled":
            checks.append(("⚠", "Extension", message))
            checks.append((" ", "", "fix: vt install-extension, then log out and back in"))
        elif code == "error":
            checks.append(("⚠", "Extension", "Installed, but GNOME Shell could not load it"))
            checks.append((" ", "", f"details: gnome-extensions info {shell_mod.installed_uuid()}"))
        elif code == "no-shell":
            checks.append(("ℹ", "Extension", "No GNOME Shell on this machine"))
        else:
            # The ordinary case right after an install: nothing is wrong and
            # rerunning the installer changes nothing. A Shell extension only
            # loads at session start.
            checks.append(("ℹ", "Extension", "Installed but not loaded (log out and back in)"))
        checks.append((" ", "", "without it: no window, workspace, touchpad or"))
        checks.append((" ", "", "typing control (media and system control still work)"))
        warn_count += 1
    else:
        # Answering the bus is not the same as being current. A Shell extension
        # only reloads on log out, so an updated checkout can sit on disk for
        # days while the old build keeps serving -- and every action added since
        # then fails one at a time with nothing tying them together.
        # Introspection names the gap without invoking anything for its side
        # effects: calling Pointer() to prove Pointer() exists moves the mouse.
        missing = shell_mod.missing_methods()
        if not missing:
            checks.append(("✓", "Extension", "D-Bus interface active, all methods present"))
            ok_count += 1
        else:
            checks.append(("⚠", "Extension", f"Running an older build ({len(missing)} method(s) missing)"))
            for feature in shell_mod.missing_features(missing):
                checks.append((" ", "", f"unavailable: {feature}"))
            checks.append((" ", "", "fix: vt install-extension, then log out and back in"))
            warn_count += 1

    # Check 5b: the tools the phone-to-PC features need. All three are optional
    # and each fails in its own quiet way -- an empty clipboard box, a
    # notification list that never fills, an upload that has nowhere to land --
    # so they are worth a line each here rather than a discovery on the phone.
    from vt.sources.clipboard import backend as clipboard_backend, unavailable_message
    from vt.sources.notifications_mirror import mirror

    tool = clipboard_backend()
    if tool:
        checks.append(("✓", "Clipboard", f"{tool['name']} available"))
        ok_count += 1
    else:
        checks.append(("⚠", "Clipboard", "No clipboard tool"))
        checks.append((" ", "", unavailable_message()))
        warn_count += 1

    # Check 5c: the unit that makes this a service rather than a command you
    # have to remember. Not a failure when absent -- `make dev` is a supported
    # way to run -- but the difference between "running" and "will be running
    # after the next login" is worth stating.
    from vt import service as service_mod

    svc = service_mod.status()
    if not svc["available"]:
        pass  # No systemd user manager; nothing to report and nothing to fix.
    elif not svc["installed"]:
        checks.append(("ℹ", "Autostart", "Not installed — start it with `make dev` or `vt serve`"))
        checks.append((" ", "", "fix: vt install-service (starts with your session)"))
    elif svc["active"]:
        checks.append(("✓", "Autostart", "gnomespeak.service is running"))
        ok_count += 1
    else:
        checks.append(("⚠", "Autostart", svc["detail"] or "installed but not running"))
        warn_count += 1

    if mirror().available():
        checks.append(("✓", "Notifications", "dbus-monitor available for mirroring"))
        ok_count += 1
    else:
        checks.append(("ℹ", "Notifications", "dbus-monitor not installed"))
        checks.append((" ", "", "notification mirroring is unavailable"))
        checks.append((" ", "", "fix: sudo apt install dbus-bin"))
        warn_count += 1

    try:
        from vt.sources.transfer import transfer_dir

        directory = transfer_dir()
        probe = directory / ".vt-write-test"
        probe.write_text("")
        probe.unlink()
        checks.append(("✓", "File transfer", f"{directory} is writable"))
        ok_count += 1
    except Exception as e:
        checks.append(("⚠", "File transfer", f"Cannot write the transfer folder: {e}"))
        warn_count += 1

    # Check 5d: the small tools the newer targets shell out to. None of them is
    # worth a failure -- each backs one action, and each already says so when
    # tapped -- but "Eject did nothing" is a much worse way to learn that
    # udisks2 is missing than a line here before anyone picks up a phone.
    from vt.sources.ring import player_argv

    extras = [
        ("notify-send", bool(shutil.which("notify-send")), "banners on the PC"),
        ("a sound player", bool(player_argv()), "ringing this PC"),
        ("udisksctl", bool(shutil.which("udisksctl")), "ejecting a USB drive"),
    ]
    absent = [(tool, feature) for tool, present, feature in extras if not present]
    if not absent:
        checks.append(("✓", "Extras", "notify-send, sound player and udisksctl"))
        ok_count += 1
    else:
        checks.append(("ℹ", "Extras", f"{len(absent)} tool(s) missing"))
        for tool, feature in absent:
            checks.append((" ", "", f"no {tool} — {feature} is unavailable"))
        checks.append((" ", "", "fix: scripts/setup-system.sh, or install them yourself"))
        warn_count += 1

    # Check 5b: COSMIC window control -- only relevant as a fallback, so skip
    # it entirely when the GNOME extension above is already doing the job.
    if not any(name == "Extension" and status == "✓" for status, name, _ in checks):
        from vt.sources import cosmic_windows

        if not cosmic_windows.available():
            checks.append(("ℹ", "COSMIC windows", "pywayland not installed"))
            checks.append((" ", "", "fix: pip install 'gnomespeak[wayland]'"))
            warn_count += 1
        else:
            cosmic_wins = cosmic_windows.list_windows()
            if cosmic_wins:
                checks.append(("✓", "COSMIC windows", f"{len(cosmic_wins)} window(s) via native protocol"))
                ok_count += 1
            else:
                checks.append(("ℹ", "COSMIC windows", "Not this compositor, or no windows open"))
                warn_count += 1

    # Check 6: Browser autoplay. A tap on the phone that opens a paused tab
    # looks identical to one that does nothing, so this is worth stating even
    # though nothing is broken in vt itself.
    try:
        from vt.sources.browser_autoplay import state as autoplay_state

        autoplay = autoplay_state(force=True)
        if autoplay["status"] == "allowed":
            checks.append(("✓", "Autoplay", "Browser starts videos opened from the phone"))
            ok_count += 1
        elif autoplay["status"] == "blocked":
            checks.append(("⚠", "Autoplay", "Browser blocks autoplay"))
            checks.append((" ", "", "videos opened from the phone load paused"))
            checks.append((" ", "", "fix: vt allow-autoplay, then restart Firefox"))
            warn_count += 1
        else:
            checks.append(("ℹ", "Autoplay", autoplay["reason"]))
            warn_count += 1
    except Exception as e:
        checks.append(("ℹ", "Autoplay", f"Could not determine: {e}"))
        warn_count += 1

    # Check 7: Port availability
    try:
        sock = subprocess.run(
            ["ss", "-tln"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if ":8765" not in sock.stdout:
            checks.append(("✓", "Port 8765", "Available"))
            ok_count += 1
        else:
            checks.append(("⚠", "Port 8765", "In use"))
            warn_count += 1
    except Exception:
        checks.append(("ℹ", "Port 8765", "Could not check"))
        warn_count += 1

    # Check 7: Commands config
    from vt.commands import CommandsConfig
    config = CommandsConfig()
    if config.get_errors():
        checks.append(("⚠", "Config", f"{len(config.get_errors())} error(s)"))
        warn_count += 1
    else:
        checks.append(
            (
                "✓" if config.get_commands() else "ℹ",
                "Config",
                f"{len(config.get_commands())} command(s)",
            )
        )
        ok_count += 1

    # Print results
    print("\nGnomeSpeak Preflight Check\n")
    for status, name, desc in checks:
        print(f"  {status} {name:<12} {desc}")

    print()
    if fail_count > 0:
        print(f"  {fail_count} failure(s) — cannot proceed")
        sys.exit(1)
    elif warn_count > 0:
        print(f"  {warn_count} warning(s) — may not work fully")
    else:
        print("  All checks passed!")


def _print_qr(text: str):
    """Print a scannable QR for a URL, when the optional dep is present."""
    try:
        import qrcode
    except ImportError:
        print("  (install qrcode for a scannable code: pip install qrcode)")
        return
    try:
        qr = qrcode.QRCode(version=1, box_size=1, border=1)
        qr.add_data(text)
        qr.make(fit=True)
        print()
        qr.print_ascii(invert=True)
    except Exception as e:
        print(f"  Could not render QR code: {e}")


def _serves_https(host: str, port: int, timeout: float = 0.6) -> bool:
    """Whether a TLS handshake completes on that port.

    `vt pair` runs in a second terminal and cannot ask the server how it was
    started, so it asks the port instead: a link with the wrong scheme is a QR
    code that fails on the phone with nothing on screen to explain it.
    """
    import socket
    import ssl

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # The certificate is this machine's own; the question here is only whether
    # the port speaks TLS at all.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw):
                return True
    except Exception:
        return False


def _lan_url(port: int) -> str:
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        host = sock.getsockname()[0]
        sock.close()
    except Exception:
        host = "127.0.0.1"
    scheme = "https" if _serves_https(host, port) else "http"
    return f"{scheme}://{host}:{port}"


def cmd_pair(args):
    """Issue a one-time pairing code for a new device."""
    from vt.auth import CODE_TTL, PairingCodes, format_code
    from vt.tunnel import clear_public_url, load_public_url, public_url_is_live

    codes = PairingCodes(ttl=args.minutes * 60.0 if args.minutes else CODE_TTL)
    # A guest phone gets the visitor's terms: media only, and gone by itself
    # after a few hours. The person deciding that is the one at the keyboard,
    # so it is settled when the code is issued rather than when it is redeemed.
    scope = "guest" if getattr(args, "guest", False) else "full"
    device_ttl = float(getattr(args, "hours", 0) or 0) * 3600.0
    code = codes.issue(args.label or "cli", scope=scope, device_ttl=device_ttl)

    # The pairing link is what makes this one scan instead of ten typed
    # characters, so it has to point at the origin the phone will actually use:
    # a device paired against the LAN address has nothing stored for the tunnel
    # hostname, because localStorage is per-origin.
    saved = load_public_url()
    stale = ""
    if args.url:
        base = args.url.rstrip("/")
    elif saved and (args.no_check or public_url_is_live(saved)):
        base = saved
    else:
        # A quick tunnel's hostname is deleted the moment cloudflared stops, so
        # a leftover one produces a QR that fails on the phone as "DNS address
        # could not be found" -- with nothing on screen to connect that back to
        # a tunnel that is no longer running. Say so, and fall back to the LAN.
        stale = saved
        if saved:
            clear_public_url()
        base = _lan_url(args.port)

    link = f"{base}/?p={code}"
    minutes = int((args.minutes * 60.0 if args.minutes else CODE_TTL) // 60)

    print(f"\n  Pairing code: {format_code(code)}")
    print(f"  Valid for:    {minutes} min, one device")
    if scope == "guest":
        print("  Grants:       media only — no power, input, files or clipboard")
    if device_ttl:
        hours = device_ttl / 3600.0
        shown = f"{hours:.0f}" if hours == int(hours) else f"{hours:.1f}"
        print(f"  Access ends:  {shown} hours after pairing")
    print(f"  Link:         {link}")
    if stale:
        print(f"\n  Note: the saved tunnel URL ({stale})")
        print("        no longer answers -- its cloudflared has stopped, and the")
        print("        hostname is gone with it. Falling back to the LAN address.")
        print("        Start a new one with `vt serve --tunnel`, then run `vt pair`")
        print("        again to get a link for the new hostname.")
    elif not args.url and not base.startswith("https://"):
        print("\n  Note: no public URL known, so this link is LAN-only.")
        print("        For remote access run `vt serve --tunnel`, or pass")
        print("        `vt pair --url https://your-tunnel.example.com`.")
    print("\n  Open the link on the phone, or enter the code in the")
    print("  \"Pair this device\" screen the web UI shows.")
    _print_qr(link)
    print()


def cmd_devices(args):
    """List or revoke paired devices."""
    import time
    from vt.auth import DeviceStore

    store = DeviceStore()

    if args.revoke_all:
        count = store.revoke_all()
        print(f"\n  Revoked {count} device(s). Every phone must pair again.\n")
        return

    if args.revoke:
        if store.revoke(args.revoke):
            print(f"\n  Revoked {args.revoke}.\n")
        else:
            print(f"\n  No device with id {args.revoke}.\n")
            sys.exit(1)
        return

    devices = store.list_devices()
    if not devices:
        print("\n  No paired devices.")
        print("  Pair one with: vt pair\n")
        return

    print(f"\n  {len(devices)} paired device(s):\n")
    now = time.time()
    for device in devices:
        last = device["last_seen"]
        if not last:
            seen = "never"
        elif now - last < 60:
            seen = "just now"
        elif now - last < 3600:
            seen = f"{int((now - last) // 60)} min ago"
        elif now - last < 86400:
            seen = f"{int((now - last) // 3600)} h ago"
        else:
            seen = f"{int((now - last) // 86400)} d ago"
        where = f" from {device['last_ip']}" if device["last_ip"] else ""
        print(f"  {device['id']}  {device['name'][:24]:<24} last seen {seen}{where}")
    print("\n  Revoke one with: vt devices --revoke <id>\n")


def cmd_audit(args):
    """Show recent authenticated actions and rejected attempts."""
    from vt.auth import AuditLog

    log = AuditLog()
    entries = log.tail(args.count)
    if not entries:
        print(f"\n  No audit entries yet ({log.path}).\n")
        return

    print(f"\n  Last {len(entries)} entries from {log.path}:\n")
    for entry in entries:
        event = entry.get("event", "?")
        if args.rejects and not (event.endswith(".reject") or event.endswith(".throttled")):
            continue
        detail = " ".join(
            f"{k}={v}" for k, v in entry.items() if k not in ("ts", "event")
        )
        print(f"  {entry.get('ts', '')}  {event:<16} {detail}")
    print()


def cmd_serve(args):
    """Start the HTTP server."""
    import socket
    from vt.server import run_server

    # --remote binds loopback because cloudflared is the only thing that should
    # be able to reach the port directly; the tunnel is what carries the rest of
    # the world in, and it arrives over 127.0.0.1.
    remote_mode = args.remote or args.tunnel or bool(args.tunnel_name)

    # Determine host
    host = args.host
    if not host and remote_mode:
        host = "127.0.0.1"
    if not host:
        # Detect LAN IP by connecting to Google's DNS
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            host = s.getsockname()[0]
            s.close()
        except Exception:
            host = "127.0.0.1"

    port = args.port

    # "" disables auth; None lets the server mint a fresh token.
    token = "" if args.no_token else None

    run_server(
        host,
        port,
        token,
        open_browser=args.open,
        require_pairing=args.require_pairing,
        trust_proxy=args.trust_proxy or remote_mode,
        public_url=args.public_url or "",
        tunnel=args.tunnel or bool(args.tunnel_name),
        tunnel_name=args.tunnel_name or "",
        pair_on_start=args.pair,
        tls=getattr(args, "tls", False),
    )


def cmd_allow_autoplay(args):
    """Allow or re-block browser autoplay of videos opened from the phone."""
    from vt.sources.browser_autoplay import restart_firefox, set_autoplay, state

    if args.status:
        current = state(force=True)
        print(f"\n  Autoplay: {current['status']}")
        print(f"  {current['reason']}")
        if current["profile"]:
            print(f"  Profile:  {current['profile']}")
        if current["fix"]:
            print(f"  Fix:      {current['fix']}")
        print()
        return

    allow = not args.revert
    result = set_autoplay(allow=allow)
    if not result["ok"]:
        print(f"✗ {result['message']}")
        sys.exit(1)
    print(f"✓ {result['message']}")

    if allow:
        print("  This is the same setting as Firefox's")
        print("  Settings → Privacy & Security → Autoplay → Allow Audio and Video.")
    elif result.get("residual"):
        print(f"  Note: {result['residual']}")
        return

    if not result["needs_restart"]:
        print("  Firefox is not running; the change applies the next time it starts.")
        return

    if args.restart:
        outcome = restart_firefox()
        print(("✓ " if outcome["ok"] else "✗ ") + outcome["message"])
        if not outcome["ok"]:
            sys.exit(1)
    else:
        print("  Restart Firefox for it to take effect (or re-run with --restart).")


ENABLED_KEY = ["org.gnome.shell", "enabled-extensions"]


def _enabled_extensions():
    """The dconf list of enabled extension uuids, or None if unreadable."""
    from vt.shell import enabled_uuids

    return enabled_uuids()


def _write_enabled_extensions(uuids) -> bool:
    try:
        result = subprocess.run(
            ["gsettings", "set"] + ENABLED_KEY + [str(list(uuids))],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def disable_extension(uuid: str) -> bool:
    """Drop an extension from the enabled list, running shell or not.

    `gnome-extensions disable` fails for an extension the shell never scanned --
    which is exactly the case for a uuid whose directory has just been deleted,
    and the one where leaving it enabled matters least but reads worst.
    """
    subprocess.run(["gnome-extensions", "disable", uuid], capture_output=True)
    enabled = _enabled_extensions()
    if enabled is None or uuid not in enabled:
        return False
    return _write_enabled_extensions([u for u in enabled if u != uuid])


def enable_extension(uuid: str):
    """Enable an extension, working around a shell that has not scanned it yet.

    `gnome-extensions enable` asks the running shell, and the running shell only
    scans the extensions directory at session start -- so for a *newly copied*
    extension under Wayland it always answers "does not exist". Telling the user
    to run the same command by hand just hands them the same error. The enabled
    list is a dconf key, though, and writing it directly sticks: the extension
    comes up enabled at the next login, which is when it could have loaded
    anyway. Returns (ok, message).
    """
    result = subprocess.run(
        ["gnome-extensions", "enable", uuid], capture_output=True, text=True
    )
    if result.returncode == 0:
        return True, "Extension enabled"

    enabled = _enabled_extensions()
    if enabled is None:
        return False, (
            "Could not read the enabled-extensions setting. Enable it after "
            f"logging back in: gnome-extensions enable {uuid}"
        )
    if uuid in enabled:
        return True, "Extension already enabled; it loads at the next login"
    if _write_enabled_extensions(enabled + [uuid]):
        return True, "Extension enabled for the next session"
    return False, (
        "Could not enable the extension automatically. Enable it after logging "
        f"back in: gnome-extensions enable {uuid}"
    )


def _extension_already_set_up() -> bool:
    """Whether there is nothing for --if-needed to do, printing why.

    `make dev` runs the install on every start, so a fresh clone comes up with
    window and touchpad control working at the next login rather than after a
    command nobody knew to run. Healthy means both halves: the directory is
    there and unbroken, and the uuid is in the enabled list -- an extension that
    is installed but disabled behaves exactly like one that was never installed.
    """
    from vt.shell import installed_uuid, install_problems, is_available, is_enabled, load_state

    if not shutil.which("gnome-extensions"):
        print("ℹ No GNOME Shell here — skipping the extension")
        print("  Window, workspace, touchpad and typing control need it; everything else works")
        return True

    if _installed_copy_is_stale():
        # `pip install -U gnomespeak` replaces the source but cannot touch a
        # copy already sitting in the extensions directory, and a Shell
        # extension one version behind the server it answers is the exact state
        # `vt doctor` calls "running an older build". Reinstalling is two file
        # operations, so the upgrade path repairs itself rather than waiting
        # for someone to notice a feature missing from the phone.
        return False

    # An unreadable setting (no gsettings, no dconf) is not evidence of a
    # problem, and reinstalling on every run to chase it would help nobody --
    # `is_enabled` treats it as enabled for that reason, and accepts either the
    # local uuid or the one the store install carries.
    if not install_problems() and is_enabled():
        # "installed" alone is what made `make dev`'s later "not loaded" note
        # read as a contradiction: both were true, and neither said that the
        # gap between them closes at the next login rather than by rerunning
        # anything.
        if is_available():
            print("✓ GNOME extension installed and loaded")
        elif load_state() == "error":
            print("⚠ GNOME extension installed but it failed to load")
            print(f"  Details: gnome-extensions info {installed_uuid()}")
        else:
            print("✓ GNOME extension installed — log out and back in to load it")
        return True
    return False


def _installed_copy_is_stale() -> bool:
    """Whether the installed extension is a copy older than the one shipped here.

    A symlinked install is never stale -- it *is* the source. A copy is what a
    `pip install` gets, and nothing else updates it: pip replaces its own data
    directory and leaves the extensions directory alone.
    """
    from vt.shell import extensions_dir, installed_uuid

    target = extensions_dir() / installed_uuid()
    if target.is_symlink() or not target.is_dir():
        return False
    source = package.source_dir()
    if not (source / "metadata.json").is_file():
        return False
    return package.metadata_version(source) > package.metadata_version(target)


def _refresh_installed_copy(target, source):
    """Bring an installed copy up to the shipped version, or leave it alone."""
    if target.is_symlink():
        print(f"  Extension already installed at {target}")
        return
    installed = package.metadata_version(target)
    shipped = package.metadata_version(source)
    if shipped <= installed:
        print(f"  Extension already installed at {target}")
        return
    # Replaced rather than merged: a file dropped from a later version of the
    # extension would otherwise stay behind and keep being loaded.
    shutil.rmtree(target)
    shutil.copytree(source, target)
    print(f"✓ Updated the extension at {target} (version {installed} → {shipped})")


def cmd_install_extension(args):
    """Install the GNOME extension."""
    from vt.shell import EXTENSION_UUID, LEGACY_EXTENSION_UUIDS, extensions_dir

    if_needed = getattr(args, "if_needed", False)
    if if_needed and _extension_already_set_up():
        return

    try:
        # Find the extension source: the checkout when there is one, the copy
        # the wheel installed when there is not.
        ext_src = package.source_dir()
        if not ext_src.exists():
            # Not fatal under --if-needed: this is a setup step running
            # alongside others, and every feature the extension backs already
            # reports its own absence rather than failing the whole run.
            print(f"{'⚠' if if_needed else '✗'} Extension source not found at {ext_src}")
            if if_needed:
                return
            sys.exit(1)

        # Target directory
        ext_dir = extensions_dir()
        ext_dir.mkdir(parents=True, exist_ok=True)

        # A pre-rename install is a symlink named voicetalk@local pointing at a
        # directory that the rename deleted. GNOME Shell drops a dangling
        # extension without a word, so every window, workspace and tab action
        # stopped working with nothing on screen to say why -- and installing
        # under the new name leaves the dead one enabled beside it.
        for uuid in LEGACY_EXTENSION_UUIDS:
            # Two halves, cleaned separately: the directory can be gone while
            # the uuid is still in the enabled list, which is how a deleted
            # extension keeps showing up as enabled forever.
            if disable_extension(uuid):
                print(f"✓ Dropped {uuid} from the enabled extensions")
            legacy = ext_dir / uuid
            if not (legacy.is_symlink() or legacy.exists()):
                continue
            broken = legacy.is_symlink() and not legacy.exists()
            if legacy.is_symlink() or legacy.is_file():
                legacy.unlink()
            else:
                shutil.rmtree(legacy)
            print(f"✓ Removed the old {uuid} install"
                  + (" (a dangling symlink)" if broken else ""))

        # Symlink or copy
        target = ext_dir / EXTENSION_UUID
        # A symlink whose target is gone is not exists(), so check both: the
        # "already installed" branch used to swallow exactly the broken case.
        if target.is_symlink() and not target.exists():
            target.unlink()
            print("  Replacing a dangling extension symlink")
        if target.exists():
            _refresh_installed_copy(target, ext_src)
        elif package.is_checkout(ext_src):
            # A checkout is the one source worth linking to: it stays where it
            # is, and an edit to extension.js is then live at the next login.
            try:
                target.symlink_to(ext_src)
                print(f"✓ Symlinked extension to {target}")
            except Exception:
                shutil.copytree(ext_src, target, dirs_exist_ok=True)
                print(f"✓ Copied extension to {target}")
        else:
            # Anything else is a directory pip owns, and pip deletes it on the
            # next upgrade or uninstall. GNOME Shell drops an extension whose
            # symlink dangles in silence, so copy instead and take on the job
            # of keeping the copy current (see _refresh_installed_copy).
            shutil.copytree(ext_src, target, dirs_exist_ok=True)
            print(f"✓ Copied extension to {target}")

        ok, note = enable_extension(EXTENSION_UUID)
        print(("✓ " if ok else "⚠ ") + note)

        print()
        print("ℹ On Wayland, GNOME Shell will not reload.")
        print("  You must **log out and log back in** for the extension to load.")
        print()

    except Exception as e:
        print(f"✗ Installation failed: {e}")
        sys.exit(1)


def cmd_open(args):
    """Open a link on this PC, the same way the phone does."""
    from vt.sources.open_url import open_url

    result = open_url(args.url)
    print(("✓ " if result["ok"] else "✗ ") + result["message"])
    if not result["ok"]:
        sys.exit(1)


def cmd_wake(args):
    """Send a wake-on-LAN packet to another machine."""
    from vt.sources.wake import wake

    result = wake(args.mac, broadcast=args.broadcast, port=args.port)
    print(("✓ " if result["ok"] else "✗ ") + result["message"])
    if result["ok"]:
        # Nothing acknowledges a magic packet, and saying "woken" would be a
        # claim this cannot check.
        print("  Nothing acknowledges a wake packet; check the machine itself.")
    else:
        sys.exit(1)


def cmd_package_extension(args):
    """Build the zip to upload to extensions.gnome.org."""
    from pathlib import Path

    result = package.build(
        out_dir=Path(args.out) if args.out else None,
        uuid=args.uuid,
    )
    if not result["ok"]:
        print(f"✗ {result['message']}")
        for problem in result.get("problems", [])[1:]:
            print(f"  also: {problem}")
        sys.exit(1)

    print(f"✓ {result['message']}")
    print(f"  uuid: {result['uuid']}   version: {result['version']}")
    print()
    print("  Upload it at https://extensions.gnome.org/upload/ .")
    print("  Bump `version` in gnome-extension/*/metadata.json before each resubmission;")
    print("  the store rejects a version it has already seen.")


def cmd_install_service(args):
    """Install the systemd user unit that starts the server at login."""
    from vt import service

    result = service.install(
        port=args.port,
        tunnel_name=args.tunnel_name,
        host=args.host,
        start=not args.no_start,
    )
    if not result["ok"]:
        print(f"✗ {result['message']}")
        sys.exit(1)

    print(f"✓ {result['message']}")
    print(f"  Unit: {result['path']}")
    if result["started"]:
        print("✓ Running now, and at every login from here on")
    elif result["start_error"]:
        print(f"⚠ Enabled, but it would not start now: {result['start_error']}")
    else:
        print("  Enabled; it starts with your next desktop session")

    if not result["session_target"]:
        # Installed cleanly and will never run: worth saying now rather than
        # after a reboot that quietly changed nothing.
        print(f"⚠ This desktop does not reach {service.SESSION_TARGET}, which the unit")
        print("  hangs off. Start it by hand with: systemctl --user start gnomespeak")

    print()
    print("  A service prints its banner where nobody reads it, so the startup")
    print("  token is not a way in: this unit requires pairing. Get a code with")
    print("  `vt pair`, then open the link on the phone.")
    print("  Logs: journalctl --user -u gnomespeak -f")
    print()


def cmd_uninstall_service(args):
    """Remove the systemd user unit."""
    from vt import service

    result = service.uninstall()
    print(("✓ " if result["ok"] else "✗ ") + result["message"])
    if not result["ok"]:
        sys.exit(1)


def _version_line() -> str:
    """`vt --version`: this build, and the extension source beside it."""
    from vt import __version__

    line = f"vt {__version__}"
    source = package.source_dir()
    shipped = package.metadata_version(source)
    if shipped:
        line += f" (GNOME extension version {shipped})"
    return line


def main():
    parser = argparse.ArgumentParser(
        prog="vt",
        description="Control your Linux PC from your phone.",
    )
    # The GNOME extension only reloads at login, so "which version is this?"
    # is a question with two answers on one machine. Both are printed here,
    # because a bug report with only the first cannot be acted on.
    parser.add_argument(
        "--version", action="version", version=_version_line(),
        help="Print the version of vt and of the extension it would install",
    )
    subparsers = parser.add_subparsers(dest="command", help="Subcommands")

    # status
    subparsers.add_parser("status", help="Show current state")

    # do
    do_parser = subparsers.add_parser("do", help="Invoke an action")
    do_parser.add_argument("target_id", help="Target ID")
    do_parser.add_argument("action_id", help="Action ID")
    do_parser.add_argument("value", type=float, nargs="?", help="Optional value (for sliders)")

    # commands
    subparsers.add_parser("commands", help="List configured commands")

    # apps
    apps_parser = subparsers.add_parser("apps", help="List installed apps you can launch")
    apps_parser.add_argument("query", nargs="*", help="Filter by name, description, or id")

    # doctor
    subparsers.add_parser("doctor", help="Run preflight checks")

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start HTTP server")
    serve_parser.add_argument("--host", help="Bind address (default: detected LAN IP)")
    serve_parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    serve_parser.add_argument("--no-token", action="store_true", help="Disable token auth")
    serve_parser.add_argument("--open", action="store_true", help="Open in browser")
    serve_parser.add_argument(
        "--tls", action="store_true",
        help=("Serve HTTPS on the LAN with this PC's own certificate. The phone warns "
              "once; the fingerprint to check is printed at startup."),
    )
    serve_parser.add_argument(
        "--tunnel", action="store_true",
        help="Run a Cloudflare quick tunnel and print a pairing QR for the public URL",
    )
    serve_parser.add_argument(
        "--tunnel-name", metavar="NAME",
        help="Run a named Cloudflare tunnel instead of a quick one",
    )
    serve_parser.add_argument(
        "--remote", action="store_true",
        help="Bind loopback and trust proxy headers (use with your own tunnel)",
    )
    serve_parser.add_argument(
        "--public-url", metavar="URL",
        help="Public https URL this server is reachable at, for pairing links",
    )
    serve_parser.add_argument(
        "--trust-proxy", action="store_true",
        help="Read CF-Connecting-IP / X-Forwarded-For from a loopback proxy",
    )
    serve_parser.add_argument(
        "--require-pairing", action="store_true",
        help="Refuse the startup token everywhere; every browser must pair",
    )
    serve_parser.add_argument(
        "--pair", action="store_true", help="Print a pairing code and QR at startup"
    )

    # pair
    pair_parser = subparsers.add_parser("pair", help="Issue a one-time device pairing code")
    pair_parser.add_argument("--url", help="Public base URL the phone will open")
    pair_parser.add_argument("--port", type=int, default=8765, help="Port for the LAN fallback URL")
    pair_parser.add_argument("--minutes", type=int, default=10, help="Code lifetime (default: 10)")
    pair_parser.add_argument("--label", help="Note stored with the code")
    pair_parser.add_argument(
        "--guest", action="store_true",
        help="Media only: no power, input, files, clipboard or pairing",
    )
    pair_parser.add_argument(
        "--hours", type=float, default=0,
        help="Access ends this many hours after pairing (default: until revoked)",
    )
    pair_parser.add_argument(
        "--no-check", action="store_true",
        help="Skip the reachability check on the saved tunnel URL",
    )

    # devices
    devices_parser = subparsers.add_parser("devices", help="List or revoke paired devices")
    devices_parser.add_argument("--revoke", metavar="ID", help="Revoke one device by id")
    devices_parser.add_argument(
        "--revoke-all", action="store_true", help="Revoke every paired device"
    )

    # audit
    audit_parser = subparsers.add_parser("audit", help="Show the recent security log")
    audit_parser.add_argument("-n", "--count", type=int, default=40, help="Entries to show")
    audit_parser.add_argument(
        "--rejects", action="store_true", help="Only rejected or throttled attempts"
    )

    # allow-autoplay
    autoplay_parser = subparsers.add_parser(
        "allow-autoplay",
        help="Let the browser start videos opened from the phone",
    )
    autoplay_parser.add_argument(
        "--status", action="store_true", help="Report the current setting and exit"
    )
    autoplay_parser.add_argument(
        "--revert", action="store_true", help="Remove vt's override again"
    )
    autoplay_parser.add_argument(
        "--restart", action="store_true", help="Restart Firefox so it takes effect now"
    )

    # install-extension
    ext_parser = subparsers.add_parser("install-extension", help="Install GNOME extension")
    ext_parser.add_argument(
        "--if-needed",
        action="store_true",
        help="Do nothing when the install is already healthy (used by `make dev`)",
    )

    open_parser = subparsers.add_parser("open", help="Open a link in this PC's browser")
    open_parser.add_argument("url", help="An http:// or https:// link")

    wake_parser = subparsers.add_parser("wake", help="Wake another machine (wake-on-LAN)")
    wake_parser.add_argument("mac", help="The other machine's MAC address")
    wake_parser.add_argument(
        "--broadcast", default="255.255.255.255", help="Broadcast address to send to",
    )
    wake_parser.add_argument("--port", type=int, default=9, help="UDP port (default: 9)")

    # package-extension
    from vt import shell

    pkg_parser = subparsers.add_parser(
        "package-extension",
        help="Build the extensions.gnome.org zip from the extension in this checkout",
    )
    pkg_parser.add_argument(
        "--uuid", default=shell.STORE_EXTENSION_UUID,
        help=f"uuid to publish under (default: {shell.STORE_EXTENSION_UUID})",
    )
    pkg_parser.add_argument("--out", default="", help="Directory to write the zip into (default: .)")

    # install-service / uninstall-service
    svc_parser = subparsers.add_parser(
        "install-service", help="Start the server with your desktop session (systemd user unit)"
    )
    svc_parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    svc_parser.add_argument("--host", default="", help="Bind address (default: the server's own choice)")
    svc_parser.add_argument(
        "--tunnel-name", default="",
        help="Run a named Cloudflare tunnel, so the URL survives a restart",
    )
    svc_parser.add_argument(
        "--no-start", action="store_true", help="Install and enable it, but do not start it now"
    )
    subparsers.add_parser("uninstall-service", help="Remove the systemd user unit")

    args = parser.parse_args()

    # Dispatch
    handlers = {
        "status": cmd_status,
        "do": cmd_do,
        "commands": cmd_commands,
        "apps": cmd_apps,
        "doctor": cmd_doctor,
        "serve": cmd_serve,
        "pair": cmd_pair,
        "devices": cmd_devices,
        "audit": cmd_audit,
        "allow-autoplay": cmd_allow_autoplay,
        "open": cmd_open,
        "wake": cmd_wake,
        "install-extension": cmd_install_extension,
        "package-extension": cmd_package_extension,
        "install-service": cmd_install_service,
        "uninstall-service": cmd_uninstall_service,
    }

    if not args.command:
        parser.print_help()
        sys.exit(0)

    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
