# Changelog

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
- Initial project structure with `server/` (Python) and `client/` (React Native)
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
