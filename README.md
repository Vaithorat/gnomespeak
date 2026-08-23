# VoiceTalk v3 — Linux CLI + Web Remote

Control your Linux PC from your phone via a simple web interface. See what's playing, what's open, what apps are running — and control it all with a dropdown of concrete actions. No app installs, no voice, no AI guessing. Just you, your PC state, and pre-configured commands.

## Features

- **Real-time state display** — See MPRIS players, open windows, running apps, and system audio.
- **Launch installed apps** — Search everything with a `.desktop` entry and start it from the phone, whether or not it is already running.
- **YouTube search & play** — Search YouTube videos, see results with title, channel and duration, and tap to play in your browser.
- **YouTube playback control** — When a YouTube video plays in your browser, control it from the phone: play/pause, seek, volume, fullscreen, close (requires `xdotool` and `wmctrl`).
- **Capability-aware controls** — The phone shows only the actions each player/window/app actually supports (play/pause, next/prev, seek, focus, close, mute, volume).
- **Pre-configured commands** — Define shell commands in TOML once, invoke them from the phone by name. No arbitrary text input.
- **Web UI, no app install** — Open `http://<pc-ip>:8765` in any phone browser. No APK, no build step, bookmarkable.
- **Token auth** — Printed on startup, hidden from history. Works on trusted LANs.
- **Linux-native** — MPRIS over D-Bus, PipeWire volume, psutil app detection, systemd services. Built for GNOME/Wayland.

## Installation

### Prerequisites

- **Linux PC** (Ubuntu 22.04+, Fedora 37+, or similar with systemd + PipeWire/ALSA + GNOME Shell 45+)
- **Python 3.11+** (check: `python3 --version`)
- **Phone** with a modern browser (same WiFi network or routed access)

### Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/yourusername/voicetalk
   cd voicetalk
   ```

2. **Install system dependencies** (one-time)
   ```bash
   # Debian/Ubuntu
   sudo apt-get install python3-aiohttp python3-psutil python3-dbus

   # Fedora
   sudo dnf install python3-aiohttp python3-psutil python3-dbus
   ```

3. **Verify preflight checks**
   ```bash
   python3 -m vt doctor
   ```

   All lines should be ✓ (or ℹ for optional features). If D-Bus or wpctl fail, your system cannot run VoiceTalk.

4. (Optional) **Install the window control extension**
   ```bash
   python3 -m vt install-extension
   ```

   This enables the `Focus` and `Close` buttons for open windows. On Wayland, you **must log out and log back in** for the extension to activate.

5. (Optional) **Configure custom commands**
   ```bash
   mkdir -p ~/.config/voicetalk
   cp commands.toml.example ~/.config/voicetalk/commands.toml
   nano ~/.config/voicetalk/commands.toml
   ```

   See `commands.toml.example` for syntax. Commands are validated on startup and invalid entries are skipped with a warning.

## Quick Start

1. **Start the server**
   ```bash
   python3 -m vt serve
   ```

   Output:
   ```
   VoiceTalk → http://192.168.1.5:8765/?t=Xq3v...
   Token: Xq3v...

   Press Ctrl+C to stop.
   ```

2. **Open the URL on your phone** (or scan the QR code if printed)
   - The token is stored in the browser's `localStorage`, so the bookmark works for future sessions.

3. **Control your PC**
   - Select a target (media player, window, app, command)
   - Click `Actions` to expand the dropdown
   - Adjust sliders or tap buttons

## Commands

| Command | Purpose |
|---------|---------|
| `vt serve [--host IP] [--port 8765] [--no-token] [--open]` | Start the HTTP server on a given host/port. Default host is your detected LAN IP. Without `--no-token`, a random token is generated and required for all API calls. `--open` attempts to open the page in your default browser. |
| `vt status` | Print the current state as a terminal table (no web server). |
| `vt do <target-id> <action-id> [value]` | Invoke an action from the CLI. For testing. |
| `vt commands` | List configured commands. |
| `vt apps [query]` | List installed apps you can launch, optionally filtered (`vt apps browser`). Launch one with `vt do launcher:<id> launch`. |
| YouTube Search | Find and play YouTube videos from the phone UI (with `yt-dlp` installed) |
| `vt doctor` | Run preflight checks. |
| `vt install-extension` | Install the GNOME Shell window control extension. |

## HTTP API

The web UI speaks three endpoints (token required via `X-VT-Token` header):

```
GET /api/state
  → {"targets": [...], "ts": unix_timestamp}

GET /api/apps[?q=search+terms]
  → {"apps": [{"id": "launcher:firefox", "title": "Firefox", ...}]}

POST /api/do
  ← {"target": "kind:id", "action": "action-id", "value": float?}
  → {"ok": bool, "message": "..."}
```

Installed apps are deliberately not part of `/api/state`: there are hundreds of
them and they change about once a week, so they would dwarf the state that
actually moves in a 1 Hz poll. The phone fetches `/api/apps` once, when you open
the list, and filters as you type.

## Configuration

### `commands.toml`

Place at `~/.config/voicetalk/commands.toml` to add custom commands.

```toml
[[command]]
id    = "lock"
label = "🔒 Lock Screen"
run   = ["loginctl", "lock-session"]

[[command]]
id      = "suspend"
label   = "💤 Suspend"
run     = ["systemctl", "suspend"]
confirm = true              # Require double-tap
```

**Rules:**
- `run` is always a list of arguments (shell=False), never a string. This is the security boundary.
- `id` must be unique and cannot collide with built-in actions.
- If `confirm: true`, the phone requires a second tap ("Sure?") before executing.
- Invalid entries are logged and skipped on startup.

## Internals

- **Targets** — Everything controllable (media players, windows, apps, system controls, commands) is a Target with a list of Actions.
- **Sources** — Targets come from:
  - **MPRIS** (`sources/mpris.py`) — Media players (Firefox, Chrome, VLC, Spotify, etc.)
  - **Windows** (`sources/windows.py`) — Open windows via GNOME Shell extension (optional)
  - **Apps** (`sources/apps.py`) — Running apps matched against `.desktop` files, and every installed `.desktop` entry as a launchable target
  - **Audio** (`sources/audio.py`) — System volume via `wpctl`
  - **Commands** (`commands.py`) — User-defined shell commands from TOML
- **Actions** — Derived from player capabilities (CanPlay, CanPause, CanSeek, etc.) so unsupported actions don't appear.
- **State refresh** — 1 Hz background task. The web UI polls instantly; the server caches.

## Limitations

- **Wayland** — Keystroke injection is not possible; the old F11 fullscreen / arrow seek are gone.
- **MPRIS only** — Only players that register on D-Bus appear (Firefox, Chrome, VLC, mpv, Spotify). HTML5 `<video>` without a media session will not.
- **Window extension** — Requires GNOME Shell 45+, needs a logout/login to activate, and may need a `metadata.json` update for GNOME 51+. On X11 or KDE, the feature doesn't work.
- **Plain HTTP** — The token stops casual access on a trusted network; it is not TLS. Do not expose to the internet.

## Troubleshooting

**No targets appear on the phone:**
- Run `vt doctor` and fix any failures.
- Check the server logs: `vt serve` prints errors to stdout.
- Ensure your phone and PC are on the same network (or route exists).

**Window actions not working:**
- Run `vt install-extension` and log out/in.
- Check: `gnome-extensions list | grep voicetalk` should show `voicetalk@local`.
- Check D-Bus: `gdbus call --session --dest org.gnome.Shell.Extensions.VoiceTalk --object-path /org/gnome/Shell/Extensions/VoiceTalk --method org.gnome.Shell.Extensions.VoiceTalk.List`

**Commands not executing:**
- Check `~/.config/voicetalk/commands.toml` exists and parses: `python3 -c "from vt.commands import CommandsConfig; c = CommandsConfig(); print(c.get_errors())"`.
- Ensure `run` is a list, not a string: `run = ["systemctl", "suspend"]` not `run = "systemctl suspend"`.

**Media players missing, or the log repeats "Introspect error ... AccessDenied":**
- You started `vt` from inside a snap's built-in terminal (the VS Code snap's,
  most often). Its children inherit the snap's AppArmor label, and snap policy
  then blocks them from talking to *other* snaps — so snap-packaged Firefox
  refuses every property read and its player vanishes from the phone.
- Fix: run `vt serve` from an ordinary terminal (GNOME Terminal). `vt doctor`
  reports the confinement under `Confinement` and `MPRIS`.

**YouTube playback controls don't appear:**
- Make sure `xdotool` and `wmctrl` are installed: `apt install xdotool wmctrl`
- Open a YouTube video in Firefox or Chrome
- Check that the video window title contains "youtube" or "youtube.com"

**Volume slider unresponsive:**
- Check `wpctl status` output. If no sinks, PipeWire is not running or misconfigured.

## Security

- **Token auth** — A 22-character URL-safe random token, required for every API call. Regenerated each startup (or persisted with `--save-token` when that flag is added).
- **Command validation** — Commands are defined in a TOML file on the PC; the phone can only name one, not supply arguments.
- **Trusted LAN** — Assumes the network is trusted. Do not bind to `0.0.0.0` and expose to the internet.
- **No secrets stored** — V3 has no API keys, no SMTP credentials, no encryption at rest. Config is plain TOML.

## Project Structure

```
voicetalk/
├── vt/
│   ├── __init__.py
│   ├── cli.py                  # CLI entry point
│   ├── model.py                # Target/Action dataclasses
│   ├── state.py                # Snapshot assembly
│   ├── server.py               # aiohttp HTTP server
│   ├── commands.py             # TOML commands loader
│   ├── sources/
│   │   ├── mpris.py            # MPRIS players
│   │   ├── windows.py          # GNOME extension
│   │   ├── apps.py             # Running and installed apps
│   │   └── audio.py            # PipeWire volume
│   ├── ui/
│   │   └── index.html          # Single-file web UI
├── gnome-extension/voicetalk@local/
│   ├── metadata.json
│   ├── extension.js            # D-Bus window interface
├── pyproject.toml
├── commands.toml.example
├── README.md
└── tests/                      # pytest suite (WIP)
```

## Development

To contribute:

1. Install dev deps: `pip install -e '.[dev]'`
2. Run tests: `pytest -xvs tests/`
3. Run the server: `python3 -m vt serve`
4. Test the CLI: `python3 -m vt status`

## License

MIT (see LICENSE file, coming soon)

## Acknowledgments

- Built on MPRIS (freedesktop.org), PipeWire (pipewire.org), GNOME Shell, and aiohttp.
- Inspired by the original VoiceTalk v1–v2, refactored for simplicity and Linux-native APIs.
