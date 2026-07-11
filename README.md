# VoiceTalk

Voice-controlled interface between Android (React Native) and Windows (Python). Speak commands on your phone — open apps, browse files, send emails, control Bluetooth, play music, play YouTube videos, search the web, and more on your PC.

## Features

- **Voice commands** — On-device speech-to-text (works offline)
- **3 interaction modes** — Push-to-talk, continuous conversation, or text chat
- **4 AI providers** — OpenAI, Gemini, OpenCode, OpenRouter (free models available)
- **YouTube playback** — Search and auto-play videos via Playwright browser automation
- **File operations** — Navigate, list, create, delete, copy, move files and folders
- **App launcher** — Launch any app via Start Menu, common directories, or PATH
- **Web browsing** — Open URLs, search Google/Bing/DuckDuckGo
- **Bluetooth control** — Turn radio on/off, scan for devices
- **Media & volume** — Play local music, set volume, mute, keyboard media keys
- **Email** — Send via configurable SMTP (Gmail, Outlook, any provider)
- **Clarification dialog** — Agent asks you questions on your phone when it needs more info
- **Multi-turn sessions** — AI remembers context across messages within a session
- **Secure** — API keys encrypted at rest (Fernet + PBKDF2), local network only

## Installation

### Prerequisites

- **Windows 10+** with Python 3.10+ and Node.js 18+
- **Android phone** with USB debugging enabled (or same WiFi network)
- **ADB** installed (for APK install): `winget install Google.PlatformTools` or download from [developer.android.com](https://developer.android.com/tools/releases/platform-tools)

### Server Setup (Windows PC)

**Option A: Run from source**
```powershell
cd voicetalk/server
pip install -r requirements.txt
playwright install chromium
python server.py
```

The server starts on `ws://0.0.0.0:8765` automatically. A GUI window shows the connection URL.

**Option B: Run packaged EXE**
```
dist/VoiceTalkServer.exe
```
No Python installation needed. Playwright Chromium is bundled.

### Client Setup (Android Phone)

**Option A: Install pre-built APK**
```powershell
adb install -r voicetalk/client/android/app/build/outputs/apk/debug/app-debug.apk
```

**Option B: Build from source**
```bash
cd voicetalk/client
npm install
cd android
./gradlew assembleDebug
# APK at: android/app/build/outputs/apk/debug/app-debug.apk
```

**Option C: Run on connected device**
```bash
cd voicetalk/client
npm install
npx react-native run-android
```

### First-Time Configuration

1. Start the server on your PC — note the IP address shown in the GUI (e.g., `192.168.1.5:8765`)
2. Open the VoiceTalk app on your phone
3. Tap the **gear icon** (top right) to open Settings
4. Enter the server IP:port (e.g., `192.168.1.5:8765`)
5. Enter at least one API key:
   - **OpenAI**: Get from [platform.openai.com](https://platform.openai.com/api-keys) (paid)
   - **Gemini**: Get from [aistudio.google.com](https://aistudio.google.com/apikey) (free tier)
   - **OpenRouter**: Get from [openrouter.ai](https://openrouter.ai/keys) (free models available)
   - **OpenCode**: Get from [opencode.ai](https://opencode.ai) (free)
6. Tap **Save**
7. The status dot should turn **green** — you're connected!

## Quick Start

Once installed and configured:

1. Ensure your phone and PC are on the **same network**
2. Start the server on your PC
3. Open the app on your phone — status dot should be green
4. **Hold the mic button** and speak a command
5. Release to send — the AI processes and executes on your PC

## Usage Examples

| Say... | What happens |
|--------|-------------|
| *"Play Golmaal 3 on YouTube"* | Searches YouTube, opens the video, auto-plays it |
| *"Search for React Native tutorials"* | Opens Google search results |
| *"Open chrome"* | Launches Chrome browser |
| *"Open youtube.com"* | Opens YouTube in browser |
| *"Show my desktop"* | Lists files on Desktop |
| *"Go to Documents"* | Opens Documents in File Explorer |
| *"Create file todo.txt"* | Creates todo.txt |
| *"Email bob@example.com with subject Hello"* | Sends email |
| *"Turn on Bluetooth"* | Enables Bluetooth radio |
| *"Scan for Bluetooth devices"* | Lists nearby BT devices |
| *"Volume 50%"* | Sets system volume to 50% |
| *"Play despacito from local files"* | Searches Music/Downloads for matching files |
| *"Pause"* / *"Resume"* | Keyboard play/pause via media_control |
| *"Fullscreen"* | Toggles F11 fullscreen |

### Chat Mode

Tap the **Chat** button to switch to text input mode. Type messages directly — same session context as voice mode.

### Conversation Mode

Tap the **Conversation** button for hands-free continuous listening. The AI listens for your voice, auto-sends after 1.5s of silence, and responds automatically.

## Project Structure

```
voicetalk/
├── client/                        # React Native Android app
│   ├── App.tsx                    # Root with navigation + AppContext
│   ├── src/
│   │   ├── components/            # RecordButton, ConversationThread, CommandLog, etc.
│   │   ├── screens/               # HomeScreen, SettingsScreen
│   │   ├── hooks/                 # useConversationMode (continuous STT)
│   │   ├── services/              # WebSocket (auto-reconnect), AsyncStorage
│   │   └── types/                 # TypeScript interfaces
│   └── android/                   # Android native build
├── server/                        # Python Windows server
│   ├── server.py                  # WebSocket entry point
│   ├── config.py                  # Fernet-encrypted secrets (auto-unlock)
│   ├── intent_parser.py           # Multi-provider AI agent loop
│   ├── command_executor.py        # Async tool dispatch (23 tools)
│   ├── handlers/
│   │   ├── browser_control.py     # Playwright + webbrowser + yt-dlp
│   │   ├── media_control.py       # pyautogui keyboard simulation
│   │   ├── file_ops.py            # File/folder operations
│   │   ├── app_launcher.py        # Application launching
│   │   ├── email_sender.py        # SMTP email
│   │   ├── bluetooth_control.py   # BT radio & devices
│   │   └── media_player.py        # Local playback & volume
│   ├── windows_gui.py             # CustomTkinter GUI wrapper
│   ├── windows_app.py             # System tray icon wrapper
│   └── requirements.txt
├── openspec/                      # Specifications (21 capabilities)
│   └── specs/
├── ARCHITECTURE.md
├── CHANGELOG.md
└── README.md
```

## AI Providers

| Provider | Model | Free? | Notes |
|----------|-------|-------|-------|
| OpenAI | GPT-3.5-turbo | No | Full agent loop, 10 iterations |
| Gemini | Gemini 2.0 Flash | Yes (limited) | Native function calling, 5 iterations |
| OpenCode | deepseek-v4-flash | Yes | Via opencode.ai API |
| OpenRouter | gemini-2.0-flash-lite | Yes | Via openrouter.ai |

At least one provider API key is required. The server auto-detects which provider to use based on which key is configured.

## Requirements

- **Server:** Windows 10+, Python 3.10+, Playwright Chromium (auto-installed)
- **Client:** Android 8+ (API 26+), Node.js 18+
- **Network:** Phone and PC on same local network

## Security

- **API keys & SMTP credentials** encrypted at rest using Fernet (PBKDF2-HMAC-SHA256, 600k iterations)
- **Local network only** — WebSocket runs on your LAN, no internet exposure
- **Session limits** — Max 50 sessions, 100 messages per session to prevent memory exhaustion
