# Changelog

## [Unreleased]

## [3.4.0] — 2026-09-03

### Added
- **A live channel** (`vt/live.py`, `GET /ws`) — the phone holds a WebSocket
  and the server pushes only the targets that changed, so a quiet PC costs no
  traffic at all instead of a full snapshot every second. The 1 Hz poll remains
  the fallback for a browser that cannot hold a socket, and `/api/state` still
  serves the same snapshot. Authentication is a single-use ticket from
  `POST /api/ws-ticket`, because a WebSocket handshake carries no headers and a
  device secret must never travel in a URL. Pointer and scroll deltas ride the
  socket too, replacing a POST every 50 ms. An action now also wakes the
  collector, so a change the phone asked for comes back in a median 253 ms
  (12 samples on this machine after all of the sources below were added; worst
  372, and two of the twelve over the 300 ms the roadmap asked for) rather than
  at the end of the next second.
- **Starts with the desktop session** (`vt install-service`, `vt/service.py`) —
  a systemd *user* unit bound to `graphical-session.target`, because every
  source vt reads (MPRIS, the Shell extension, the session bus, PipeWire) lives
  in the session and does not exist outside it. The unit requires pairing,
  since a service prints its banner where nobody reads it; `vt pair` mints a
  code from the terminal. `vt uninstall-service` leaves nothing behind, and
  `vt doctor` reports the unit's state.
- **Installable web app and Android share target** (`vt/ui/manifest.webmanifest`,
  `vt/ui/sw.js`) — a home-screen icon, a fullscreen page, an offline "PC
  unreachable" screen instead of a browser error, and a GnomeSpeak entry in
  Android's share sheet. A share POST carries no credential, so the service
  worker parks the payload and the page — which holds the credential — uploads
  it through the existing endpoints. Still nothing installed from a store.
- **Per-application volume** (`vt/sources/audio.py`) — every stream `wpctl`
  lists becomes its own slider and mute, so the game goes down without the call
  going with it. A stream that ends mid-session drops out of the snapshot.
- **Screenshot on demand** (`vt/sources/screenshot.py`, `GET /api/screenshot`) —
  one still frame through `org.freedesktop.portal.Screenshot`, on request only,
  deleted from disk the moment it has been served. Declining on the PC reads as
  "you declined", not as a D-Bus error. Explicitly not a stream.
- **Album art and a live scrubber** (`vt/sources/art.py`, `GET /api/art`) — art
  is served by a key some player published rather than by a URL the phone
  names, size-capped, and checked to be an actual image; the position bar
  interpolates locally so it moves smoothly on one message per change.
- **Notifications arrive rather than being found** — the mirror hands each new
  notification to the live channel, which pushes it to every open phone; the
  three-second poll on that screen is now only the fallback for a phone with no
  socket. A push waits 0.3 s first, because the daemon's reply carries the id
  that makes "Dismiss" work and it lands just after the call the mirror read.
- **The extension travels with the wheel** — `pip install gnomespeak` now
  carries `gnome-extension/gnomespeak@local/` as data, and
  `vt install-extension` finds it there when there is no checkout, so getting
  started no longer means `git clone`. A checkout still wins over an installed
  copy, so a developer always installs the tree they are editing.
- **Notifications can be dismissed** — the mirror now watches the notification
  daemon's replies as well as the calls, so it keeps the id that
  `CloseNotification` needs, and stops counting GNOME Shell's forwarded copy as
  a second notification. Activating an action stays out of reach: an app
  listens for `ActionInvoked` from the daemon's own bus name, and vt is not the
  daemon.
- **Ring this PC, and the phone's battery on the PC** (`vt/sources/ring.py`) —
  an alert sound and a banner on demand, and a phone that reports its own
  battery over the live channel appears as a target beside the PC's. The ring
  runs on its own thread and can be stopped from the phone (`system:ring stop`,
  or `{type:"ring_stop"}` on the live channel); the button on the phone says
  "Stop ringing" for exactly as long as the PC is making noise, and a ring
  nobody stops falls silent after a minute.
- **`vt package-extension`** (`vt/package.py`) — builds the archive
  extensions.gnome.org accepts, and refuses one it would reject: a string
  `version`, a missing `url`, or a `session-modes` that claims the lock screen.
  The zip carries the store uuid while the checkout keeps `gnomespeak@local`,
  so publishing does not rename anyone's working install. `vt/shell.py` now
  accepts either uuid, in the user's extensions directory or a system-wide one,
  and says so when both are installed -- they claim the same D-Bus name, and
  the loser of that race looks like a broken extension rather than a second one.
- **An unreachable PC is marked in the switcher** (`POST /api/probe`) — the
  phone cannot ask another origin whether it is up (the browser refuses the
  cross-origin request, and the page's own CSP says `connect-src 'self'`), so
  the PC asks and answers yes or no. Never a status code, a header or a body:
  the answer is what a switcher needs to grey out a machine and nothing that
  would make the desktop a readable port scanner. The page says the check came
  from the PC, because a machine the PC can see may still be out of the
  phone's reach.
- **The security log on the phone** (`GET /api/audit`) — every action and every
  rejection, with rejections rendered as prominently as actions.
- **A switcher for more than one PC** — saved machines live in the page, and
  switching is navigation, so each PC keeps its own pairing and no new trust
  relationship is created between them.

- **Open a link on the PC** (`POST /api/open`, `vt/sources/open_url.py`) — the
  phone's clipboard screen grows an "Open on the PC" button for anything that
  is a link, and a page shared from Android's share sheet opens by itself. Only
  `http` and `https`: a desktop's URL handlers reach far past the browser, and
  the link arrives as free text from a phone that may be passing on something
  it was sent.
- **Choose where sound goes** (`audio:sink`, `audio:source`) — every output and
  input `wpctl` lists, with the current one as the row's status and the others
  as buttons. wpctl exits 0 for a device WirePlumber then declines to use, so
  the switch is confirmed by reading the default back: an HDMI socket with no
  cable in it now says "the PC would not switch to it" instead of claiming the
  sound moved.
- **What the machine is doing** (`system:machine`, `vt/sources/monitor.py`) —
  numbers re-read every five seconds and rounded to the nearest five per cent,
  because a row that changed every second would be a patch to every phone every
  second -- the 1 Hz poll again, wearing a socket. An idle PC sends two
  messages in twelve seconds.
  CPU, memory, disk, uptime and the warmest sensor, as one row. The CPU figure
  is left off the first tick rather than reported as psutil's since-boot
  average, and the temperature is read from the thermal zones on a slow cache
  because `psutil.sensors_temperatures()` costs 200 ms.
- **The keys the focused app answers to** (`vt/sources/keypads.py`) — a pad for
  the browser, VLC, mpv, a presentation, a terminal, an editor or a file
  manager, chosen by the focused window. The phone sends the *name* of a key
  and the table decides the chord, so a request that is not in it reaches
  nothing; an application with no entry gets no pad rather than a guessed one.
- **Bluetooth device battery** — BlueZ publishes it on the same object the
  device list already reads, so connected headphones now say how much they have
  left.
- **Recently copied on the PC** (`GET/DELETE /api/clipboard/history`) — the last
  couple of dozen clips, kept in memory only, started by opening the clipboard
  screen, and cleared by one button because a clipboard sometimes holds a
  password.
- **What works** (`GET /api/diagnostics`, `vt/diagnostics.py`) — `vt doctor` as
  a screen on the phone, because the person debugging is holding the phone and
  the PC is across the room. Every row says what is true, what it costs and
  what to do.
- **Sleep timers** (`vt/schedule.py`) — "Suspend in 15/30/60 min" on the power
  row, a row of its own per pending timer with a cancel button, and jobs that
  live in memory because a timer that survived a restart would fire into a
  desktop that has been doing something else for an hour.
- **Guest devices and per-device scopes** (`vt pair --guest --hours N`) —
  a guest keeps the state, the media controls and the socket; reading the
  clipboard, reading or dismissing notifications, listing files, diagnostics,
  probes, wake packets and `/api/pair/self` all answer 403. That last one
  mattered most: without it a guest could have minted itself a full,
  never-expiring credential in one call. a
  paired phone can be limited to media, and given a credential that expires by
  itself. A refusal is 403 rather than 401, because 401 makes the page throw
  its credential away and ask to pair again. Every phone paired before this is
  unchanged: no scope stored means every capability.
- **A picture from the phone as the wallpaper** (`POST /api/files/wallpaper`) —
  the share sheet already lands a photo in the transfer folder; this is the tap
  that puts it on the desktop. Both the light and dark keys are set, and the
  file has to be a real image rather than something merely named like one.
- **Pinned targets and home-screen quick actions** — four things get used every
  evening and the rest almost never, so a target can be pinned to the top of
  the page; and the installed icon's long-press menu opens the touchpad,
  clipboard, screenshot or notifications directly.
- **Dictate to the PC** — the phone already has speech recognition and the
  microphone permission, and the PC already types into the focused window. No
  audio ever reaches the PC, only the text; the button is absent on a browser
  without speech rather than present and inert.

- **Wake another PC** (`POST /api/wake`, `vt wake`) — the switcher already knew
  about the other machines and already asked whether they answer; a machine
  that is awake can now send the magic packet to one that is not, so "not
  answering" becomes "wake it". Nothing acknowledges a wake packet, so the
  answer says "sent" and the row re-checks a few seconds later.
- **Join a saved Wi-Fi network** — the Wi-Fi row shows the network it is on and
  offers the other saved ones. The list is cached because it changes about once
  a month and the snapshot is collected once a second, and a name the phone was
  holding from an older snapshot is checked against NetworkManager's own list
  before `nmcli` sees it.
- **The PC says when the phone is nearly flat** (`vt/notify.py`) — a banner on
  the PC when a connected phone crosses 15% and is not charging, once per
  crossing rather than once per report. The phone's own warning is easy to miss
  from across the room, which is the whole reason this direction exists.

- **Removable drives** (`vt/sources/disks.py`) — a row per mounted removable
  drive with an Eject button, built from the kernel's own removable flag so
  twenty snap loopbacks and the internal disk stay out of it. Ejecting
  unmounts and then powers the drive down; a drive that unmounted but would not
  power off is reported as safe to remove rather than as a failure.
- **Battery alerts in both directions** — the PC raises a banner when a
  connected phone crosses 15% while discharging, and pushes an alert to the
  phone when its own battery does the same. Both fire on the crossing, not on
  the state: a machine sitting at 9% reports the same number every second.

- **Mute one app's notifications** (`POST /api/notifications/mute`) — press and
  hold a notification on the phone and that app stops arriving, along with the
  backlog it just made. In memory and for this session only: it is "not
  tonight", not a settings screen, and it drops the app before the socket
  rather than hiding rows after them.

- **Notifications reach a phone whose page is closed** (`vt/push.py`,
  `/api/push/*`) — Web Push, which is the browser's own answer to the one thing
  an app could do that this could not. The page subscribes, the PC posts to the
  endpoint the browser hands back, and the service worker wakes up to show it.
  Still no app and no store.

  The encryption (RFC 8291) and the authorization (RFC 8292) are implemented
  here against `cryptography` rather than by adding a push library: the one
  available today pins a newer `cryptography` than other tools accept, and the
  two specifications together are about a hundred lines. RFC 8291's own worked
  example is in the test suite, so the bytes are checked against the standard
  rather than against themselves, and one test posts a real signed, encrypted
  request at a local stand-in for a push service.

  A phone that is looking at the page is skipped -- it already got the
  notification over the socket -- and a subscription the push service calls
  gone is forgotten rather than retried. `pip install gnomespeak[push]`; without
  it, `vt doctor` and the phone's own "What works" screen say so.

- **Macros** (`commands.toml`) — a command may carry `steps` instead of `run`:
  a list of the same target-and-action pairs the phone sends, with optional
  waits between them. "Movie mode" is do-not-disturb, night light, and the
  volume down, on one button. Steps cannot name a program, so the argv boundary
  that keeps this file away from a shell does not move, and a macro stops at
  the first step that fails rather than reporting success for half of itself.

- **HTTPS on the LAN** (`vt serve --tls`, `vt/tls.py`) — off the LAN everything
  already rode the tunnel's TLS; on the LAN the token travelled in a header
  over plain HTTP, where anyone on the same Wi-Fi could read it. The PC now
  makes its own certificate covering its LAN address, hostname and loopback,
  keeps the key `0600`, and prints the SHA-256 fingerprint at startup, because
  a self-signed certificate is only as good as the person checking it. Opt-in,
  since the first minute is worse (the phone warns) and every hour after it is
  better. `vt pair` probes the port and hands out an `https://` link when the
  server is listening for one, so a QR code cannot carry the wrong scheme.

### Changed
- **The snapshot is collected in about 75 ms rather than 230** (`vt/procs.py`,
  `vt/state.py`) — `wpctl get-volume` and `gsettings get` are processes that
  spend their whole lives waiting, and the collector ran them one after
  another; they now wait together. The two sources that touch no D-Bus (the
  `/proc` app scan and the `wpctl` audio rows) run on their own threads while
  the D-Bus sources, which share one connection and must stay serialized, take
  their turn; both are spliced back at their own positions. The settle after an
  action is 0.10 s rather than 0.15 s. All of it is the live channel's latency
  budget.
- **The README leads with the thesis** rather than the feature list, which is
  what the roadmap's release gate asks for.

### Fixed
- **Album art and screenshots rendered as the browser's broken-image icon.**
  Both are fetched with a credential and handed to the `<img>` as an object
  URL, because an `<img src>` cannot carry a header and the credential must not
  travel in a URL — but the page's own CSP said `img-src 'self' data:`, and a
  `blob:` URL is neither. The policy now names `blob:`. Belt and braces: an
  image that still fails to load removes itself rather than leaving a
  placeholder, since a broken icon says "this is wrong" about a player that is
  playing perfectly well.
- **`make dev` no longer looks like it contradicts the setup it just ran.**
  "Installed" and "not loaded" were both true and neither said why: a GNOME
  Shell extension only loads at session start. `vt/shell.py` now reports disk,
  dconf and the running shell separately (`status()`, `load_state()`), so setup
  says "installed — log out and back in to load it", the server banner names
  the fix that actually applies, and an extension that failed to load is no
  longer told to reinstall itself.
- **Window control on COSMIC** (`sources/cosmic_windows.py`) — Focus,
  Minimize, Maximize, and Close now work under COSMIC (System76's compositor)
  without the GNOME extension, by talking its own
  `ext-foreign-toplevel-list-v1` / `cosmic-toplevel-info-unstable-v1` /
  `cosmic-toplevel-management-unstable-v1` Wayland protocols directly.
  New optional dependency: `pip install gnomespeak[wayland]` (a pure wheel,
  no system package needed, unlike `dbus-python`). Workspaces still need the
  GNOME extension and are not available on this backend yet. `vt doctor`
  reports it under "COSMIC windows".
- **Keystroke injection on COSMIC** (`sources/cosmic_input.py`) — Firefox
  tab-switching, per-tab close, and YouTube playback keys (fullscreen, close
  tab) now work on COSMIC too, the same actions the GNOME extension's
  `SendKeys` provides there. Delivered through
  `zwp_virtual_keyboard_manager_v1`, a standard wlroots-family protocol, with
  a bundled static XKB keymap rather than a new `libxkbcommon` dependency.
  See `COSMIC_INPUT_PARITY.md` for the design and the Phase 0 spike that
  confirmed an ordinary client is allowed to do this here.
- **`make dev` sets the machine up by itself.** It now installs missing system
  packages (`scripts/setup-system.sh`, which asks for sudo only when something
  is actually missing and supports apt, dnf, pacman and zypper) and installs or
  repairs the GNOME extension (`vt install-extension --if-needed`) before
  starting the server. Both steps are idempotent, cost milliseconds when there
  is nothing to do, and cannot fail the run: an unknown distro, no sudo, or no
  GNOME at all still leaves a server that starts, with each unavailable feature
  reporting its own absence. `SKIP_SYSTEM=1` opts out; `YES=1` never prompts.
- **The startup banner says when the extension is not loaded**, once, instead of
  leaving window and touchpad control to fail one tap at a time.
- **Touchpad, keyboard and presentation remote** — the phone drives the pointer
  (drag to move, tap to click, two fingers to scroll, two-finger tap to
  right-click), types literal text into whatever has focus, and sends key
  chords, including a Prev/Next/F5/Escape row for slides. New extension
  methods: `Pointer`, `Click`, `Scroll`, `TypeText`, `Keys`. Under Wayland only
  the compositor may synthesize input, so this is the only route that works;
  `POST /api/input` carries it, outside `/api/do` because a trackpad has no
  target and sends about twenty deltas a second.
- **Clipboard sync** — read the PC's clipboard on the phone and push text back,
  through `wl-clipboard` on Wayland or `xclip`/`xsel` on X11
  (`GET`/`POST /api/clipboard`).
- **Notification mirroring** — desktop notifications appear on the phone as
  they arrive, read by monitoring the session bus through `dbus-monitor`
  (`GET /api/notifications`). Read-only by design.
- **File transfer** — send a file from the phone to `~/Downloads/GnomeSpeak`,
  open it there with one tap, or pull one back (`POST /api/upload`,
  `GET /api/files`, `GET /api/files/<name>`, `POST /api/files/open`). Uploads
  stream to disk with a 100 MB cap; names are reduced to something that cannot
  express a path, and downloads are resolved against the directory's real path
  so a symlink inside it cannot lead out.
- **Wayland YouTube playback keys** — play/pause, 10s seek, volume, mute,
  **fullscreen** and close tab now work under Wayland. They are delivered
  through the GNOME extension or (on COSMIC) `sources/cosmic_input.py` --
  only the compositor may synthesise input under Wayland -- instead of
  `xdotool`, which stays as a fallback for non-GNOME, non-COSMIC X11 sessions.
  The tab is found by window title, or through Firefox's session store when
  the video is parked in a background tab.
- **Window state and workspaces** — minimize, restore, maximize, unmaximize,
  move a window to another workspace, and switch workspaces from the phone.
  New extension methods: `Minimize`, `Unminimize`, `Maximize`, `Unmaximize`,
  `MoveToWorkspace`, `SwitchWorkspace`, `Workspaces`.
- **Bluetooth** (`sources/bluetooth.py`) — turn the radio on and off, and
  connect or disconnect paired devices, over BlueZ on the system bus. Pairing
  a *new* device is deliberately out of scope: it needs an agent to answer a
  PIN prompt that the phone cannot see.
- **System control** (`sources/system.py`) — lock, suspend, restart, shut down
  (the last two `confirm` actions), screen brightness as a slider and steps,
  do-not-disturb, and battery charge/state/time-remaining.
- **Streaming shortcuts** (`sources/streaming.py`) — one tap for Netflix,
  Spotify, Prime Video, Disney+, JioHotstar, Twitch, Max and YouTube. Prefers
  an installed desktop app, falls back to the browser, and says which it will
  do. Overridable in `~/.config/gnomespeak/streaming.toml`.
- **Steam games** (`sources/steam.py`) — installed games read from Steam's own
  library manifests (including libraries on other drives), filtered to what is
  fully installed and not a runtime, launched via `steam://rungameid/`. They
  appear in the existing app search rather than the 1 Hz snapshot.
- **"Up next"** — `GET /api/youtube/related` and a button on the YouTube
  screen return what to watch after the video already playing, with no need to
  say which one that is. Falls back to searching the current title when
  yt-dlp exposes no related list.
- **`vt doctor` detects a stale extension** — a Shell extension only reloads on
  log out, so an updated checkout can sit on disk while the old build keeps
  serving. Doctor now probes for the newest method and says to log out.

### Fixed
- **`vt doctor` always reported the GNOME extension missing.** The rename to
  GnomeSpeak updated the bus name in `vt/cli.py` alone, leaving doctor probing
  `org.gnome.Shell.Extensions.GnomeSpeak` while everything else — including the
  extension — used `…Extensions.VoiceTalk`. The bus name, object path, uuid and
  expected method set now live once in `vt/shell.py`.
- **A pre-rename extension install was left dangling and silent.** An install
  from before the rename is a `voicetalk@local` symlink into a directory that no
  longer exists; GNOME Shell drops such an extension without a word, taking
  window, workspace and browser-tab control with it. `vt install-extension`
  removes it, drops it from `org.gnome.shell enabled-extensions`, and repairs a
  dangling `gnomespeak@local` symlink instead of calling it "already installed".
- **A freshly installed extension could not be enabled.** The running shell only
  scans the extensions directory at session start, so `gnome-extensions enable`
  answered "does not exist" — and the printed fallback was that same command.
  The uuid is written to the dconf enabled list instead, which takes effect at
  the next login.
- **Extension version skew is now one line, not one failure per action.**
  `vt doctor` introspects the live extension and names the features a stale
  build cannot serve.
- **A missing extension is visible on the phone.** `system:extension` is a
  snapshot target, shown once at the top of the System tab and on the touchpad
  screen, rather than four features failing separately.
- **Clipboard writes reported a timeout on success.** `wl-copy` forks a process
  that owns the selection and inherited the stderr pipe, so `subprocess.run`
  waited out its full timeout on a copy that had already worked.
- **Battery time on a full battery** — UPower keeps reporting a `TimeToEmpty`
  when the battery is full (8391600 seconds on the development machine), which
  rendered as "100% · full · 2331h left". Only a charging or discharging
  battery gets a countdown now.

## [3.1.0] — 2026-08-23

### Added
- **Cloudflare Tunnel** — `make dev` starts a quick tunnel by default, giving
  a `*.trycloudflare.com` URL accessible from anywhere. No port forwarding,
  no router config, no Cloudflare account needed. `--tunnel` flag on
  `vt serve`; `TUNNEL=0` disables it.
- **Device pairing** — off-network callers must present a paired-device
  credential; the startup token is only accepted on the LAN. Pair a phone
  with `vt pair` or the QR code printed at startup. Max 32 devices.
- **`vt pair`** — issue a one-time pairing code with link and QR. Supports
  `--url`, `--port`, `--minutes`, `--label`.
- **`vt devices`** — list paired devices or revoke access (`--revoke ID`,
  `--revoke-all`).
- **`vt audit`** — show the recent security log (`-n N`, `--rejects`).
- **Security headers** — CSP (nonce-based), HSTS, X-Frame-Options DENY,
  nosniff, no-referrer, COOP on every response.
- **Rate limiting** — 5 failed auth attempts per IP triggers a 15-minute
  lockout. Pairing attempts rate-limited globally (30/hour).
- **Audit log** — every authenticated action and rejected attempt recorded
  in `~/.local/state/gnomespeak/audit.log` as JSONL.
- **New API endpoints** — `/api/session`, `/api/pair`, `/api/pair/self`,
  `/api/devices`, `/api/devices/revoke`.

### Changed
- **`make dev`** — now starts a Cloudflare tunnel by default.
- **Server banner** — shows tunnel URL, pairing code, and device count.
- **Token auth** — LAN callers use token; remote callers must pair a device.
- **`--no-token`** — disables token for LAN callers only; remote callers
  still need a paired device.

## [3.0.0] — 2026-08-23

Complete rewrite. Previously a Windows-only Python server with a
CustomTkinter GUI plus a React Native Android app; now a Linux CLI
(`vt`) that serves a self-contained web UI to any browser on the LAN.

### Removed
- **The entire v2 stack** — `client/` (React Native app and Gradle build),
  `server/` (Windows GUI, LLM intent parser, PowerShell/pyautogui/pycaw/
  Playwright handlers, Fernet config), and the OpenSpec specs describing them.
  All of it stays recoverable in git history.
- **The LLM agent loop** — v3 performs deterministic, pre-configured actions
  only. No provider keys, no prompt, no tool dispatcher.

### Added
- **`vt` CLI** — `serve`, `status`, `do`, `apps`, `commands`, `doctor`, and
  `install-extension`.
- **Web UI** — one self-contained `vt/ui/index.html`, no build step. Open the
  printed URL on a phone; it polls `/api/state` over HTTP and auto-reconnects.
- **Token auth** — a 22-char random token is generated per run and required on
  every `/api/*` request.
- **MPRIS players** — play/pause, seek, and volume, gated on the capabilities
  each player actually reports (`CanPause`, `CanSeek`, …).
- **System audio** — volume and mute via `wpctl` (PipeWire).
- **Installed apps** — `GET /api/apps` lists every `.desktop` entry as a
  launchable target; the UI filters as you type, and `launcher:<desktop-id>` +
  `launch` works from the UI and from `vt do`. Apps need not already be running.
- **Window control** — an optional GNOME extension exposes stable window IDs
  over D-Bus for `List`/`Focus`/`Close`; absent it, vt degrades gracefully.
- **YouTube search** — `GET /api/youtube?q=` searches via `yt-dlp` and returns
  title, channel, and duration. Tap a result to open it.
- **YouTube playback control** — appears only on X11, where `xdotool` and
  `wmctrl` can synthesise keystrokes.
- **Pre-configured commands** — `~/.config/gnomespeak/commands.toml`, where `run`
  is always an argv list and never a shell string, validated on startup.
- **`vt allow-autoplay`** — sets `media.autoplay.default` in the Firefox
  profile's `user.js` (the same setting as Settings → Privacy & Security →
  Autoplay → Allow Audio and Video), with `--status`, `--revert`, and
  `--restart`. Reverting says so plainly when Firefox has already copied the
  value into its own `prefs.js`, where vt cannot take it back.
- **`Makefile`** — one way to run the project. `make dev` builds the venv if it
  is missing and starts the server through `venv/bin/vt` by absolute path, so a
  VS Code terminal, a plain shell, and a different working directory all produce
  the same result; `VIRTUAL_ENV`, `PYTHONPATH`, and `PYTHONHOME` from the
  calling shell are dropped rather than inherited. Also `setup`, `test`,
  `doctor`, `env` (prints the resolved interpreter and which optional deps it
  can see), `link` (puts `vt` on `$PATH`), `clean`, and `reset`.

### Fixed
- **A video opened from the phone that never started playing** — tapping a
  search result ran `xdg-open` and reported "Playing video", but Firefox blocks
  autoplay of audible media by default, so the tab loaded paused. Nothing
  played, no MPRIS player was published, and the video never appeared under
  Players; the only way to find out was to walk to the PC and press play, which
  is the one thing a phone remote exists to avoid. vt now reads the browser's
  autoplay policy (`sources/browser_autoplay.py`), says which of the two
  actually happened, and offers the fix: `vt allow-autoplay` on the PC, or an
  "Allow autoplay" button on the YouTube screen that sets the pref, restarts
  Firefox, and reopens the video that failed — so the tap completes itself.
  `vt doctor` reports the policy under `Autoplay`.
- **YouTube search returning nothing** — `yt-dlp` present in a venv but not to
  the running interpreter now reports "yt-dlp is not available to this
  interpreter" with install instructions, instead of an empty result list.
- **Playback controls that silently did nothing** — keystroke controls are
  hidden on Wayland, which forbids client-to-client input synthesis, and the UI
  points at the MPRIS player instead.
- **Search box losing focus while typing** — the 1 Hz state poll re-rendered the
  view underneath the user; a view signature now suppresses no-op re-renders.
- **D-Bus log flood under snap confinement** — every proxy is built with
  `introspect=False`, so a player refusing `Introspect` no longer logs an error
  per player per second. `Seek` passes an explicit `dbus.Int64`, which
  introspection used to supply.
- **Media players silently missing** — an `AccessDenied` from a snap-packaged
  player is recognised and reported once, naming the AppArmor confinement that
  caused it, instead of looking identical to "nothing is playing".
- **Flatpak apps collapsing onto one entry** — `Exec=/usr/bin/flatpak run ...`
  was indexed under `flatpak`, so the first flatpak app scanned shadowed all
  the others.
- **Newly installed apps invisible** — the `.desktop` scan was cached for the
  life of the process; it now refreshes every 60 seconds.
- **Seek buttons that broke the player they controlled** — Firefox reports
  `CanSeek=true` but implements neither `Seek` nor `SetPosition`. Either call
  returned without error, playback did not move, and the player then reported
  `Position=0` with no `mpris:length` for the rest of the track, so the progress
  readout never came back. Seek is now withheld from players known to
  misreport it, and the target says why instead of leaving a silent gap.
  Players that do implement seeking (VLC, mpv, Spotify) are unaffected.

### Requirements
- Linux with GNOME Shell 45+, systemd, and PipeWire/ALSA; Python 3.11+.
- Wayland and X11 are both supported; the keystroke-based YouTube controls are
  X11-only.

## [2.2.0] — 2026-07-19

### Added
- **Deterministic-first command routing** — Common browser, YouTube, volume, Bluetooth, app, file, and email phrases now bypass the LLM and execute through typed internal commands first.
- **Deterministic command sequences** — Phrases such as `set volume to 100% and then open YouTube and search for ...` now execute as ordered multi-step command sequences.
- **Per-request client routing tests** — Added client Jest coverage for WebSocket routing, conversation request handling, HomeScreen send-failure behavior, and RecordButton lifecycle cleanup.
- **Server diagnostics bundle** — `server/diagnostics.py` creates a support bundle with version info, config paths, dependency versions, connectivity checks, and sanitized logs.
- **Browser runtime bootstrap** — The Windows GUI can install the Playwright Chromium runtime on demand, and browser automation can auto-bootstrap it once when missing.

### Changed
- **Browser preference order** — Simple `open/search/go to` browser actions now prefer the system default browser. Playwright is reserved for automation flows like opening and trying to autoplay a YouTube video.
- **Windows packaged server** — `windows_gui.py` is the supported desktop entry point, the packaged app is single-instance guarded, and the PyInstaller spec now builds a GUI app without a console window.
- **OpenCode default model** — Switched to the documented free Zen model `deepseek-v4-flash-free`.
- **OpenRouter default model** — Switched to `nvidia/nemotron-nano-9b-v2:free`.
- **Android release pipeline** — Release builds now require explicit signing credentials, enable shrinking/optimization, and exclude Flipper from release artifacts.
- **Client speech handling** — Android STT now uses the device locale and forwards up to 5 alternative transcripts to the server for deterministic matching.
- **Session history** — Reduced stored session history from 100 to 30 messages with tool-result truncation.

### Fixed
- **Request correlation** — GUI server path, client streams, and clarification answers now consistently propagate `request_id` so overlapping requests stay isolated.
- **Volume control** — Absolute volume commands now bypass the LLM and use direct pycaw endpoint volume control instead of repeated step-up key events.
- **Browser command phrasing** — Added deterministic handling for natural phrases like `open youtube and search for ...`, `go to youtube and search ...`, and `play the first video` after a YouTube search.
- **Browser fallback behavior** — When `yt-dlp` cannot find a direct match, YouTube search fallback opens in the default browser instead of a Playwright `about:blank`/automation path.
- **Windows GUI lifecycle** — Fixed Start/Stop/Settings button wiring, request-aware logging, rotating file logs, log export, diagnostics export, and recovery flows for encrypted config.
- **Client stuck-listening regression** — Final deterministic results now clear listening state and still render even if request tracking was lost.
- **Config durability** — `%APPDATA%\VoiceTalk\config.json` is now the real relative default, `.master.bak` recovery is preserved, and config/master writes are process-locked and atomic.
- **Truthfulness gaps** — Removed unsupported Bluetooth connect/disconnect claims, corrected autoplay behavior messaging, and documented the actual packaged browser/runtime behavior.

## [2.1.0] — 2026-07-15

### Added
- **Streaming responses** — `parse_stream()` async generator yields sentence-level chunks via `stream_chunk`/`stream_result` WebSocket messages. Client displays text incrementally in all 3 modes (voice, conversation, chat).
- **Safety system** — `SafetyChecker` intercepts destructive tools (delete, move, copy, create_file overwrite) and prompts user for confirmation via existing ask_user flow.
- **Environment model** — `EnvironmentModel` caches desktop files, installed apps (PowerShell `Get-StartApps`), and recently accessed folders. Injected into system prompt for AI context. Lazy refresh on access + 15-min periodic refresh.
- **Ollama provider** — 5th AI provider: fully local inference via `localhost:11434/v1`. No data leaves the machine. Works with existing `AsyncOpenAI` client.
- **PowerShell app launcher** — `app_launcher.py` now uses `Get-StartApps` PowerShell cmdlet for faster, more reliable app discovery. Falls back to Start Menu scan.
- **Random master password** — First run generates a random 32-char password via `secrets.token_urlsafe(24)` stored in `.master` file. No more hardcoded `"voicetalk"` password.
- **125 unit tests** — Test suite covering SafetyChecker, EnvironmentModel, FileOps, AppLauncher, IntentParser, CommandExecutor, and MediaControl.

### Changed
- **Streaming architecture** — Server now streams AI responses incrementally instead of waiting for full completion. Sentence-level chunking (max 500 chars) via regex.
- **`config.py`** — Removed `DEFAULT_MASTER_PASSWORD` constant. `auto_unlock()` now reads from `.master` file or generates a new random password.
- **`server.py`** — `setup()` takes no arguments; calls `config.auto_unlock()`.
- **`command_executor.py`** — Integrates `SafetyChecker` and `EnvironmentModel`. File operations refresh folder caches.
- **`intent_parser.py`** — Added `parse_stream()` alongside existing `parse()`. Gemini streaming appends user message outside tool loop. `full_response` accumulates across agent iterations.
- **`windows_gui.py`** — Removed hardcoded password from `ServerThread` and `_start_server()`.
- **`windows_app.py`** — Uses `server.setup()` without password argument.
- **`.gitignore`** — `server/config.json` now properly gitignored (was commented out).
- **Browser control** — All navigation (including general browsing) now uses Playwright instead of `webbrowser.open()`.

### Fixed
- **Dead regex prefixes** — `"open folder X"` and `"open file X"` were unreachable due to generic `"open "` prefix matching first. Reordered specific prefixes before generic.
- **PowerShell injection** — App names now escaped with single-quote doubling before embedding in PS commands.
- **Session storage in streaming** — `_store_session_stream()` now correctly stores both user and assistant messages.
- **`full_response` accumulation** — Moved initialization before agent loop so text accumulates across iterations.
- **`streamingChatMsgIdRef` read order** — Ref is now captured before being cleared in `onStreamResult`.

## [2.0.0] — 2026-07-11

### Added
- **Playwright browser automation** — Async Chromium for YouTube: navigate, auto-play via JS, single-tab execution
- **yt-dlp integration** — Reliable YouTube search replacing fragile HTML scraping
- **pyautogui media control** — Keyboard simulation for play/pause, skip, volume, fullscreen, etc.
- **4 AI providers** — OpenAI, Gemini (google-genai), OpenCode, OpenRouter (free models)
- **Gemini native function calling** — Agent loop with FunctionDeclaration/Schema (replaces text JSON parsing)
- **Session context** — Multi-turn conversations remembered within a session (max 50 sessions, 100 msgs each)
- **3 interaction modes** — Voice (push-to-talk), Conversation (continuous STT), Chat (text input)
- **Chat mode UI** — TextInput + Send button with shared session context
- **Conversation mode** — Continuous listening with 1.5s silence auto-send, session_id protocol
- **ConversationThread component** — FlatList chat bubbles with live transcription
- **Pipeline status bar** — Real-time step tracking (listening → processing → sending → waiting → done)
- **Autonomy system prompt** — AI never asks user to click; English-only; error recovery; task decomposition
- **Auto-unlock config** — Server starts without manual password entry
- **URL normalization** — Handles ws://, wss://, http://, bare hostnames
- **OpenSpec specs** — 21 capability specifications including agent-autonomy, keyboard-simulation

### Changed
- **Browser handler split** — YouTube uses Playwright (auto-play), general browsing uses webbrowser (default browser)
- **command_executor.py** — Fully async; all browser/yt calls use await
- **intent_parser.py** — All executor calls async; system prompt rewritten for full PC autonomy
- **System prompt** — "You control the PC COMPLETELY — you NEVER ask the user to click"
- **YouTube rules** — yt_play handles search + navigate + play in one call; no need for media_control after
- **Tool count** — Expanded from 17 to 23 tools
- **UI redesign** — Flat design: bold colors, no shadows, no pastels. Primary #DC2626, Accent #2563EB

### Fixed
- **Gemini session context** — System prompt now injected at start of every session (was lost on continuation)
- **Gemini single-shot** — Now has agent loop (up to 5 iterations) with native function calling
- **openrouterKey missing dependency** — WebSocket now reconnects when only OpenRouter key is set
- **URL malformed** — Entering `ws://...` no longer creates `ws://ws://...`
- **RecordButton double-fire** — finalize() guarded against duplicate calls
- **Voice.destroy() not awaited** — Fixed race condition on rapid re-record
- **ConversationThread re-renders** — data array wrapped in useMemo (was recreated every render)
- **google.genai import crash** — Wrapped in try/except ImportError
- **Session memory leak** — Added MAX_SESSIONS=50 and MAX_SESSION_MESSAGES=100 with LRU eviction
- **set_volume int() crash** — Safe conversion with try/except ValueError/TypeError
- **app_launcher shell=True** — Replaced with os.startfile() for security
- **Signal handler** — Uses shutdown_event.set() instead of sys.exit(0)
- **getStatusBar() triple-call** — Computed once instead of 3x per render
- **Connection alert removed** — No more jarring Alert popup on first WebSocket connect

### Removed
- **Master password requirement** — Server auto-unlocks with default password
- **webbrowser.open() for YouTube** — Replaced by Playwright with auto-play
- **HTML scraping for YouTube** — Replaced by yt-dlp (reliable JSON output)
- **pyautogui auto-chain for YouTube** — Playwright handles play natively via JS
- **webbrowser.py module** — Merged into browser_control.py with Playwright

## [1.0.0] — 2026-07-11

### Added
- Initial GnomeSpeak project structure with `server/` (Python) and `client/` (React Native)
- WebSocket communication with auto-reconnect, heartbeat pings, and exponential backoff
- On-device Android STT via `@react-native-voice/voice` with `PermissionsAndroid`
- OpenAI GPT-3.5 intent parsing with rule-based regex fallback
- File operations: navigate, list, create, delete, copy, move
- App launcher: Start Menu → common install dirs → PATH → `start` fallback
- Email sender: configurable SMTP with TLS
- Browser control: open URLs, web search, YouTube search via `webbrowser`
- Bluetooth control: radio on/off/status/scan via PowerShell (connect/disconnect pending winrt)
- Media playback: local file search in Music/Downloads, system volume control via pycaw/PowerShell
- Question/answer protocol for agent-to-user clarification
- Agent loop: OpenAI function-calling with 15 tool definitions, max 10 iterations
- Client UI: Home screen (status + record + log), Settings screen, ClarificationDialog
- Fernet-encrypted config with PBKDF2 key derivation and wrong-password detection
- Specifications under `openspec/specs/` covering 16 capabilities

### Changed
- Intent parser rewritten from one-shot parse → multi-step agent loop with tool calling
- Command executor refactored to dynamic tool dispatch
- Bluetooth logic extracted from command_executor into dedicated handler
- MediaPlayer handler created for volume control and local playback

### Fixed
- Client TypeScript errors: import paths, WebSocket MessageEvent typing, onResult/onQuestion callback naming
- STT: denied permission shows alert with "Open Settings" button; failures show user-facing error; mic disabled when no permission
