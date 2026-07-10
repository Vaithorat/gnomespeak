# Architecture

## Overview

VoiceTalk is a voice-controlled interface between an Android phone and a Windows PC. The user speaks commands on their phone, which are transcribed on-device, sent over WebSocket to a Python server on the PC, and executed as system actions.

```
┌─────────────────────┐         ┌─────────────────────────────┐
│   Android Phone      │         │       Windows PC            │
│  (React Native)      │         │      (Python Server)        │
│                      │         │                             │
│  ┌──────────────┐    │         │  ┌───────────────────────┐  │
│  │ RecordButton │    │  ws://  │  │   IntentParser        │  │
│  │ (on-device   │────┼─────────┼──┤  (OpenAI agent loop   │  │
│  │  STT)        │    │         │  │   + regex fallback)   │  │
│  └──────────────┘    │         │  └──────────┬────────────┘  │
│                      │         │             │               │
│  ┌──────────────┐    │         │  ┌──────────▼────────────┐  │
│  │ConnectionStatus│  │         │  │  CommandExecutor      │  │
│  └──────────────┘    │         │  │  (tool dispatch)      │  │
│                      │         │  └──┬───┬───┬───┬───┬───┘  │
│  ┌──────────────┐    │         │     │   │   │   │   │      │
│  │   CommandLog  │    │         │     ▼   ▼   ▼   ▼   ▼      │
│  └──────────────┘    │         │  ┌───────────────────────┐  │
│                      │         │  │  Handlers:            │  │
│  ┌──────────────┐    │         │  │  • FileOps            │  │
│  │Clarification │    │         │  │  • AppLauncher        │  │
│  │   Dialog     │    │         │  │  • EmailSender        │  │
│  └──────────────┘    │         │  │  • BrowserControl     │  │
│                      │         │  │  • BluetoothControl   │  │
│  ┌──────────────┐    │         │  │  • MediaPlayer        │  │
│  │   Settings    │    │         │  └───────────────────────┘  │
│  └──────────────┘    │         └─────────────────────────────┘
└─────────────────────┘
```

## Communication Protocol

### WebSocket (JSON)

| Direction | Type | Purpose |
|-----------|------|---------|
| Client → Server | `command` | Voice transcript + API key |
| Server → Client | `result` | Command execution result |
| Server → Client | `question` | Agent asks user for clarification |
| Client → Server | `answer` | User's response to agent |
| Client → Server | `ping` | Heartbeat keep-alive |
| Server → Client | `pong` | Heartbeat response |

### Command Flow

```
User speaks → on-device STT → WebSocket command
  → IntentParser.parse() 
    → [if API key configured] OpenAI agent loop (tool calling)
    → [if no API key] regex fallback
  → CommandExecutor.execute_tool()
  → Handler executes → result returned to client
```

### Question/Answer Flow

```
Agent calls ask_user() → server sends {"type": "question", "id": "...", "message": "...", "options": [...]}
  → Client shows ClarificationDialog
  → User selects option or types answer
  → Client sends {"type": "answer", "id": "...", "text": "..."}
  → Server resolves the pending Future → agent loop continues with answer
```

## Server Components

### config.py
Manages encrypted secrets using Fernet (symmetric encryption with AES-128-CBC). A master password is derived via PBKDF2-HMAC-SHA256 (600k iterations) into a 32-byte key. Unlock verifies the password by attempting decryption of existing data — raises `ValueError` on mismatch.

### auth.py
Validates OpenAI API key format against `^sk-[A-Za-z0-9]{20,}$`.

### intent_parser.py
Core AI integration. Uses `AsyncOpenAI` with function-calling (15 tool definitions). The agent loop:
1. Sends system prompt + user text to GPT-3.5
2. Processes tool_calls (handler dispatch) sequentially
3. Appends each tool result to the conversation
4. Loops until the model returns text (no tool_calls)
5. Falls back to regex rules if no API key is available

Max 10 iterations to prevent runaway loops.

### command_executor.py
Routes tool calls to handlers. Each tool name maps to a handler method. Supports error catching — exceptions return `{"success": false, "message": "..."}` without crashing.

### Handlers

| Handler | Tools | Dependencies |
|---------|-------|-------------|
| `file_ops.py` | navigate, list_dir, create_file, create_folder, delete, copy, move | Python stdlib |
| `app_launcher.py` | open_app | Python stdlib |
| `email_sender.py` | send_email | smtplib (stdlib) |
| `browser_control.py` | browser_navigate, browser_search, yt_play | webbrowser (stdlib) |
| `bluetooth_control.py` | control_bluetooth (status/on/off/scan, connect/disconnect with winrt) | PowerShell |
| `media_player.py` | play_media, volume_up/down/mute, set_volume | pycaw (set_volume), os.startfile, PowerShell |

## Client Components

| Component | Purpose |
|-----------|---------|
| `App.tsx` | Navigation stack + AppContext provider |
| `HomeScreen.tsx` | Main screen — status, record, log, clarification dialog |
| `SettingsScreen.tsx` | Server URL + API key config with show/hide |
| `ConnectionStatus.tsx` | Colored dot indicator (green/yellow/gray/red) |
| `RecordButton.tsx` | Press-and-hold mic with Android Permission request + error handling |
| `CommandLog.tsx` | Scrollable log with success/failure indicators |
| `ClarificationDialog.tsx` | Modal with option buttons + free-text input, blocks recording |
| `websocket.ts` | WebSocket service — auto-reconnect with exponential backoff, 30s ping |
| `storage.ts` | AsyncStorage wrapper for persisting settings |
| `types/index.ts` | TypeScript interfaces for all message types |

## Tool Definitions (OpenAI Function Calling)

The agent has access to these 15 tools:

1. `browser_navigate` — Open URL in default browser
2. `browser_search` — Web search (Google/Bing/DuckDuckGo)
3. `yt_play` — Search YouTube, open results page
4. `open_app` — Launch Windows application
5. `navigate` — Open file/folder in Explorer
6. `list_dir` — List directory contents
7. `send_email` — Send via configured SMTP
8. `create_file` — Create file with optional content
9. `create_folder` — Create directory
10. `delete` — Delete file/folder
11. `copy` — Copy file/folder
12. `move` — Move file/folder
13. `control_bluetooth` — BT radio on/off/scan/connect/disconnect
14. `play_media` — Search and play local music files
15. `volume_up/down/mute/set_volume` — System volume control
16. `get_system_info` — PC capabilities (OS, Bluetooth hardware)
17. `ask_user` — Ask the user for clarification via phone dialog

## Security

- API keys encrypted at rest using Fernet (PBKDF2-HMAC-SHA256)
- Master password required at server startup to decrypt config
- WebSocket runs on local network only (no internet exposure)
- API key validated on every command
- No secrets in source code — all in encrypted config.json
