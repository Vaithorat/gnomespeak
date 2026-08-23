"""Action execution: one dispatcher shared by the HTTP server and the CLI.

Both entry points used to carry their own copy of this logic, which is how
`vt do` ended up supporting only audio and MPRIS while the web UI supported
windows, apps, and configured commands. Everything routes through
`execute_action` now, so the two can no longer drift.

Every function here is blocking (subprocess and D-Bus). The server runs them on
a worker thread; the CLI calls them directly.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from vt.commands import CommandsConfig

try:
    import dbus
    HAS_DBUS = True
except ImportError:
    dbus = None
    HAS_DBUS = False


SHELL_BUS_NAME = "org.gnome.Shell.Extensions.VoiceTalk"
SHELL_OBJECT_PATH = "/org/gnome/Shell/Extensions/VoiceTalk"

# D-Bus names that mean "nobody is offering this service", as opposed to a
# service that answered with an error of its own.
_NO_SERVICE = {
    "org.freedesktop.DBus.Error.ServiceUnknown",
    "org.freedesktop.DBus.Error.NameHasNoOwner",
}

ACCESS_DENIED = "org.freedesktop.DBus.Error.AccessDenied"


def dbus_error_name(e) -> str:
    """The D-Bus error name, or "" for anything that is not a DBusException."""
    try:
        return e.get_dbus_name() or ""
    except Exception:
        return ""


def confinement_label() -> str:
    """This process's AppArmor label, or "" when it is unconfined.

    A snap's integrated terminal runs its children under the snap's own label:
    a `vt serve` started from VS Code's terminal is `snap.code.code`. snapd's
    D-Bus policy then refuses to let it talk to *other* snaps, so every property
    read against snap-packaged Firefox comes back AccessDenied -- which looks
    exactly like "no media players are running".
    """
    try:
        raw = Path("/proc/self/attr/current").read_text(errors="ignore")
    except Exception:
        return ""
    label = raw.strip().strip("\x00").split(" ")[0]
    return "" if label in ("", "unconfined") else label


def dbus_denied_message() -> str:
    """Explain an AccessDenied, naming the confinement when there is one."""
    label = confinement_label()
    if label.startswith("snap."):
        return (
            "D-Bus access denied: vt is confined as "
            f"{label}, and snap policy blocks it from reaching other snaps "
            "(snap-packaged Firefox, for one). Start it from a normal terminal "
            "-- GNOME Terminal, not a snap's built-in terminal such as the one "
            "in the VS Code snap."
        )
    if label:
        return f"D-Bus access denied: vt is confined as {label} by AppArmor."
    return "D-Bus access denied by the session bus policy."


def no_dbus_message() -> str:
    """dbus-python missing is nearly always a wrong-interpreter problem."""
    return (
        "python-dbus is not importable under this interpreter "
        f"({sys.executable}). Media players and window control are unavailable. "
        "Install it (apt install python3-dbus), or recreate your venv with "
        "--system-site-packages so it can see the distro package."
    )


def shell_error(e) -> str:
    """Explain a D-Bus failure against the GNOME extension.

    Only an unowned bus name means the extension is missing. Anything else --
    a JS exception inside the extension, most often -- is a live extension
    reporting a real error, and saying "not available" sends the user off to
    reinstall something that is already installed.
    """
    try:
        name = e.get_dbus_name()
    except Exception:
        name = None
    if name in _NO_SERVICE:
        return "GNOME extension not available"
    detail = str(e).strip().splitlines()[-1] if str(e).strip() else name or "unknown error"
    return f"GNOME extension error: {detail}"


def match_window(windows: list[dict], app_name: str) -> Optional[dict]:
    """Find the window belonging to an app, given its executable basename.

    wm_class is the app-identity field; window titles hold document names and
    change as the user works, so "firefox" never matches "GitHub - Mozilla
    Firefox" by substring. Classes come in several shapes for one binary --
    "firefox", "Navigator", "org.gnome.Nautilus" -- so compare case-folded and
    accept a reverse-DNS tail. Title matching stays as a last resort for apps
    that report no class at all.
    """
    want = app_name.casefold()

    for w in windows:
        cls = str(w.get("wm_class") or "").casefold()
        if not cls:
            continue
        if cls == want or cls.rsplit(".", 1)[-1] == want:
            return w

    for w in windows:
        cls = str(w.get("wm_class") or "").casefold()
        if cls and (want in cls or cls in want):
            return w

    for w in windows:
        if want in str(w.get("title") or "").casefold():
            return w

    return None


def _shell_interface():
    """Return the GNOME extension's D-Bus interface."""
    bus = dbus.SessionBus()
    # introspect=False: we name the interface explicitly, so the Introspect
    # round trip buys nothing -- and when it is refused, dbus-python logs the
    # failure itself, once per call.
    obj = bus.get_object(SHELL_BUS_NAME, SHELL_OBJECT_PATH, introspect=False)
    return dbus.Interface(obj, SHELL_BUS_NAME)


# --- dispatch ---------------------------------------------------------------

def execute_action(target_id: str, action_id: str, value: Optional[float] = None) -> dict:
    """Execute an action on a target. Returns {"ok": bool, "message": str}."""
    if ":" not in target_id:
        return {"ok": False, "message": f"Invalid target ID: {target_id}"}

    kind, target_spec = target_id.split(":", 1)

    if kind == "system" and target_spec == "audio":
        return execute_audio_action(action_id, value)
    elif kind == "mpris":
        return execute_mpris_action(target_spec, action_id, value)
    elif kind == "command":
        return execute_command_action(target_spec)
    elif kind == "window":
        return execute_window_action(target_spec, action_id)
    elif kind == "app":
        return execute_app_action(target_spec, action_id)
    elif kind == "launcher":
        return execute_launcher_action(target_spec, action_id)
    elif kind == "youtube":
        return execute_youtube_action(target_spec, action_id)
    return {"ok": False, "message": f"Unknown target kind: {kind}"}


def execute_audio_action(action_id: str, value: Optional[float] = None) -> dict:
    """Control the default sink through wpctl."""
    try:
        if action_id == "volume":
            if value is None:
                return {"ok": False, "message": "Volume action requires a value"}
            vol = max(0.0, min(1.0, value))
            subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", str(vol)],
                check=True,
                capture_output=True,
                timeout=2,
            )
            return {"ok": True, "message": f"Volume set to {int(vol * 100)}%"}
        elif action_id == "mute":
            subprocess.run(
                ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"],
                check=True,
                capture_output=True,
                timeout=2,
            )
            return {"ok": True, "message": "Mute toggled"}
        return {"ok": False, "message": f"Unknown audio action: {action_id}"}
    except FileNotFoundError:
        return {"ok": False, "message": "wpctl not found (PipeWire is required)"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Command timed out"}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "message": f"wpctl error: {e}"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def execute_mpris_action(player_name: str, action_id: str, value: Optional[float] = None) -> dict:
    """Control an MPRIS player."""
    if not HAS_DBUS:
        return {"ok": False, "message": no_dbus_message()}

    try:
        bus = dbus.SessionBus()
        # The target id already carries the full bus name; do not re-prefix it.
        full_name = (
            player_name
            if player_name.startswith("org.mpris.MediaPlayer2.")
            else f"org.mpris.MediaPlayer2.{player_name}"
        )
        # introspect=False for the same reason as the shell interface: the
        # interface is known, and a snap-confined player refuses Introspect.
        obj = bus.get_object(full_name, "/org/mpris/MediaPlayer2", introspect=False)
        player = dbus.Interface(obj, "org.mpris.MediaPlayer2.Player")

        if action_id == "play_pause":
            player.PlayPause()
            return {"ok": True, "message": "Toggled play/pause"}
        elif action_id == "next":
            player.Next()
            return {"ok": True, "message": "Skipped to next"}
        elif action_id == "prev":
            player.Previous()
            return {"ok": True, "message": "Skipped to previous"}
        elif action_id == "seek_back":
            # Seek takes an int64 of microseconds. Without introspection
            # dbus-python cannot learn that signature, and would guess int32
            # from a bare Python int -- which the player rejects.
            player.Seek(dbus.Int64(-10_000_000))
            return {"ok": True, "message": "Seeked back 10s"}
        elif action_id == "seek_fwd":
            player.Seek(dbus.Int64(10_000_000))
            return {"ok": True, "message": "Seeked forward 10s"}
        elif action_id == "stop":
            player.Stop()
            return {"ok": True, "message": "Stopped playback"}
        elif action_id == "raise":
            dbus.Interface(obj, "org.mpris.MediaPlayer2").Raise()
            return {"ok": True, "message": "Raised player window"}
        return {"ok": False, "message": f"Unknown MPRIS action: {action_id}"}

    except dbus.DBusException as e:
        if dbus_error_name(e) == ACCESS_DENIED:
            return {"ok": False, "message": dbus_denied_message()}
        return {"ok": False, "message": f"D-Bus error: {e}"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def execute_command_action(cmd_id: str) -> dict:
    """Run a command from commands.toml. `run` is always argv, never a shell string."""
    config = CommandsConfig()
    for cmd in config.get_commands():
        if cmd["id"] != cmd_id:
            continue
        try:
            subprocess.run(cmd["run"], check=True, capture_output=True, timeout=10)
            return {"ok": True, "message": f"Executed: {cmd['label']}"}
        except FileNotFoundError:
            return {"ok": False, "message": f"Not found: {cmd['run'][0]}"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "Command timed out"}
        except subprocess.CalledProcessError as e:
            return {"ok": False, "message": f"Command failed: {e}"}
        except Exception as e:
            return {"ok": False, "message": f"Error: {e}"}
    return {"ok": False, "message": f"Command not found: {cmd_id}"}


def execute_window_action(window_id: str, action_id: str) -> dict:
    """Focus or close a window through the GNOME extension."""
    if not HAS_DBUS:
        return {"ok": False, "message": no_dbus_message()}

    try:
        wid = dbus.UInt32(int(window_id))
    except (TypeError, ValueError):
        return {"ok": False, "message": f"Invalid window id: {window_id}"}

    try:
        interface = _shell_interface()
        if action_id == "focus":
            interface.Focus(wid)
            return {"ok": True, "message": "Window focused"}
        elif action_id == "close":
            interface.Close(wid)
            return {"ok": True, "message": "Window closed"}
        return {"ok": False, "message": f"Unknown window action: {action_id}"}
    except dbus.DBusException as e:
        return {"ok": False, "message": shell_error(e)}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def execute_app_action(app_name: str, action_id: str) -> dict:
    """Quit or focus a running app, identified by its executable basename."""
    if action_id == "quit":
        # Match the executable name exactly (-x) and only among this user's own
        # processes (-U). "pkill -f firefox" matched the whole command line, so
        # quitting one app could take down anything that merely mentioned its
        # name in an argument.
        try:
            result = subprocess.run(
                ["pkill", "-x", "-U", str(os.getuid()), app_name],
                capture_output=True,
                timeout=2,
            )
            if result.returncode == 1:
                return {"ok": False, "message": f"No running process named {app_name}"}
            if result.returncode != 0:
                return {"ok": False, "message": f"pkill failed for {app_name}"}
            return {"ok": True, "message": f"Quit {app_name}"}
        except FileNotFoundError:
            return {"ok": False, "message": "pkill not found (install procps)"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "Command timed out"}
        except Exception as e:
            return {"ok": False, "message": f"Error: {e}"}

    # Everything below needs the GNOME extension, and so needs D-Bus.
    if not HAS_DBUS:
        return {"ok": False, "message": no_dbus_message()}

    if action_id == "focus":
        # app_name is an executable basename ("firefox", "nautilus"), so match it
        # against wm_class rather than the window title -- titles carry document
        # names, not app identity.
        try:
            interface = _shell_interface()
            windows = json.loads(interface.List())
        except dbus.DBusException as e:
            return {"ok": False, "message": shell_error(e)}
        except Exception as e:
            return {"ok": False, "message": f"Error: {e}"}

        match = match_window(windows, app_name)
        if match is None:
            return {"ok": False, "message": f"Window for {app_name} not found"}
        try:
            interface.Focus(dbus.UInt32(match["id"]))
            return {"ok": True, "message": f"Focused {app_name}"}
        except dbus.DBusException as e:
            return {"ok": False, "message": shell_error(e)}
        except Exception as e:
            return {"ok": False, "message": f"Error: {e}"}

    return {"ok": False, "message": f"Unknown app action: {action_id}"}


def execute_launcher_action(app_id: str, action_id: str) -> dict:
    """Start an installed app, addressed by its .desktop id."""
    if action_id != "launch":
        return {"ok": False, "message": f"Unknown launcher action: {action_id}"}

    # Imported here rather than at module scope: sources import nothing from
    # this module's neighbours, and keeping it that way leaves the import graph
    # a tree.
    from vt.sources.apps import get_installed_index

    entry = get_installed_index().get(app_id)
    if entry is None:
        return {"ok": False, "message": f"No installed app with id {app_id}"}
    return launch_entry(entry)


def launch_entry(entry: dict) -> dict:
    """Spawn a .desktop entry, detached from the server.

    `gio launch` is preferred over the parsed argv because it applies the
    desktop file's own semantics -- field codes, Terminal=true, DBusActivatable,
    a scope of its own -- instead of our approximation of them. The argv is the
    fallback for systems without glib's CLI. Stderr is captured so we can report
    why gio or the app itself failed to start.
    """
    use_gio = shutil.which("gio") is not None
    argv = ["gio", "launch", entry["path"]] if use_gio else entry.get("argv") or []
    if not argv:
        return {"ok": False, "message": f"No runnable command for {entry['name']}"}

    try:
        if use_gio:
            # gio handles the fork; we just wait for it to report success/failure.
            # Capture its stderr to show if it failed.
            try:
                result = subprocess.run(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=5,
                    cwd=str(Path.home()),
                )
                if result.returncode != 0:
                    stderr = result.stderr.decode(errors="ignore").strip()
                    msg = stderr.split('\n')[-1] if stderr else "gio launch failed"
                    return {"ok": False, "message": f"{entry['name']}: {msg}"}
                return {"ok": True, "message": f"Launched {entry['name']}"}
            except subprocess.TimeoutExpired:
                return {"ok": False, "message": f"{entry['name']}: gio timed out"}
        else:
            # Raw argv: spawn the app directly in its own session.
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
                cwd=str(Path.home()),
            )
            try:
                code = proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                return {"ok": True, "message": f"Launched {entry['name']}"}

            if code != 0:
                stderr = proc.stderr.read().decode(errors="ignore").strip() if proc.stderr else ""
                msg = stderr.split('\n')[-1] if stderr else f"exit {code}"
                return {"ok": False, "message": f"{entry['name']}: {msg}"}
            return {"ok": True, "message": f"Launched {entry['name']}"}

    except FileNotFoundError:
        return {"ok": False, "message": f"Not found: {argv[0]}"}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def execute_youtube_action(target_spec: str, action_id: str) -> dict:
    """Handle YouTube actions: play video, fix autoplay, or control playback."""
    if action_id == "play":
        # target_spec is the video URL
        from vt.sources.youtube import play_video
        return play_video(target_spec)
    elif action_id == "fix_autoplay":
        from vt.sources.youtube import fix_autoplay
        return fix_autoplay()
    elif target_spec == "player":
        return execute_youtube_player_action(action_id)
    return {"ok": False, "message": f"Unknown YouTube action: {action_id}"}


def execute_youtube_player_action(action_id: str) -> dict:
    """Control a YouTube window with keystrokes. X11 only -- see youtube_player."""
    from vt.sources.youtube_player import close_youtube_window, send_keys

    if action_id == "close":
        return close_youtube_window()
    return send_keys(action_id)
