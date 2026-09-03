"""Action execution: one dispatcher shared by the HTTP server and the CLI.

Both entry points used to carry their own copy of this logic, which is how
`vt do` ended up supporting only audio and MPRIS while the web UI supported
windows, apps, and configured commands. Everything routes through
`execute_action` now, so the two can no longer drift.

Every function here is blocking (subprocess and D-Bus). The server runs them on
a worker thread; the CLI calls them directly.
"""

import json
import re
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from vt.commands import CommandsConfig
from vt.shell import SHELL_BUS_NAME, SHELL_OBJECT_PATH

try:
    import dbus
    HAS_DBUS = True
except ImportError:
    dbus = None
    HAS_DBUS = False

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

def _execute_system(target_spec: str, action_id: str, value) -> dict:
    """The system rows, which are several sources wearing one kind."""
    if target_spec == "audio":
        return execute_audio_action("@DEFAULT_AUDIO_SINK@", action_id, value)
    if target_spec == "mic":
        return execute_audio_action("@DEFAULT_AUDIO_SOURCE@", action_id, value)
    if target_spec == "wifi":
        from vt.sources.network import execute as execute_network_action
        return execute_network_action(target_spec, action_id)
    from vt.sources.system import execute as execute_system_action
    return execute_system_action(target_spec, action_id, value)


def _execute_disk(target_spec: str, action_id: str) -> dict:
    from vt.sources.disks import eject

    if action_id != "eject":
        return {"ok": False, "message": f"Unknown drive action: {action_id}"}
    return eject(target_spec)


def _execute_timer(target_spec: str, action_id: str) -> dict:
    from vt.schedule import scheduler

    if action_id != "cancel":
        return {"ok": False, "message": f"Unknown timer action: {action_id}"}
    return scheduler().cancel(target_spec)


def _execute_keypad(target_spec: str, action_id: str) -> dict:
    """A per-application key pad. The phone sends the name of a key, never a
    chord: the table decides which keys this application was said to answer."""
    from vt.sources.keypads import execute as execute_keypad_action

    return execute_keypad_action(target_spec, action_id)


def _execute_audio_device(target_spec: str, action_id: str) -> dict:
    """The output/input device rows: the spec is the direction, and the action
    carries the wpctl node to switch to."""
    from vt.sources.audio import execute_device_action

    return execute_device_action(target_spec, action_id)


def _execute_bluetooth(target_spec: str, action_id: str) -> dict:
    from vt.sources.bluetooth import execute as run

    return run(target_spec, action_id)


def _execute_workspace(target_spec: str, action_id: str) -> dict:
    from vt.sources.workspaces import execute as run

    return run(target_spec, action_id)


def _execute_streaming(target_spec: str, action_id: str) -> dict:
    from vt.sources.streaming import execute as run

    return run(target_spec, action_id)


# Kinds whose whole dispatch is "hand the spec and the action to one source".
# A table rather than another branch each, so adding a source does not make
# this function harder to read -- and the ones that need the value, or need to
# check the spec first, stay as branches below where that is visible.
_SIMPLE_KINDS = {
    "disk": _execute_disk,
    "timer": _execute_timer,
    "keys": _execute_keypad,
    "audio": _execute_audio_device,
    "bluetooth": _execute_bluetooth,
    "workspace": _execute_workspace,
    "streaming": _execute_streaming,
    "steam": lambda spec, action: execute_steam_action(spec, action),
    "window": lambda spec, action: execute_window_action(spec, action),
    "app": lambda spec, action: execute_app_action(spec, action),
    "launcher": lambda spec, action: execute_launcher_action(spec, action),
    "youtube": lambda spec, action: execute_youtube_action(spec, action),
}


def execute_action(target_id: str, action_id: str, value: Optional[float] = None) -> dict:
    """Execute an action on a target. Returns {"ok": bool, "message": str}."""
    if ":" not in target_id:
        return {"ok": False, "message": f"Invalid target ID: {target_id}"}

    kind, target_spec = target_id.split(":", 1)

    simple = _SIMPLE_KINDS.get(kind)
    if simple is not None:
        return simple(target_spec, action_id)

    if kind == "system":
        return _execute_system(target_spec, action_id, value)
    elif kind == "stream":
        # A per-application stream is a wpctl node like any other; only its id
        # is user-supplied, so it has to be a number and nothing else.
        if not target_spec.isdigit():
            return {"ok": False, "message": f"Invalid stream: {target_spec}"}
        return execute_audio_action(target_spec, action_id, value)
    elif kind == "mpris":
        return execute_mpris_action(target_spec, action_id, value)
    elif kind == "command":
        return execute_command_action(target_spec)
    return {"ok": False, "message": f"Unknown target kind: {kind}"}


def execute_audio_action(node: str, action_id: str, value: Optional[float] = None) -> dict:
    """Control a wpctl node -- the default sink or the default source."""
    try:
        if action_id == "volume":
            if value is None:
                return {"ok": False, "message": "Volume action requires a value"}
            vol = max(0.0, min(1.0, value))
            subprocess.run(
                ["wpctl", "set-volume", node, str(vol)],
                check=True,
                capture_output=True,
                timeout=2,
            )
            return {"ok": True, "message": f"Volume set to {int(vol * 100)}%"}
        elif action_id == "mute":
            subprocess.run(
                ["wpctl", "set-mute", node, "toggle"],
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
        if cmd.get("steps"):
            return _run_macro(cmd)
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


def _run_macro(cmd: dict) -> dict:
    """Run a command's steps in order, stopping at the first that fails.

    Stopping matters: the second half of "mute, then suspend" should not run
    when the first half did not, and a macro that reported success after doing
    half of itself would be worse than one that failed.
    """
    import time

    done = 0
    for index, step in enumerate(cmd["steps"], start=1):
        if "wait" in step:
            time.sleep(step["wait"])
            done += 1
            continue
        result = execute_action(step["target"], step["action"], step.get("value"))
        if not result.get("ok"):
            return {
                "ok": False,
                "message": (f"{cmd['label']}: step {index} "
                            f"({step['target']} {step['action']}) failed — "
                            f"{result.get('message', 'no reason given')}"),
            }
        done += 1
    return {"ok": True, "message": f"{cmd['label']}: {done} step(s) done"}


UNKNOWN_METHOD = "org.freedesktop.DBus.Error.UnknownMethod"

# Window-frame actions that map one-to-one onto an extension method.
_WINDOW_METHODS = {
    "minimize": ("Minimize", "Window minimized"),
    "unminimize": ("Unminimize", "Window restored"),
    "maximize": ("Maximize", "Window maximized"),
    "unmaximize": ("Unmaximize", "Window unmaximized"),
}

_MOVE_PREFIX = "move_ws_"


def _stale_extension_message(method: str) -> str:
    """An installed-but-older extension answers the bus and not the method.

    Reporting that as a generic D-Bus error sent the last person to hit it
    looking for a broken install rather than an out-of-date one.
    """
    return (
        f"The installed GNOME extension has no {method} method. Run "
        "`vt install-extension`, then reload the extension (log out and back "
        "in under Wayland)."
    )

# Tab targets carry their key chord in the id fragment: "1234#tab=2&keys=alt+3".
# Parsing it here keeps the action independent of the session store, which is
# rewritten every 15s and may have shifted since the snapshot was served.
_TAB_ID = re.compile(r"^(?P<wid>\d+)#tab=(?P<tab>\d+)&keys=(?P<keys>.+)$")


def _send_keys(interface, wid, chord: str) -> dict:
    """Type a chord into a window through the extension.

    Only the compositor may synthesize input under Wayland, so this is the one
    route that works there; xdotool is silently ignored by design.
    """
    try:
        interface.SendKeys(wid, chord)
        return {"ok": True, "message": ""}
    except dbus.DBusException as e:
        if dbus_error_name(e) == UNKNOWN_METHOD:
            return {"ok": False, "message": _stale_extension_message("SendKeys")}
        return {"ok": False, "message": shell_error(e)}


# Alt+1..9 and Ctrl+Page_Down are not reserved by Firefox, so a web app is free
# to claim them: on a Teams tab, Alt+2 moves Teams' own left rail and the browser
# never sees a tab switch. Ctrl+L is reserved -- no page can swallow it -- so
# parking focus in the address bar first takes the page out of the keyboard path,
# and Escape hands focus back to the content once the right tab is selected.
def _guarded(chord: str) -> str:
    """Wrap a tab chord so the focused page cannot intercept it."""
    return f"ctrl+l,{chord},escape"


def _execute_tab_action(interface, wid, tab, action_id: str) -> dict:
    """Act on one browser tab, addressed by the chord that selects it."""
    chord = tab.group("keys")
    number = int(tab.group("tab")) + 1

    if action_id == "focus":
        result = _send_keys(interface, wid, _guarded(chord))
        if result["ok"]:
            result["message"] = f"Switched to tab {number}"
        return result
    if action_id in ("close", "close_tab"):
        # Select the tab first, then close it. One SendKeys call so the two
        # cannot interleave with anything else the user is doing.
        result = _send_keys(interface, wid, f"{_guarded(chord)},ctrl+w")
        if result["ok"]:
            result["message"] = f"Closed tab {number}"
        return result
    if action_id == "close_window":
        interface.Close(wid)
        return {"ok": True, "message": "Window closed"}
    return {"ok": False, "message": f"Unknown tab action: {action_id}"}


def execute_window_action(window_id: str, action_id: str) -> dict:
    """Focus or close a window, or a single browser tab, via the GNOME extension.

    Browser tabs are not windows -- Mutter cannot see them at all -- so a tab
    target names its parent window plus the keystrokes that select that tab
    inside the browser. See vt/sources/firefox.py.

    A "cosmic:" prefix means sources/windows.py built this id from
    sources/cosmic_windows.py instead -- COSMIC's own Wayland protocols, not
    the GNOME extension. That module has no tab-level ids (see windows.py),
    so this split only ever needs to happen once, before the tab regex below.
    """
    from vt.sources.cosmic_windows import PREFIX as COSMIC_PREFIX
    if window_id.startswith(COSMIC_PREFIX):
        from vt.sources.cosmic_windows import execute as execute_cosmic_action
        return execute_cosmic_action(window_id[len(COSMIC_PREFIX):], action_id)

    if not HAS_DBUS:
        return {"ok": False, "message": no_dbus_message()}

    tab = _TAB_ID.match(window_id)

    try:
        wid = dbus.UInt32(int(tab.group("wid") if tab else window_id))
    except (TypeError, ValueError):
        return {"ok": False, "message": f"Invalid window id: {window_id}"}

    try:
        interface = _shell_interface()

        if tab:
            return _execute_tab_action(interface, wid, tab, action_id)

        if action_id == "focus":
            interface.Focus(wid)
            return {"ok": True, "message": "Window focused"}
        elif action_id in ("close", "close_window"):
            interface.Close(wid)
            return {"ok": True, "message": "Window closed"}
        elif action_id == "close_tab":
            result = _send_keys(interface, wid, "ctrl+w")
            if result["ok"]:
                result["message"] = "Tab closed"
            return result
        elif action_id in _WINDOW_METHODS:
            method, message = _WINDOW_METHODS[action_id]
            try:
                getattr(interface, method)(wid)
            except dbus.DBusException as e:
                if dbus_error_name(e) == UNKNOWN_METHOD:
                    return {"ok": False, "message": _stale_extension_message(method)}
                raise
            return {"ok": True, "message": message}
        elif action_id.startswith(_MOVE_PREFIX):
            try:
                index = int(action_id[len(_MOVE_PREFIX):])
            except ValueError:
                return {"ok": False, "message": f"Invalid workspace action: {action_id}"}
            try:
                interface.MoveToWorkspace(wid, dbus.UInt32(index))
            except dbus.DBusException as e:
                if dbus_error_name(e) == UNKNOWN_METHOD:
                    return {"ok": False, "message": _stale_extension_message("MoveToWorkspace")}
                raise
            return {"ok": True, "message": f"Moved to workspace {index + 1}"}
        return {"ok": False, "message": f"Unknown window action: {action_id}"}
    except dbus.DBusException as e:
        return {"ok": False, "message": shell_error(e)}
    except Exception as e:
        return {"ok": False, "message": f"Error: {e}"}


def execute_app_action(app_name: str, action_id: str) -> dict:
    """Quit or focus a running app, identified by its executable basename."""
    # app_name arrives straight off the wire, so confirm it names a real
    # installed app before it becomes an argv element. A list argv stops the
    # shell from seeing it, but not pkill: "app:-9" would otherwise reach
    # pkill as an option, leaving -U as the only criterion and signalling
    # every one of this user's processes. Matching the launcher, the check is
    # an index lookup rather than a character filter, so what gets through is
    # a name we discovered rather than one that merely looks harmless.
    from vt.sources.apps import get_binary_index

    if app_name not in get_binary_index():
        return {"ok": False, "message": f"No installed app named {app_name}"}

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


def execute_steam_action(appid: str, action_id: str) -> dict:
    """Start an installed Steam game, addressed by its app id."""
    if action_id != "launch":
        return {"ok": False, "message": f"Unknown Steam action: {action_id}"}

    from vt.sources.steam import launch_game
    return launch_game(appid)


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
