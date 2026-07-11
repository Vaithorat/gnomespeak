# Changelog

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
