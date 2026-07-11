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
| Server → Client | `question` | Agent asks user for clarification (`id`, `message`, `options`) |
| Client → Server | `answer` | User's response to agent clarification |
| Client → Server | `ping` | Heartbeat keep-alive (30s interval) |
| Server → Client | `pong` | Heartbeat response |

### Command Flow

```
User speaks → on-device STT → WebSocket command (with session_id)
  → IntentParser.parse()
    → [OpenAI] Agent loop — function calling, max 10 iterations
    → [Gemini] Agent loop — native function calling, max 5 iterations
    → [OpenCode/OpenRouter] Agent loop — OpenAI-compatible API
    → [No API key] Regex fallback
  → CommandExecutor.execute_tool() (async)
  → Handler executes → result returned to client
  → Session history stored for multi-turn context
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
Manages encrypted secrets using Fernet (AES-128-CBC). Master password derived via PBKDF2-HMAC-SHA256 (600k iterations). Auto-unlocks with default password `voicetalk` — no manual password entry required.

### intent_parser.py
Core AI integration. Supports 4 providers:

| Provider | SDK | Agent Loop | Native Function Calling |
|----------|-----|------------|------------------------|
| OpenAI | `openai` (AsyncOpenAI) | Up to 10 iterations | Yes |
| Gemini | `google.genai` | Up to 5 iterations | Yes (native FunctionDeclaration) |
| OpenCode | `openai` (custom base URL) | Up to 10 iterations | Yes |
| OpenRouter | `openai` (custom base URL) | Up to 10 iterations | Yes |

**Session management:** Conversations tracked by `session_id`. Max 50 sessions, max 100 messages per session. LRU eviction when limit exceeded.

**System prompt:** Enforces full PC autonomy — AI never asks user to click/tap. English-only responses. Error recovery protocol. YouTube single-tab rules.

### command_executor.py
Async tool dispatch. Routes 23 tool names to 7 handler modules. Includes safe `int()` conversion for volume level.

### Handlers

| Handler | Tools | Backend |
|---------|-------|---------|
| `browser_control.py` | `browser_navigate`, `browser_search`, `yt_play`, `yt_search`, `yt_results` | **Playwright** (async Chromium) for YouTube; `webbrowser` for general browsing; **yt-dlp** for search |
| `file_ops.py` | `navigate`, `list_dir`, `create_file`, `create_folder`, `delete`, `copy`, `move` | Python stdlib (`os`, `shutil`, `pathlib`) |
| `app_launcher.py` | `open_app` | Start Menu scan → common dirs → `os.startfile()` |
| `email_sender.py` | `send_email` | `smtplib` with TLS |
| `bluetooth_control.py` | `control_bluetooth` (on/off/scan/status, connect/disconnect with winrt) | PowerShell |
| `media_player.py` | `play_media`, `volume_up`, `volume_down`, `volume_mute`, `set_volume` | `pycaw` (set_volume), `os.startfile`, PowerShell |
| `media_control.py` | `media_control` (play_pause, skip, volume, fullscreen, etc.) | **pyautogui** keyboard simulation |

### Browser Automation (Playwright)

The browser handler uses a hybrid approach:

- **YouTube playback** (`yt_play`): Uses Playwright's async Chromium to navigate to the video page and auto-play via JavaScript `v.play()`. Single persistent browser instance. All navigation happens in one tab.
- **General browsing** (`browser_navigate`, `browser_search`): Uses Python's `webbrowser.open()` to open URLs in the user's default browser.
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

- API keys encrypted at rest using Fernet (PBKDF2-HMAC-SHA256, 600k iterations)
- Auto-unlocks with default password — no manual entry required
- WebSocket runs on local network only (no internet exposure)
- Session limit (50 sessions, 100 messages each) prevents memory exhaustion
- `google.genai` import wrapped in try/except — server starts without Gemini SDK
- Volume level input safely converted with try/except
