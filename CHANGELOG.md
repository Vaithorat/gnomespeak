# Changelog

## [Unreleased]

### Added
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
