# VoiceTalk v3 — Linux CLI + Web Remote

Control your Linux PC from your phone via a simple web interface. See what's playing, what's open, what apps are running — and control it all with a dropdown of concrete actions. No app installs, no voice, no AI guessing. Just you, your PC state, and pre-configured commands.

## Features

- **Real-time state display** — See MPRIS players, open windows, running apps, and system audio.
- **Launch installed apps** — Search everything with a `.desktop` entry and start it from the phone, whether or not it is already running.
- **YouTube search & play** — Search YouTube videos, see results with title, channel and duration, and tap to play in your browser. The video **starts on its own** and shows up under Players — vt checks the browser's autoplay policy and can fix it from the phone if it would block playback.
- **YouTube playback control** — When a YouTube video plays in your browser, control it from the phone: play/pause, seek, volume, fullscreen, close (requires `xdotool` and `wmctrl`).
- **Capability-aware controls** — The phone shows only the actions each player/window/app actually supports (play/pause, next/prev, seek, focus, close, mute, volume).
- **Pre-configured commands** — Define shell commands in TOML once, invoke them from the phone by name. No arbitrary text input.
- **Cloudflare Tunnel** — `make dev` starts a quick tunnel by default, giving you a `*.trycloudflare.com` URL accessible from anywhere. No port forwarding, no router config, no Cloudflare account needed.
- **Device pairing** — off-network callers must present a paired-device credential; the startup token is only accepted on the LAN. Pair a phone with `vt pair` or the QR code printed at startup.
- **Web UI, no app install** — Open `http://<pc-ip>:8765` in any phone browser. No APK, no build step, bookmarkable.
- **Token auth** — Printed on startup, hidden from history. Works on trusted LANs.
- **Linux-native** — MPRIS over D-Bus, PipeWire volume, psutil app detection, systemd services. Built for GNOME/Wayland.

## Installation

### Prerequisites

- **Linux PC** (Ubuntu 22.04+, Fedora 37+, or similar with systemd + PipeWire/ALSA + GNOME Shell 45+)
- **Python 3.11+** (check: `python3 --version`)
- **Phone** with a modern browser (same WiFi network or routed access)

### Quick Install (PyPI)

1. **Install system dependencies** (one-time)
   ```bash
   # Debian/Ubuntu
   sudo apt-get install python3-dbus python3-gi

   # Fedora
   sudo dnf install python3-dbus python3-gi
   ```

   These two cannot be pip-installed without libdbus/glib headers, so they come
   from the distro. Everything else is installed via pip.

2. **Install VoiceTalk** (one-time)
   ```bash
   pip install voicetalk
   ```

   This installs the `vt` command globally. You can now run `vt serve` from anywhere.

3. **Verify preflight checks**
   ```bash
   vt doctor
   ```

   All lines should be ✓ (or ℹ for optional features). If D-Bus or wpctl fail, your system cannot run VoiceTalk.

4. (Optional) **Install the window control extension**
   ```bash
   vt doctor      # confirm the extension line first
   vt install-extension
   ```

   This enables the `Focus` and `Close` buttons for open windows. On Wayland, you **must log out and log back in** for the extension to activate.

5. (Optional) **Configure custom commands**
   ```bash
   mkdir -p ~/.config/voicetalk
   cp ~/.local/lib/python*/site-packages/vt/commands.toml.example ~/.config/voicetalk/commands.toml
   nano ~/.config/voicetalk/commands.toml
   ```

   See the example file for syntax. Commands are validated on startup and invalid entries are skipped with a warning.

### Development Setup (from source)

For development or to work on the code:

1. Clone and enter the repo
   ```bash
   git clone https://github.com/Vaithorat/voicetalk
   cd voicetalk
   ```

2. Install system dependencies (same as above)
   ```bash
   sudo apt-get install python3-dbus python3-gi
   ```

3. Set up development environment
   ```bash
   make setup
   ```

   Creates a venv and installs the package in editable mode with dev/test extras.

4. Run tests and linting
   ```bash
   make test
   make lint
   ```

5. Start the development server
   ```bash
   make dev
   ```

## Quick Start

1. **Start the server**
   ```bash
   make dev
   ```

   `make dev` is the only start command you need. It sets the environment up if
   it isn't already, then runs the server through `venv/bin/vt` by absolute
   path — so it behaves identically from a VS Code terminal, a plain shell, or
   any other directory. A Cloudflare tunnel is started by default.

   Output:
   ```
   VoiceTalk → http://192.168.1.5:8765/?t=Xq3v...
   Token: Xq3v...

   ⏳ Starting Cloudflare Tunnel...

   ── Cloudflare Tunnel is up ────────────────────
   Public URL: https://some-words.trycloudflare.com

   ── Pair a device ──────────────────────────────
   Code:  RRMFH-2QK9X   (valid 10 min, one device)
   Link:  https://some-words.trycloudflare.com/?p=RRMFH2QK9X
   ```

2. **Open the URL on your phone** (or scan the QR code)
   - From the LAN: the token is stored in `localStorage`, bookmark works.
   - From anywhere: enter the pairing code shown at startup.

3. **Control your PC**
   - Select a target (media player, window, app, command)
   - Click `Actions` to expand the dropdown
   - Adjust sliders or tap buttons

## Commands

| Command | Purpose |
|---------|---------|
| `vt serve [--host IP] [--port 8765] [--no-token] [--open] [--tunnel]` | Start the HTTP server. Default: LAN IP with Cloudflare tunnel. `--tunnel` enables a quick tunnel for global access. `--no-token` disables token auth. `--open` opens in browser. |
| `vt pair [--url URL] [--port PORT] [--minutes N]` | Issue a one-time pairing code for a new device. Prints a link and QR code. |
| `vt devices [--revoke ID] [--revoke-all]` | List paired devices or revoke access. |
| `vt audit [-n N] [--rejects]` | Show recent security log entries. |
| `vt status` | Print the current state as a terminal table (no web server). |
| `vt do <target-id> <action-id> [value]` | Invoke an action from the CLI. For testing. |
| `vt commands` | List configured commands. |
| `vt apps [query]` | List installed apps you can launch, optionally filtered (`vt apps browser`). Launch one with `vt do launcher:<id> launch`. |
| YouTube Search | Find and play YouTube videos from the phone UI (with `yt-dlp` installed) |
| `vt allow-autoplay [--status] [--revert] [--restart]` | Let the browser start videos opened from the phone. Writes `media.autoplay.default` into the Firefox profile's `user.js` — the same setting as Settings → Privacy & Security → Autoplay → Allow Audio and Video. Takes effect on the next Firefox start; `--restart` does that for you. |
| `vt doctor` | Run preflight checks. |
| `vt install-extension` | Install the GNOME Shell window control extension. |

## HTTP API

The web UI speaks several endpoints. Token auth via `X-VT-Token` header for
LAN; device auth via `X-VT-Device` + `X-VT-Secret` headers for remote access.

```
GET /api/session
  → {authenticated, kind, device_id, remote, needs_pairing}

POST /api/pair
  ← {code, name}
  → {ok, device_id, secret, name}

POST /api/pair/self
  ← {name}
  → {ok, device_id, secret, name}

GET /api/devices
  → {devices: [...], current: device_id}

POST /api/devices/revoke
  ← {id}

GET /api/state
  → {"targets": [...], "ts": unix_timestamp}

GET /api/apps[?q=search+terms]
  → {"apps": [{"id": "launcher:firefox", "title": "Firefox", ...}]}

GET /api/youtube[?q=search+terms]
  → {"results": [...], "error": ""}

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
  - **YouTube** (`sources/youtube.py`) — Search via `yt-dlp`, and opening a video in the browser. Before it opens one it asks `sources/browser_autoplay.py` whether the browser will actually start playing, so a tap that cannot succeed says why instead of reporting success.
  - **Commands** (`commands.py`) — User-defined shell commands from TOML
- **Actions** — Derived from player capabilities (CanPlay, CanPause, CanSeek, etc.) so unsupported actions don't appear.
- **State refresh** — 1 Hz background task. The web UI polls instantly; the server caches.

## Limitations

- **Wayland** — Keystroke injection is not possible; the old F11 fullscreen / arrow seek are gone.
- **MPRIS only** — Only players that register on D-Bus appear (Firefox, Chrome, VLC, mpv, Spotify). HTML5 `<video>` without a media session will not.
- **Window extension** — Requires GNOME Shell 45+, needs a logout/login to activate, and may need a `metadata.json` update for GNOME 51+. On X11 or KDE, the feature doesn't work.
- **Autoplay is a browser setting** — vt can read and set it for Firefox (`vt allow-autoplay`), but it only takes effect on the next Firefox start, and for Chromium-family browsers there is no equivalent switch from outside the process.
- **Plain HTTP** — The token stops casual access on a trusted network; it is not TLS. The Cloudflare tunnel provides HTTPS end-to-end.

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

**A video opens on the PC but sits there paused:**
- The browser is blocking autoplay. Firefox blocks audible autoplay by default,
  so the tab loads, nothing plays, no MPRIS player is published, and the video
  never reaches the **Players** list — from the phone it looks like the tap did
  nothing at all.
- Fix from the phone: open **YouTube Search**; the banner at the top offers
  **Allow autoplay**, which sets the pref and restarts Firefox (tabs are
  restored) so the video you just picked starts playing.
- Fix from the PC: `vt allow-autoplay`, then restart Firefox — or set
  Settings → Privacy & Security → Autoplay to **Allow Audio and Video** yourself.
- `vt doctor` reports this under `Autoplay`, and `vt allow-autoplay --status`
  shows which profile it read.
- Undo with `vt allow-autoplay --revert`. Note that Firefox copies the setting
  into its own `prefs.js` once it has started with it, so a revert removes vt's
  override but the value can persist — the command says so when that happens,
  and the Settings UI is then the way back.

**YouTube playback controls don't appear:**
- Make sure `xdotool` and `wmctrl` are installed: `apt install xdotool wmctrl`
- Open a YouTube video in Firefox or Chrome
- Check that the video window title contains "youtube" or "youtube.com"

**Volume slider unresponsive:**
- Check `wpctl status` output. If no sinks, PipeWire is not running or misconfigured.

## Security

Two tiers of access, deliberately unequal:

- **LAN** — the startup token in the URL is enough. It travels in a bookmark
  and a QR code, which is fine for a network you already control.
- **Remote** — the token is not accepted at all. The caller must present a
  paired-device credential, and a device is paired once, from a code that only
  ever appears on this PC's own terminal.

That split is the whole security model: exposing the public URL leaks nothing,
because the URL is not a credential off-network.

- **Device pairing** — 31^10 entropy codes, 10-minute TTL, single-use. Pair a
  device with `vt pair` or the QR printed at startup. Max 32 devices.
- **Rate limiting** — 5 failed auth attempts per IP triggers a 15-minute
  lockout. Pairing attempts are rate-limited globally (30/hour).
- **Audit log** — every authenticated action and rejected attempt is recorded
  in `~/.local/state/voicetalk/audit.log`. View with `vt audit`.
- **Security headers** — CSP, HSTS, X-Frame-Options, nosniff on every response.
- **Command validation** — Commands are defined in a TOML file on the PC; the
  phone can only name one, not supply arguments.
- **No secrets stored** — V3 has no API keys, no SMTP credentials, no
  encryption at rest. Device secrets are SHA-256 hashed.

## Project Structure

```
voicetalk/
├── vt/
│   ├── __init__.py
│   ├── cli.py                  # CLI entry point
│   ├── model.py                # Target/Action dataclasses
│   ├── state.py                # Snapshot assembly
│   ├── server.py               # aiohttp HTTP server
│   ├── auth.py                 # Device pairing, credentials, rate limiting
│   ├── tunnel.py               # Cloudflare Tunnel integration
│   ├── commands.py             # TOML commands loader
│   ├── sources/
│   │   ├── mpris.py            # MPRIS players
│   │   ├── windows.py          # GNOME extension
│   │   ├── apps.py             # Running and installed apps
│   │   ├── audio.py            # PipeWire volume
│   │   ├── youtube.py          # Search, and opening a video so it plays
│   │   ├── youtube_player.py   # X11-only keystroke fallback
│   │   └── browser_autoplay.py # Whether the browser will actually start it
│   ├── ui/
│   │   └── index.html          # Single-file web UI
├── gnome-extension/voicetalk@local/
│   ├── metadata.json
│   ├── extension.js            # D-Bus window interface
├── Makefile                    # make dev / setup / test / doctor
├── scripts/envreport.py        # backs `make env`
├── pyproject.toml
├── commands.toml.example
├── README.md
└── tests/                      # pytest suite (WIP)
```

## Development

Everything goes through `make`. Each target sets the environment up first if it
needs to, so there is no activate step and no ordering to remember.

| Target | What it does |
|--------|--------------|
| `make dev` | Set up if needed, then start the server. **Start here.** |
| `make setup` | Create `venv/` and install deps. Idempotent; re-runs only when `pyproject.toml` changes. |
| `make test` | Run the pytest suite (`make test ARGS="-x -k mpris"`). |
| `make doctor` | Preflight checks — D-Bus, PipeWire, port, extension, config. |
| `make status` / `make commands` / `make apps` | CLI passthroughs. |
| `make env` | Print the resolved interpreter and which optional deps it can see. |
| `make link` / `make unlink` | Add/remove `~/.local/bin/vt`. |
| `make deps` | Force a dependency reinstall. |
| `make clean` | Drop caches and build artifacts (keeps the venv). |
| `make reset` | Delete the venv and rebuild from scratch (~10s). |

Options apply to `make dev`: `HOST=0.0.0.0`, `PORT=9000`, `NO_TOKEN=1`, `OPEN=1`,
and `ARGS="..."` for anything else.

### Why make, and not `python3 -m vt serve`

`python3 -m vt serve` resolves to a different interpreter depending on where you
run it. A VS Code terminal auto-activates `venv/` and gets `yt-dlp`; a plain
shell gets the system Python and doesn't, so YouTube search quietly stops
working — and from any directory other than the repo root the import fails
outright. The Makefile removes the ambiguity:

- every path is derived from the Makefile's own location, never from `$PWD`
- every command runs `venv/bin/python` or `venv/bin/vt` by absolute path
- `VIRTUAL_ENV`, `PYTHONPATH`, and `PYTHONHOME` from the calling shell are
  dropped, so an unrelated activated venv cannot change the result

If two terminals still disagree, run `make env` in both and compare the
`interpreter` line.

## License

MIT (see LICENSE file, coming soon)

## Acknowledgments

- Built on MPRIS (freedesktop.org), PipeWire (pipewire.org), GNOME Shell, and aiohttp.
- Inspired by the original VoiceTalk v1–v2, refactored for simplicity and Linux-native APIs.
