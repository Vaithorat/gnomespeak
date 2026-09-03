# GnomeSpeak — Linux CLI + Web Remote

[![CI](https://github.com/Vaithorat/gnomespeak/actions/workflows/ci.yml/badge.svg)](https://github.com/Vaithorat/gnomespeak/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/gnomespeak)](https://pypi.org/project/gnomespeak/)
[![Python](https://img.shields.io/pypi/pyversions/gnomespeak)](https://pypi.org/project/gnomespeak/)
[![License: MIT](https://img.shields.io/github/license/Vaithorat/gnomespeak)](LICENSE)

**The remote for your Linux desktop that needs nothing installed on the phone and works from outside the house — because it sends state, not screens.**

Open a URL in any phone browser and you get a live model of what the PC is doing: what is playing, what is open, what apps are running, what the volume and battery are — each one a target with concrete actions, one tap each. Kilobytes per update rather than megabits, so it still works on mobile data in a lift. No app to install, no voice, no AI guessing.

## Features

- **Live channel over WebSocket** — Sub-300ms state updates (`GET /ws`) with JSON diff patches. Transmits only changed targets; an idle PC uses virtually zero network traffic. Falls back automatically to 1 Hz HTTP polling.
- **Starts with the desktop session** — `vt install-service` installs a systemd *user* service bound to `graphical-session.target`. Starts automatically on login, uninstalls cleanly with `vt uninstall-service`.
- **Installable web app (PWA) & share target** — Add to home screen from Chrome on Android for a fullscreen standalone app with quick actions. Share photos or links directly from Android's share sheet to your PC.
- **Web Push notifications** — Receive notifications on your phone even when the browser tab is closed via RFC 8291 payload encryption and RFC 8292 VAPID auth (`pip install gnomespeak[push]`).
- **Real-time state display** — See MPRIS players with album art and live position scrubbers, open windows, individual Firefox tabs, workspaces, running apps, streaming shortcuts, Bluetooth devices, and system status.
- **Per-app volume & device switching** — Control individual application stream volumes and mute independently via PipeWire (`wpctl`). Switch audio output (sinks) and input (sources) between headphones, speakers, and mics.
- **Touchpad and keyboard** — The phone is a trackpad: drag to move pointer, tap to click, two-finger scroll, two-finger tap for right-click. Type into whatever has focus, send key chords, or drive slide decks with a Prev/Next/F5/Escape presentation row. Works under Wayland via the compositor extension.
- **Context-aware keypads** — Dedicated shortcut pads automatically tailored for the currently focused app (VLC, mpv, Firefox, terminal, etc.).
- **Hardware system monitor** — Glanceable CPU, memory, disk usage, thermal sensor temperatures, and system uptime (`system:machine`).
- **Screenshot on demand** — Capture a still frame of your desktop on demand via `org.freedesktop.portal.Screenshot`, viewed securely and removed immediately from disk.
- **Ring this PC & battery sync** — Trigger an audible alarm and notification to find a misplaced laptop across the room, with on-screen stop control. Synchronizes phone battery level to the PC with low-battery alerts in both directions.
- **Removable drives** — Detect mounted USB/external drives, view storage usage, and safely unmount and power them off via udisks2.
- **Sleep timers & schedule** — Schedule delays to suspend, lock, or pause media ("suspend in 30 minutes") directly from the phone.
- **Command macros** — Define multi-step sequences in `commands.toml` with optional delays between steps (e.g. Movie Mode: night light on, DND on, set volume).
- **Clipboard sync & history** — Read and write the PC clipboard (`wl-clipboard` on Wayland, `xclip`/`xsel` on X11), with in-memory recent clipboard history.
- **Open links & set wallpaper** — Open any link sent from your phone in the PC browser with one tap. Set any transferred image as your desktop background (light and dark themes).
- **Launch installed apps & Steam games** — Search and launch any desktop app (`.desktop` entry) or installed Steam game.
- **YouTube search, playback & Up Next** — Search YouTube, tap to play in browser with autoplay policy detection and fix, control playback (play/pause, seek, volume, fullscreen, close tab), and view related "Up next" videos.
- **Window and workspace control** — Focus, minimize, maximize, move windows across workspaces, and switch workspaces (GNOME Shell extension or COSMIC Wayland protocols).
- **Notification mirroring, dismiss & mute** — Mirror desktop notifications to the phone, dismiss them remotely, or mute notifications from noisy apps for the session.
- **Guest pairing & scopes** — Pair devices with restricted permissions (e.g. `--guest` for media controls only) and auto-expiring access (`--hours N`).
- **LAN HTTPS / TLS** — Encrypt local Wi-Fi traffic with self-signed TLS certificates (`vt serve --tls`). Off-LAN traffic is encrypted by Cloudflare Tunnel.
- **Multi-PC switcher** — Manage multiple PCs from one web UI with PC-side reachability probes (`POST /api/probe`) and Wake-on-LAN packet sending.
- **On-phone diagnostics** — View `vt doctor` preflight checks directly from the phone (`GET /api/diagnostics`), along with security audit logs (`GET /api/audit`).
- **Voice dictation** — Dictate text on your phone's microphone using Web Speech API to type directly into the focused window on your PC.
- **No phone app required** — Built purely on web standards. Works in any browser. Responsive, lightweight, and bandwidth-efficient.

## Installation

### Prerequisites

- **Linux PC** (Ubuntu 22.04+, Fedora 37+, or similar with systemd + PipeWire/ALSA + GNOME Shell 45+)
- **Python 3.11+** (check: `python3 --version`)
- **Phone** with a modern browser (same WiFi network or routed access)

### Quick Install (PyPI)

**One command to install everything:**

```bash
curl -fsSL https://raw.githubusercontent.com/Vaithorat/gnomespeak/main/install.sh | bash
```

This script:
- Detects your Linux distro (Debian/Ubuntu, Fedora, Arch or openSUSE)
- Installs the system dependencies it finds missing, asking for sudo only then
  (`python3-dbus`, `python3-gi`, `wl-clipboard`, `xclip`, `dbus-monitor`,
  `wireplumber`, `xdg-user-dirs`, plus `xdotool`/`wmctrl` on X11)
- Installs GnomeSpeak from PyPI
- Installs the GNOME extension, so window and touchpad control work at your
  next login
- Prints next steps

Nothing here is fatal. A distro it does not recognise, a machine with no sudo,
or one that is not running GNOME still ends up with a server it can start —
just with fewer features, each of which says so in `vt doctor` and on the phone.

**After installation:**

1. **Verify preflight checks**
   ```bash
   vt doctor
   ```

   All lines should be ✓ (or ℹ for optional features). If D-Bus or wpctl fail, your system cannot run GnomeSpeak.

2. **Log out and back in**

   GNOME Shell only loads extensions at session start under Wayland, so window
   control (`Focus`, `Close`, minimize/maximize, workspaces), the touchpad,
   typing and the presentation remote start working after the next login. To
   install or repair the extension by hand:

   ```bash
   vt install-extension
   ```

3. (Optional) **Configure custom commands**
   ```bash
   mkdir -p ~/.config/gnomespeak
   cp ~/.local/lib/python*/site-packages/vt/commands.toml.example ~/.config/gnomespeak/commands.toml
   nano ~/.config/gnomespeak/commands.toml
   ```

   See the example file for syntax. Commands are validated on startup and invalid entries are skipped with a warning.

### Development Setup (from source)

For development or to work on the code:

1. Clone and enter the repo
   ```bash
   git clone https://github.com/Vaithorat/gnomespeak
   cd gnomespeak
   ```

2. Start the server
   ```bash
   make dev
   ```

   That is the whole setup. `make dev` installs any missing system packages
   (asking for sudo at that point, and only then), builds the venv, installs the
   package in editable mode with the dev/test extras, installs the GNOME
   extension if it is missing or broken, and starts the server. Every step is
   idempotent, so the second run is fast and silent, and none of them can fail
   the run — a missing package means a missing feature, not a missing server.

   To skip the package step (an air-gapped box, or one where you manage
   packages yourself): `make dev SKIP_SYSTEM=1`. To check what it would install
   without installing anything: `scripts/setup-system.sh --check`.

3. Run tests and linting
   ```bash
   make test
   make lint
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
   GnomeSpeak → http://192.168.1.5:8765/?t=Xq3v...
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
| `vt pair [--url URL] [--port PORT] [--minutes N] [--guest] [--hours N]` | Issue a one-time pairing code for a new device. Prints a link and QR code. `--guest` limits the phone to media (no power, input, files, clipboard or pairing); `--hours` makes its access end by itself. |
| `vt devices [--revoke ID] [--revoke-all]` | List paired devices or revoke access. |
| `vt audit [-n N] [--rejects]` | Show recent security log entries. |
| `vt status` | Print the current state as a terminal table (no web server). |
| `vt do <target-id> <action-id> [value]` | Invoke an action from the CLI. For testing. |
| `vt commands` | List configured commands, including macros. |
| `vt apps [query]` | List installed apps you can launch, optionally filtered (`vt apps browser`). Launch one with `vt do launcher:<id> launch`. |
| YouTube Search | Find and play YouTube videos from the phone UI (with `yt-dlp` installed) |
| `vt allow-autoplay [--status] [--revert] [--restart]` | Let the browser start videos opened from the phone. Writes `media.autoplay.default` into the Firefox profile's `user.js` — the same setting as Settings → Privacy & Security → Autoplay → Allow Audio and Video. Takes effect on the next Firefox start; `--restart` does that for you. |
| `vt serve --tls` | Serve HTTPS on the LAN with a certificate this PC makes for itself. The phone warns once; the fingerprint to check is printed at startup. Off-LAN traffic already rides the tunnel's TLS. Needs `pip install gnomespeak[push]` (same extra). |
| `vt open <url>` | Open an http(s) link in this PC's browser. The same path the phone uses. |
| `vt wake <mac> [--broadcast ADDR] [--port N]` | Send a wake-on-LAN packet to another machine. Nothing acknowledges one, so it reports "sent", never "woken". |
| `vt doctor` | Run preflight checks. |
| `vt install-extension` | Install the GNOME Shell extension (windows, workspaces, pointer, typing). Cleans up a pre-rename `voicetalk@local` install and enables the new one for the next login. |
| `vt package-extension [--uuid UUID] [--out DIR]` | Build the zip to upload to [extensions.gnome.org](https://extensions.gnome.org/upload/). The archive carries the store uuid (`gnomespeak@vaithorat.github.io`) while the checkout keeps `gnomespeak@local`; both are recognised by `vt doctor` and by the server. Bump `version` in `gnome-extension/*/metadata.json` before each resubmission. |
| `vt install-service [--port N] [--tunnel-name NAME] [--no-start]` | Start the server with your desktop session, as a systemd *user* unit. Requires pairing (a service's banner reaches nobody), so get in with `vt pair`. Logs: `journalctl --user -u gnomespeak -f`. |
| `vt uninstall-service` | Stop, disable and remove that unit. |

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

GET /api/youtube/related
  → {"results": [...], "error": ""}

POST /api/do
  ← {"target": "kind:id", "action": "action-id", "value": float?}
  → {"ok": bool, "message": "..."}

GET  /api/clipboard
  → {ok, text, message, tool}

POST /api/clipboard
  ← {text}
  → {ok, message}

POST /api/input
  ← {"op": "move",   "dx": int, "dy": int}      pointer, relative
    {"op": "scroll", "dx": int, "dy": int}      pixels of thumb travel
    {"op": "click",  "button": "left|middle|right", "double": bool}
    {"op": "type",   "text": "..."}             into whatever has focus
    {"op": "keys",   "keys": "ctrl+shift+t"}    comma-separated chords
  → {ok, message}

GET  /api/notifications?since=<seq>
  → {ok, entries: [{seq, ts, app, icon, summary, body, id}], error, running}

POST /api/notifications/dismiss
  ← {id}                                       the id from an entry above
  → {ok, message}

GET  /api/screenshot
  → image/png, taken now and deleted from disk once served
    403 {ok:false, message} when the portal prompt was declined

GET  /api/art?k=<key>
  → image/png|jpeg, the album art a player published (key comes from a target)

GET  /api/audit[?count=60]
  → {entries: [...]}   the security log, newest last

POST /api/ws-ticket
  → {ok, ticket, expires_in}                   single-use, seconds to live

GET  /ws?ticket=<ticket>
  → a live channel. Server sends {type:"state"|"patch"}; the phone may send
    {type:"input"|"battery"|"ring"|"ring_stop"|"resync"|"ping"}.
    Notifications are pushed as {type:"notification", entries:[...]} once the
    mirror is running (the notifications screen starts it).

POST /api/open                 ← {url} → {ok, message}
  Opens an http(s) link in the PC's browser. Anything else is refused.

GET  /api/clipboard/history    → {entries: [{seq, ts, text, truncated, length}]}
DELETE /api/clipboard/history  → {ok, cleared}
  The last few clips, in memory on the PC only.

GET  /api/diagnostics          → {checks: [{id, title, state, detail, fix, lost}], summary}
  `vt doctor` for the phone.

POST /api/files/wallpaper      ← {name} → {ok, message}
  Uses a transferred picture as the desktop background.

GET  /api/push/key             → {ok, available, key, subscribed}
POST /api/push/subscribe       ← {subscription} → {ok, message}
POST /api/push/unsubscribe     ← {endpoint?} → {ok, removed}
  Web Push, so notifications and alerts arrive with the page closed. Needs
  `pip install gnomespeak[push]` on the PC.

POST /api/notifications/mute   ← {app, muted?} → {ok, muted: [...]}
  Stops mirroring one app for this session; `muted: false` asks for it back.

POST /api/wake                 ← {mac} → {ok, message}
  Wake-on-LAN for another machine on the network.

POST /api/probe                ← {urls: [...]} → {servers: [{url, reachable, checked}]}
  Whether each saved PC answers, checked from this PC. A yes or no and nothing
  else: no status code, no body. At most 10 origins, http(s) only.

GET  /api/files                → {files: [{name, size, mtime}], dir}
POST /api/upload               multipart, field name "file" → {ok, name, size}
GET  /api/files/<name>         → the file itself
POST /api/files/open           ← {name} → {ok, message}

POST /share                    ← multipart form data from Android share sheet
GET  /{sw.js|manifest.webmanifest|*.png} → PWA service worker, web manifest, and icons
```

Remote input has an endpoint of its own rather than being an action: a trackpad
has no target in the snapshot and sends about twenty deltas a second, so routing
it through `/api/do` would mean a snapshot lookup and an audit line per pointer
movement. Typing and key chords *are* audited; pointer motion is not.

The live channel replaces the poll where a browser can hold a socket: the
server pushes only the targets that changed, so a PC that is doing nothing
sends nothing. `/api/state` keeps serving the whole snapshot, unchanged, for
any client that never opens `/ws`. A WebSocket handshake cannot carry headers,
so the credential is exchanged for a single-use ticket first — a device secret
in a URL would outlive the session in proxy logs and browser history.

Installed apps are deliberately not part of `/api/state`: there are hundreds of
them and they change about once a week, so they would dwarf the state that
actually moves in a 1 Hz poll. The phone fetches `/api/apps` once, when you open
the list, and filters as you type.

## Configuration

### `commands.toml`

Place at `~/.config/gnomespeak/commands.toml` to add custom commands.

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

# Or a macro: sequential target-and-action steps with optional waits
[[command]]
id    = "movie_mode"
label = "🎬 Movie Mode"
icon  = "🎬"
steps = [
  {target = "system:notifications", action = "dnd_on"},
  {target = "system:display", action = "night_light_on"},
  {wait = 0.5},
  {target = "system:audio", action = "volume", value = 0.4},
]
```

**Rules:**
- `run` is always a list of arguments (shell=False), never a string. This is the security boundary.
- Alternatively, `steps` defines a sequence of target/action pairs (e.g. `{target = "system:audio", action = "volume", value = 0.4}`) or `{wait = seconds}`. Steps cannot name external binaries, keeping commands safe.
- `id` must be unique and cannot collide with built-in actions.
- If `confirm: true`, the phone requires a second tap ("Sure?") before executing.
- Invalid entries are logged and skipped on startup.

## Internals

- **Targets** — Everything controllable (media players, windows, apps, system controls, commands) is a Target with a list of Actions.
- **Sources** — Targets come from:
  - **MPRIS** (`sources/mpris.py`) — Media players (Firefox, Chrome, VLC, Spotify, etc.) with album art (`sources/art.py`) and live position tracking
  - **Windows** (`sources/windows.py`) — Open windows via the GNOME Shell extension, or via `sources/cosmic_windows.py` talking COSMIC's Wayland protocols (`pip install gnomespeak[wayland]`)
  - **Input injection** (`sources/remote_input.py`, `sources/cosmic_input.py`) — Wayland input synthesis via GNOME extension or COSMIC virtual keyboard protocols
  - **Firefox tabs** (`sources/firefox.py`) — Tab list read directly from Firefox session store (`recovery.jsonlz4`), switched via keyboard shortcuts
  - **Apps** (`sources/apps.py`) — Running apps matched to `.desktop` entries, plus installed launcher targets (`/api/apps`)
  - **Audio** (`sources/audio.py`) — System volume, per-application stream mixers, and sink/source output switching via `wpctl` (PipeWire)
  - **YouTube** (`sources/youtube.py`, `sources/youtube_player.py`) — Search via `yt-dlp`, related videos, autoplay verification (`sources/browser_autoplay.py`), and media key controls
  - **Commands & Macros** (`commands.py`) — Shell commands (argv) and multi-step macros from TOML
  - **Network** (`sources/network.py`) — Wi-Fi radio state and switching between saved NetworkManager connections
  - **Clipboard** (`sources/clipboard.py`, `sources/clipboard_history.py`) — Bi-directional clipboard sync and in-memory history
  - **Notifications** (`sources/notifications_mirror.py`, `push.py`) — Live D-Bus notification monitor with dismiss/mute, plus Web Push
  - **Disks** (`sources/disks.py`) — Removable USB storage list, usage, and safe ejection via `udisksctl`
  - **Keypads** (`sources/keypads.py`) — Context-aware keyboard shortcuts tailored to the active application
  - **Monitor** (`sources/monitor.py`) — System performance (CPU, memory, disk, thermals, uptime) via `psutil`
  - **Screenshot** (`sources/screenshot.py`) — On-demand portal still capture
  - **Ring** (`sources/ring.py`, `notify.py`) — PC alarm sound and desktop notification banners
  - **Open & Wallpaper** (`sources/open_url.py`, `sources/wallpaper.py`) — Open URL in browser and set background image
  - **Wake-on-LAN** (`sources/wake.py`) — Broadcast magic packets across the local subnet
- **Actions** — Derived from capabilities (CanPlay, CanPause, CanSeek, etc.) so unsupported actions don't appear.
- **State refresh** — Live WebSocket channel pushes diff patches under 300ms (`vt/live.py`). 1 Hz background task caches snapshots for `/api/state` poll fallback. Concurrent subprocess collection (`vt/procs.py`) completes snapshots in ~75ms.

## Limitations

- **Wayland** — Only the compositor may synthesize input, so keystrokes go through the GNOME extension's `SendKeys` or COSMIC's `virtual-keyboard` protocol. `xdotool` is only used as a fallback on non-GNOME, non-COSMIC X11 sessions.
- **Firefox tab list lags** — The session store is rewritten every `browser.sessionstore.interval` ms (15000 by default), so a newly opened tab can take that long to appear. Lower the pref in `about:config` for a snappier remote, at the cost of more disk writes.
- **Firefox tabs past the ninth** — Firefox binds Alt+1..8 to tabs 1-8 and Alt+9 to the last tab. Tabs in between are reached by jumping to tab 8 and stepping forward with Ctrl+PageDown, which is correct but visibly walks the tab bar.
- **MPRIS only** — Only players that register on D-Bus appear (Firefox, Chrome, VLC, mpv, Spotify). HTML5 `<video>` without a media session will not.
- **Window extension** — Requires GNOME Shell 45+, needs a logout/login to activate, and may need a `metadata.json` update for GNOME 51+. **A Shell extension only reloads on log out**, so after updating vt you must log out and back in before window state, workspaces and the YouTube keys will work; `vt doctor` says so when it detects an older build still running.
- **Window control on COSMIC** — Works via `sources/cosmic_windows.py` and `sources/cosmic_input.py` (`pip install gnomespeak[wayland]`) instead of an extension. Window focus, close, minimize, maximize, Firefox tab switching, and YouTube playback keys are supported. Workspace listing/switching on COSMIC is not yet implemented. On KDE or other non-GNOME compositors, window management is not yet supported.
- **Bluetooth pairing** — Only devices already paired through the desktop's own dialog can be connected. Pairing a *new* device needs an agent to answer a PIN or confirmation prompt, and answering it from a phone that cannot see the number on the screen is how people pair the wrong device.
- **Up next is approximate** — yt-dlp has never promised a related-videos field, so when one is absent vt searches for the current video's title instead. Similar, not identical to YouTube's own sidebar.
- **Autoplay is a browser setting** — vt can read and set it for Firefox (`vt allow-autoplay`), but it only takes effect on the next Firefox start, and for Chromium-family browsers there is no equivalent switch from outside the process.
- **Plain HTTP by default** — The token stops casual access on a trusted network; it is not TLS. Use `vt serve --tls` for local HTTPS encryption, or Cloudflare Tunnel for off-LAN HTTPS.
- **Notifications cannot be acted on, only dismissed** — Dismissal is a method on the notification daemon, so any client may call it; *activating* an action means emitting `ActionInvoked` from the daemon's own bus name, and vt is not the daemon. A reply box that could never deliver would be worse than no button.
- **Screenshots are stills, on request** — The portal prompts, one frame at a time, and nothing is retained on disk. Screen *streaming* stays out of scope: it costs megabits a second and stops working on mobile data.
- **Phone battery needs the Battery Status API** — Chromium-family browsers still expose it; Firefox removed it, and there the PC simply shows no phone row.
- **Live channel needs a WebSocket** — Where one cannot be held, the page falls back to the 1 Hz poll and keeps working.

## Troubleshooting

**No targets appear on the phone:**
- Run `vt doctor` and fix any failures.
- Check the server logs: `vt serve` prints errors to stdout.
- Ensure your phone and PC are on the same network (or route exists).

**Window actions, the touchpad or typing not working:**
- Run `vt doctor`. The **Extension** line distinguishes never installed,
  installed-but-not-yet-loaded, and an install whose symlink target is gone.
- Run `vt install-extension` and log out/in. It also removes a pre-rename
  `voicetalk@local` install, which after the rename to GnomeSpeak is a symlink
  into a directory that no longer exists — GNOME Shell drops such an extension
  without a word, so every window and keystroke action stops at once.
- Check: `gnome-extensions list | grep gnomespeak` should show `gnomespeak@local`.
- Check D-Bus (note the bus name keeps its original spelling; see ARCHITECTURE.md):
  `gdbus call --session --dest org.gnome.Shell.Extensions.VoiceTalk --object-path /org/gnome/Shell/Extensions/VoiceTalk --method org.gnome.Shell.Extensions.VoiceTalk.List`

**`make dev` asked for my sudo password:**
- Only when a system package it needs is missing. It prints the exact command
  before running it, and asks for nothing when everything is already present.
- See what it would install without installing it: `scripts/setup-system.sh --check`.
- Never install packages: `make dev SKIP_SYSTEM=1`. The server still starts; the
  features backed by whatever is missing report their own absence.

**Clipboard sync does nothing:**
- It needs `wl-clipboard` on Wayland, or `xclip`/`xsel` on X11. `vt doctor`
  names the one your session wants.

**The notifications screen stays empty:**
- It needs `dbus-monitor` (`sudo apt install dbus-bin`). Only notifications
  that arrive *after* the screen is first opened are shown — there is no
  backlog to read on a desktop.

**Commands not executing:**
- Check `~/.config/gnomespeak/commands.toml` exists and parses: `python3 -c "from vt.commands import CommandsConfig; c = CommandsConfig(); print(c.get_errors())"`.
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
- Open a YouTube video in Firefox or Chrome first — the controls only show when
  there is a tab to send keys to.
- Under Wayland (and GNOME generally) these go through the window extension.
  Run `vt doctor`: if it reports an older build, log out and back in to reload it.
- A tab in the background is found through Firefox's session store, which is
  rewritten every 15s — a video opened seconds ago may not be visible yet.
- On a non-GNOME X11 session the fallback needs `xdotool` and `wmctrl`
  (`sudo apt install xdotool wmctrl`).

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
  in `~/.local/state/gnomespeak/audit.log`. View with `vt audit`.
- **Security headers** — CSP, HSTS, X-Frame-Options, nosniff on every response.
- **Command validation** — Commands are defined in a TOML file on the PC; the
  phone can only name one, not supply arguments.
- **No secrets stored** — GnomeSpeak has no API keys, no SMTP credentials, no
  encryption at rest. Device secrets are SHA-256 hashed.

## Project Structure

```
gnomespeak/
├── vt/
│   ├── __init__.py             # Version (3.4.0)
│   ├── cli.py                  # CLI entry point (serve, pair, devices, status, do, ...)
│   ├── model.py                # Target/Action dataclasses
│   ├── state.py                # Snapshot assembly
│   ├── server.py               # aiohttp HTTP server & REST routes
│   ├── auth.py                 # Device pairing, credentials, rate limiting, scopes
│   ├── live.py                 # Live WebSocket channel with diff patching
│   ├── tunnel.py               # Cloudflare Tunnel integration
│   ├── commands.py             # TOML commands & macros loader
│   ├── notify.py               # Desktop notifications & battery alerts
│   ├── procs.py                # Concurrent subprocess runner
│   ├── push.py                 # Web Push encryption (RFC 8291) and auth (RFC 8292)
│   ├── schedule.py             # Sleep timers & scheduled actions
│   ├── service.py              # systemd user service management
│   ├── shell.py                # GNOME Shell extension D-Bus client & lifecycle
│   ├── diagnostics.py          # System preflight checks & phone diagnostics
│   ├── tls.py                  # Self-signed LAN TLS certificate generation
│   ├── package.py              # GNOME extension packager & validator
│   ├── sources/
│   │   ├── mpris.py            # MPRIS players, controls & position
│   │   ├── art.py              # Album art retrieval & caching
│   │   ├── windows.py          # Window control dispatcher
│   │   ├── cosmic_windows.py   # Wayland foreign toplevel window control (COSMIC)
│   │   ├── cosmic_input.py     # Wayland virtual keyboard input injection (COSMIC)
│   │   ├── firefox.py          # Firefox tab list from session store
│   │   ├── apps.py             # Running and installed apps (.desktop)
│   │   ├── audio.py            # PipeWire volume, per-stream mixers, sinks/sources
│   │   ├── youtube.py          # Search, related videos, watch URLs
│   │   ├── youtube_player.py   # YouTube playback controls
│   │   ├── browser_autoplay.py # Browser autoplay policy detection & fix
│   │   ├── workspaces.py       # Workspace list and switching
│   │   ├── bluetooth.py        # BlueZ radio, paired devices, battery levels
│   │   ├── streaming.py        # Streaming app-or-browser shortcuts
│   │   ├── steam.py            # Installed Steam games
│   │   ├── system.py           # Lock, suspend, brightness, DND, battery, power
│   │   ├── monitor.py          # CPU, memory, disk, thermals, uptime
│   │   ├── disks.py            # Removable drives & safe eject via udisks2
│   │   ├── keypads.py          # Context-aware per-app keypads
│   │   ├── ring.py             # PC alarm sound & desktop banner
│   │   ├── clipboard.py        # Clipboard read/write
│   │   ├── clipboard_history.py# In-memory clipboard history
│   │   ├── remote_input.py     # Touchpad, typing, and key chords
│   │   ├── notifications_mirror.py # Desktop notifications monitor & dismiss/mute
│   │   ├── open_url.py         # Open link in PC browser
│   │   ├── wallpaper.py        # Set desktop wallpaper image
│   │   ├── wake.py             # Wake-on-LAN magic packets
│   │   └── transfer.py         # File transfer & downloads
│   ├── ui/
│   │   ├── index.html          # Single-file web remote UI
│   │   ├── sw.js               # Service worker (offline fallback, Web Push, share)
│   │   ├── manifest.webmanifest# PWA web manifest with app shortcuts
│   │   └── *.png               # PWA icons (192, 512, maskable, apple-touch)
├── gnome-extension/gnomespeak@local/
│   ├── metadata.json           # Extension metadata (v4 / 3.4.0)
│   ├── extension.js            # D-Bus window, workspace, pointer & key interface
├── Makefile                    # make dev / setup / test / doctor
├── scripts/envreport.py        # backs `make env`
├── scripts/setup-system.sh     # system packages by capability
├── pyproject.toml
├── commands.toml.example
├── README.md
├── ARCHITECTURE.md
├── CHANGELOG.md
└── tests/                      # pytest suite (854 tests)
```

## Development

Everything goes through `make`. Each target sets the environment up first if it
needs to, so there is no activate step and no ordering to remember.

| Target | What it does |
|--------|--------------|
| `make dev` | Set up if needed, then start the server. **Start here.** |
| `make setup` | System packages, `venv/`, Python deps, GNOME extension, git hooks. Idempotent; the Python step re-runs only when `pyproject.toml` changes. |
| `make system` | Just the system packages (asks for sudo only if something is missing). |
| `make extension` | Just the GNOME extension — installs or repairs it, no-op when healthy. |
| `make test` | Run the pytest suite (`make test ARGS="-x -k mpris"`). |
| `make doctor` | Preflight checks — D-Bus, PipeWire, port, extension, config. |
| `make status` / `make commands` / `make apps` | CLI passthroughs. |
| `make env` | Print the resolved interpreter and which optional deps it can see. |
| `make link` / `make unlink` | Add/remove `~/.local/bin/vt`. |
| `make deps` | Force a dependency reinstall. |
| `make clean` | Drop caches and build artifacts (keeps the venv). |
| `make reset` | Delete the venv and rebuild from scratch (~10s). |

Options apply to `make dev`: `HOST=0.0.0.0`, `PORT=9000`, `NO_TOKEN=1`, `OPEN=1`,
and `ARGS="..."` for anything else. `SKIP_SYSTEM=1` leaves system packages
alone; `YES=1` never prompts (for CI, which has nobody to type a sudo
password).

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

MIT (see [LICENSE](LICENSE))

## Acknowledgments

- Built on MPRIS (freedesktop.org), PipeWire (pipewire.org), GNOME Shell, and aiohttp.
- Inspired by the original VoiceTalk v1–v2, refactored for simplicity and Linux-native APIs.
