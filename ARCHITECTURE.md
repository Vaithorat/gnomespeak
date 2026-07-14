# Architecture

## Overview

VoiceTalk is a voice-controlled interface between an Android phone and a Windows PC. The user speaks commands on their phone, which are transcribed on-device, sent over WebSocket to a Python server on the PC, and executed as system actions via an AI agent.

```
┌──────────────────────────┐         ┌──────────────────────────────────────┐
│   Android Phone           │         │       Windows PC                     │
│  (React Native)           │         │      (Python Server)                 │
│                           │         │                                      │
│  ┌───────────────────┐    │         │  ┌────────────────────────────────┐  │
│  │ RecordButton       │    │         │  │  IntentParser                  │  │
│  │ (on-device STT)    │    │  ws://  │  │  • OpenAI agent loop           │  │
│  ├───────────────────┤    ├─────────┼──┤  • Gemini native function call  │  │
│  │ ConversationThread │    │         │  │  • OpenCode / OpenRouter        │  │
│  │ (chat UI)          │    │         │  │  • Regex fallback               │  │
│  ├───────────────────┤    │         │  └──────────────┬─────────────────┘  │
│  │ 3 Modes:           │    │         │                 │                    │
│  │ • Voice (PTT)      │    │         │  ┌──────────────▼─────────────────┐  │
│  │ • Conversation     │    │         │  │  CommandExecutor (async)       │  │
│  │ • Chat (text)      │    │         │  │  (tool dispatch)               │  │
│  └───────────────────┘    │         │  └──┬───┬───┬───┬───┬───┬───┬────┘  │
│                           │         │     │   │   │   │   │   │   │        │
│  ┌───────────────────┐    │         │     ▼   ▼   ▼   ▼   ▼   ▼   ▼        │
│  │ ConnectionStatus   │    │         │  ┌────────────────────────────────┐  │
│  │ ClarificationDialog│    │         │  │  Handlers:                    │  │
│  │ CommandLog          │    │         │  │  • BrowserControl (Playwright)│  │
│  │ SettingsScreen     │    │         │  │  • FileOps                    │  │
│  └───────────────────┘    │         │  │  • AppLauncher                │  │
│                           │         │  │  • EmailSender                 │  │
│                           │         │  │  • BluetoothControl            │  │
│                           │         │  │  • MediaPlayer                 │  │
│                           │         │  │  • MediaControl (pyautogui)    │  │
│                           │         │  └────────────────────────────────┘  │
│                           │         └──────────────────────────────────────┘
└──────────────────────────┘
```

## Communication Protocol

### WebSocket (JSON)

| Direction | Type | Purpose |
|-----------|------|---------|
| Client → Server | `command` | Voice transcript + API key + provider + session_id |
| Server → Client | `result` | Command execution result (`success`, `message`) |
| Server → Client | `stream_chunk` | Incremental AI response text (`content`) |
| Server → Client | `stream_result` | Final result after streaming completes (`success`, `message`) |
| Server → Client | `question` | Agent asks user for clarification (`id`, `message`, `options`) |
| Client → Server | `answer` | User's response to agent clarification |
| Client → Server | `ping` | Heartbeat keep-alive (30s interval) |
| Server → Client | `pong` | Heartbeat response |

### Command Flow

```
User speaks → on-device STT → WebSocket command (with session_id)
  → IntentParser.parse_stream() (async generator)
    → [OpenAI] Agent loop — function calling, max 10 iterations, streaming
    → [Gemini] Agent loop — native function calling, max 5 iterations, streaming
    → [OpenCode/OpenRouter] Agent loop — OpenAI-compatible API, streaming
    → [No API key] Regex fallback
  → Yields stream_chunk → Server sends incremental text to client
  → CommandExecutor.execute_tool() (async)
    → SafetyChecker intercepts destructive tools (delete/move/copy/overwrite)
    → If confirmation required → ask_user flow → user confirms/denies
  → Handler executes → result returned to client
  → stream_result sent → Session history stored for multi-turn context
```

### Question/Answer Flow

```
Agent calls ask_user() → server sends {"type": "question", ...}
  → Client shows ClarificationDialog (options + free text)
  → User responds → Client sends {"type": "answer", ...}
  → Server resolves pending Future → agent loop continues with answer
```

## Server Components

### config.py
Manages encrypted secrets using Fernet (AES-128-CBC). Master password generated randomly on first run via `secrets.token_urlsafe(24)` and stored in `.master` file. Auto-unlocks on subsequent starts by reading `.master` — no manual password entry required.

### intent_parser.py
Core AI integration. Supports 5 providers with streaming:

| Provider | SDK | Agent Loop | Native Function Calling |
|----------|-----|------------|------------------------|
| OpenAI | `openai` (AsyncOpenAI) | Up to 10 iterations | Yes |
| Gemini | `google.genai` | Up to 5 iterations | Yes (native FunctionDeclaration) |
| OpenCode | `openai` (custom base URL) | Up to 10 iterations | Yes |
| OpenRouter | `openai` (custom base URL) | Up to 10 iterations | Yes |
| Ollama | `openai` (localhost:11434) | Up to 10 iterations | Yes |

**Streaming:** `parse_stream()` is an async generator yielding `{type: "chunk", content}` and `{type: "tool_result", ...}` messages. Sentence-level chunking via regex (`[.!?]\s|\n`), max 500 chars per chunk. OpenAI uses `stream=True` + `stream_options`. Gemini appends user message outside tool loop.

**Session management:** Conversations tracked by `session_id`. Max 50 sessions, max 100 messages per session. LRU eviction when limit exceeded.

**System prompt:** Enforces full PC autonomy — AI never asks user to click/tap. English-only responses. Error recovery protocol. YouTube single-tab rules. Environment model context injected (desktop files, installed apps, recent folders).

### command_executor.py
Async tool dispatch. Routes 23 tool names to 7 handler modules. Includes SafetyChecker (intercepts destructive operations for user confirmation) and EnvironmentModel (cached desktop/apps/folders). File operations refresh affected folders in the environment cache. Includes safe `int()` conversion for volume level.

### Handlers

| Handler | Tools | Backend |
|---------|-------|---------|
| `browser_control.py` | `browser_navigate`, `browser_search`, `yt_play`, `yt_search`, `yt_results` | **Playwright** (async Chromium) for YouTube; `webbrowser` for general browsing; **yt-dlp** for search |
| `file_ops.py` | `navigate`, `list_dir`, `create_file`, `create_folder`, `delete`, `copy`, `move` | Python stdlib (`os`, `shutil`, `pathlib`) |
| `app_launcher.py` | `open_app` | PowerShell `Get-StartApps` → Start Menu scan → common dirs → `os.startfile()` |
| `email_sender.py` | `send_email` | `smtplib` with TLS |
| `bluetooth_control.py` | `control_bluetooth` (on/off/scan/status, connect/disconnect with winrt) | PowerShell |
| `media_player.py` | `play_media`, `volume_up`, `volume_down`, `volume_mute`, `set_volume` | `pycaw` (set_volume), `os.startfile`, PowerShell |
| `media_control.py` | `media_control` (play_pause, skip, volume, fullscreen, etc.) | **pyautogui** keyboard simulation |

### Browser Automation (Playwright)

The browser handler uses a hybrid approach:

- **YouTube playback** (`yt_play`): Uses Playwright's async Chromium to navigate to the video page and auto-play via JavaScript `v.play()`. Single persistent browser instance. All navigation happens in one tab.
- **General browsing** (`browser_navigate`, `browser_search`): Uses Playwright to navigate in the persistent browser instance.
- **YouTube search data** (`yt_results`): Uses `yt-dlp` CLI for fast, reliable search without browser overhead.

## Client Components

### Three Modes

| Mode | UI | How It Works |
|------|-----|-------------|
| **Voice** (default) | Push-to-talk button | Hold mic → speak → release → send once |
| **Conversation** | Continuous thread + listening bar | Always listening, 1.5s silence auto-sends, multi-turn |
| **Chat** | Text input + send button | Type messages, same session as voice mode |

### Components

| Component | Purpose |
|-----------|---------|
| `App.tsx` | Navigation stack + AppContext provider (pastel → flat redesign) |
| `HomeScreen.tsx` | Main screen — 3 modes, pipeline status, command log, session management |
| `SettingsScreen.tsx` | Server URL + 4 API keys (OpenAI, Gemini, OpenCode, OpenRouter) with show/hide |
| `RecordButton.tsx` | Push-to-talk with permissions, error handling, recording state |
| `ConversationThread.tsx` | FlatList of user/assistant/question bubbles with live transcription |
| `useConversationMode.ts` | Continuous STT lifecycle, silence detection, session management |
| `ClarificationDialog.tsx` | Modal with option buttons + free-text input |
| `CommandLog.tsx` | Scrollable log with success/failure indicators |
| `ConnectionStatus.tsx` | Colored dot indicator (green/yellow/gray/red) |
| `websocket.ts` | Auto-reconnect with exponential backoff, 30s ping, URL normalization |
| `storage.ts` | AsyncStorage wrapper for settings persistence |
| `types/index.ts` | TypeScript interfaces + `getActiveProvider()` utility |

## Tool Definitions (23 Tools)

| # | Tool | Description |
|---|------|-------------|
| 1 | `browser_navigate` | Open a URL in the default browser |
| 2 | `browser_search` | Web search (Google/Bing/DuckDuckGo) |
| 3 | `yt_play` | Search + open + auto-play YouTube video (Playwright) |
| 4 | `yt_search` | Open YouTube search results page |
| 5 | `yt_results` | Fetch top 10 YouTube results with titles (yt-dlp) |
| 6 | `open_app` | Launch a Windows application |
| 7 | `navigate` | Open file/folder in Explorer |
| 8 | `list_dir` | List directory contents |
| 9 | `create_file` | Create file with optional content |
| 10 | `create_folder` | Create directory |
| 11 | `delete` | Delete file/folder |
| 12 | `copy` | Copy file/folder |
| 13 | `move` | Move/rename file/folder |
| 14 | `send_email` | Send email via configured SMTP |
| 15 | `control_bluetooth` | BT radio on/off/scan/connect/disconnect |
| 16 | `get_system_info` | OS version, Bluetooth hardware info |
| 17 | `play_media` | Search and play local music files |
| 18 | `volume_up` | Increase system volume |
| 19 | `volume_down` | Decrease system volume |
| 20 | `volume_mute` | Toggle mute |
| 21 | `set_volume` | Set volume to specific level |
| 22 | `media_control` | Keyboard actions (play/pause, skip, fullscreen, etc.) |
| 23 | `ask_user` | Ask user for clarification via phone dialog |

## Security

- **Random master password** — Generated on first run via `secrets.token_urlsafe(24)`, stored in `.master` file. No hardcoded passwords.
- **Encrypted config** — API keys and SMTP credentials encrypted at rest using Fernet (PBKDF2-HMAC-SHA256, 600k iterations)
- **Auto-unlock** — Reads `.master` file on startup — no manual password entry required
- **`config.json` gitignored** — Encrypted secrets file excluded from version control
- **WebSocket on local network only** — No internet exposure (binds `0.0.0.0:8765`)
- **Session limits** — Max 50 sessions, 100 messages each, LRU eviction prevents memory exhaustion
- **Safe imports** — `google.genai` wrapped in try/except — server starts without Gemini SDK
- **Safe volume conversion** — `int()` wrapped in try/except ValueError/TypeError
- **PowerShell injection prevention** — App names escaped with single-quote doubling before embedding in PS commands

## Safety System

`server/safety.py` provides destructive operation protection:

- **Intercepted tools:** `delete`, `move`, `copy`, `create_file` (when overwriting)
- **Flow:** SafetyChecker.check() → ask_user() → user confirms/denies → operation proceeds or is cancelled
- **Safe default:** On exception or timeout, destructive operations are denied (not approved)
- **Configurable:** `SafetyChecker.enabled` flag can disable checks (used in tests)

## Environment Model

`server/env_model.py` provides cached system awareness:

- **Desktop files** — Up to 30 filenames and types from `~/Desktop`
- **Installed apps** — Up to 50 app names from Start Menu (`.lnk`, `.exe` files)
- **Recent folders** — Up to 10 recently browsed folder paths with item counts
- **Lazy refresh** — Refreshes on access if stale (>15 minutes since last refresh)
- **Background refresh** — Full refresh runs as asyncio task (non-blocking)
- **Context injection** — `build_context_prompt()` output appended to system prompt on every AI request
- **Folder updates** — File operations refresh affected folders via `refresh_folder()`

## Data Privacy

`server/redactor.py` (planned) sanitizes tool results before AI API calls:

| Privacy Level | Behavior |
|---------------|----------|
| `full` | No redaction — all data sent to AI provider |
| `smart` | Redacts file contents, email bodies; keeps paths/URLs |
| `strict` | Redacts all file paths, directory listings, URLs, device names |

**Redaction rules:**
- File paths → `[file:name.ext]`
- Directory listings → `[N items: X files, Y folders]`
- Browser URLs → `[opened: domain.com]`
- Email bodies → `[email body redacted]`
- System info → OS/arch only, no Bluetooth device names

## Device Pairing (Planned)

`server/pairing.py` — TeamViewer-style secure pairing:

- **First connection:** 6-digit code displayed on Windows GUI, entered on phone
- **Subsequent connections:** Trusted device token (`vt_` prefix) auto-authenticates
- **Token storage:** Encrypted in config via Fernet
- **Rate limiting:** 5 attempts per code, code expires after 5 minutes
