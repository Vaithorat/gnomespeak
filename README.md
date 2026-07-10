# VoiceTalk

Voice-controlled interface between Android (React Native) and Windows (Python). Speak commands on your phone — open apps, browse files, send emails, control Bluetooth, play music, search the web, and more on your PC.

## Features

- **Voice commands** — On-device speech-to-text (works offline)
- **AI-powered parsing** — OpenAI GPT-3.5 agent loop with 17 tools (regex fallback when offline)
- **File operations** — Navigate, list, create, delete, copy, move files and folders
- **App launcher** — Launch any app via Start Menu, common directories, or PATH
- **Web & YouTube** — Open URLs, search the web, search YouTube results
- **Bluetooth control** — Turn radio on/off, scan for devices (connect/disconnect with winrt)
- **Media & volume** — Play local music files, set volume, mute
- **Email** — Send via configurable SMTP (Gmail, Outlook, any provider)
- **Clarification dialog** — Agent asks you questions on your phone when it needs more info
- **Secure** — API keys encrypted at rest (Fernet + PBKDF2), local network only

## Architecture

```
Android Phone                    Windows PC
┌──────────────┐                ┌────────────────────────────┐
│  React Native │  WebSocket    │  Python Server             │
│  App          │────ws://──────│  OpenAI Agent Loop         │
│  on-device STT│               │  → 7 handlers (17 tools)   │
│  + dialog UI  │               │  → encrypted config        │
└──────────────┘                └────────────────────────────┘
```

## Quick Start

### Server (Windows)

```powershell
cd server
pip install -r requirements.txt
python server.py
# Enter master password on first run → guided setup for API key & email
```

### Client (Android)

```bash
cd client
npm install
npx react-native run-android
```

Open the app → tap gear icon → enter your PC's IP:port and OpenAI API key → tap **Save**.

## Usage Examples

| Say... | What happens |
|--------|-------------|
| *"Open Chrome"* | Launches Chrome browser |
| *"Open youtube.com"* | Opens YouTube in browser |
| *"Play despacito"* | Opens YouTube search results for despacito |
| *"Search for React Native tutorials"* | Opens Google search results |
| *"Show my desktop"* | Lists files on Desktop |
| *"Go to Documents"* | Opens Documents in File Explorer |
| *"Create file todo.txt"* | Creates todo.txt |
| *"Email bob@example.com with subject Hello"* | Sends email |
| *"Turn on Bluetooth"* | Enables Bluetooth radio |
| *"Scan for Bluetooth devices"* | Lists nearby BT devices |
| *"Volume 50%"* | Sets system volume to 50% |
| *"Play despacito from local files"* | Searches Music/Downloads for matching files |
| *"What's my IP address?"* | Agent gets system info |

## Project Structure

```
voicetalk/
├── client/                    # React Native Android app
│   ├── App.tsx                # Root with navigation + AppContext
│   ├── src/
│   │   ├── components/        # RecordButton, ConnectionStatus, CommandLog, ClarificationDialog
│   │   ├── screens/           # HomeScreen, SettingsScreen
│   │   ├── services/          # WebSocket (auto-reconnect), AsyncStorage
│   │   └── types/             # TypeScript interfaces
│   └── package.json
├── server/                    # Python Windows server
│   ├── server.py              # WebSocket entry point
│   ├── config.py              # Fernet-encrypted secrets
│   ├── auth.py                # API key validation
│   ├── intent_parser.py       # OpenAI agent loop + regex fallback
│   ├── command_executor.py    # Tool dispatch
│   ├── handlers/
│   │   ├── file_ops.py        # File/folder operations
│   │   ├── app_launcher.py    # Application launching
│   │   ├── email_sender.py    # SMTP email
│   │   ├── browser_control.py # Web URLs, search, YouTube
│   │   ├── bluetooth_control.py # BT radio & devices
│   │   └── media_player.py    # Local playback & volume
│   └── requirements.txt
├── openspec/                  # Specifications (16 capabilities)
│   └── specs/
├── ARCHITECTURE.md
├── CHANGELOG.md
└── README.md
```

## Security

- **API keys & SMTP credentials** encrypted at rest using Fernet (PBKDF2-HMAC-SHA256, 600k iterations)
- **Master password** required at server startup to decrypt config
- **Local network only** — WebSocket runs on your LAN, no internet exposure
- **Key validation** — API key format checked on every command
- **Wrong password detection** — unlock verifies by test-decrypting existing data

## Requirements

- **Server:** Windows 10+, Python 3.10+
- **Client:** Android 8+ (API 26+), Node.js 18+
- **OpenAI API key** (sk-...) — for AI agent features (regex fallback works without it)
