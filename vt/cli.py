"""Command-line interface."""

import argparse
import sys
import subprocess
from vt.actions import execute_action
from vt.state import get_snapshot


def cmd_status(args):
    """Print the current snapshot as a table."""
    snapshot = get_snapshot()
    if not snapshot.targets:
        print("No targets found.")
        return

    print(f"\nVoiceTalk — {len(snapshot.targets)} target(s)\n")
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
        print("  Create ~/.config/voicetalk/commands.toml -- see commands.toml.example.\n")
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

    # Check 5: GNOME extension. Catch bare Exception -- naming
    # dbus.DBusException here would itself raise NameError when the dbus import
    # above failed, taking down the whole doctor run.
    try:
        import dbus
        bus = dbus.SessionBus()
        bus.get_object(
            "org.gnome.Shell.Extensions.VoiceTalk",
            "/org/gnome/Shell/Extensions/VoiceTalk",
        )
        checks.append(("✓", "Extension", "D-Bus interface active"))
        ok_count += 1
    except Exception:
        checks.append(("ℹ", "Extension", "Not active (optional; run 'vt install-extension')"))
        warn_count += 1

    # Check 6: Port availability
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
    print("\nVoiceTalk Preflight Check\n")
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


def cmd_serve(args):
    """Start the HTTP server."""
    import socket
    from vt.server import run_server

    # Determine host
    host = args.host
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

    run_server(host, port, token, open_browser=args.open)


def cmd_install_extension(args):
    """Install the GNOME extension."""
    import shutil
    from pathlib import Path

    try:
        # Find the extension source
        ext_src = Path(__file__).parent.parent / "gnome-extension" / "voicetalk@local"
        if not ext_src.exists():
            print(f"✗ Extension source not found at {ext_src}")
            sys.exit(1)

        # Target directory
        ext_dir = Path.home() / ".local" / "share" / "gnome-shell" / "extensions"
        ext_dir.mkdir(parents=True, exist_ok=True)

        # Symlink or copy
        target = ext_dir / "voicetalk@local"
        if target.exists():
            print(f"  Extension already installed at {target}")
        else:
            # Symlink (so edits are live)
            try:
                target.symlink_to(ext_src)
                print(f"✓ Symlinked extension to {target}")
            except Exception:
                # Fallback to copy
                shutil.copytree(ext_src, target, dirs_exist_ok=True)
                print(f"✓ Copied extension to {target}")

        # Enable the extension
        try:
            subprocess.run(
                ["gnome-extensions", "enable", "voicetalk@local"],
                check=True,
                capture_output=True,
            )
            print("✓ Extension enabled")
        except subprocess.CalledProcessError:
            print("⚠ Failed to enable extension automatically.")
            print("  Run manually: gnome-extensions enable voicetalk@local")

        print()
        print("ℹ On Wayland, GNOME Shell will not reload.")
        print("  You must **log out and log back in** for the extension to load.")
        print()

    except Exception as e:
        print(f"✗ Installation failed: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        prog="vt",
        description="Control your Linux PC from your phone.",
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

    # install-extension
    subparsers.add_parser("install-extension", help="Install GNOME extension")

    args = parser.parse_args()

    # Dispatch
    handlers = {
        "status": cmd_status,
        "do": cmd_do,
        "commands": cmd_commands,
        "apps": cmd_apps,
        "doctor": cmd_doctor,
        "serve": cmd_serve,
        "install-extension": cmd_install_extension,
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
