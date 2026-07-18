# VoiceTalk

Voice-controlled interface between Android (React Native) and Windows (Python). Speak commands on your phone to open apps, browse files, send emails, control supported Bluetooth radio actions, play music, open YouTube videos, search the web, and more on your PC.

## Features

- **Voice commands** — On-device speech-to-text with device-locale recognition and alternative transcript fallback
- **3 interaction modes** — Push-to-talk, continuous conversation, or text chat
- **4 AI providers** — OpenAI, Gemini, OpenCode, OpenRouter (free models available)
- **YouTube playback** — Search and open videos via Playwright browser automation, with explicit reporting when autoplay is blocked
- **File operations** — Navigate, list, create, delete, copy, move files and folders
- **App launcher** — Launch any app via Start Menu, common directories, or PATH
- **Web browsing** — Open URLs and searches in your system default browser; reserve Playwright only for automation flows
- **Deterministic command routing** — Common browser, YouTube, volume, Bluetooth, file, and app phrases execute without LLM guesswork
- **Bluetooth control** — Turn the radio on/off when supported and scan for devices
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
This is the supported packaged GUI entry point. No Python installation is needed for core voice/file/app control.

Browser automation is not bundled inside the EXE itself. VoiceTalk first uses your system default browser for simple open/search/navigation commands. For browser automation flows, it falls back to a VoiceTalk-managed browser profile and only installs Playwright Chromium as a last resort into `%APPDATA%\VoiceTalk\ms-playwright`.

Windows packaging notes:
- First launch may show SmartScreen for unsigned internal builds. Only bypass it for a build you trust.
- Allow the app through the Windows firewall on Private networks so the phone can reach `ws://<pc-lan-ip>:8765`.
- The GUI writes rotating logs to `%APPDATA%\VoiceTalk\logs\voicetalk-server.log` and lets you export them from the `Export Logs` button.
- Browser-powered open/search commands prefer your normal signed-in browser first. Only automation flows such as opening and trying to autoplay a YouTube video use the VoiceTalk-managed browser runtime.

### Client Setup (Android Phone)

**Option A: Install pre-built APK**
```powershell
adb install -r voicetalk/client/android/app/build/outputs/apk/debug/app-debug.apk
```

This debug APK is for local development only. Do not distribute it as a release build.

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
| *"Play Golmaal 3 on YouTube"* | Searches YouTube, opens the video, and reports whether autoplay started |
| *"Open YouTube and search for Taarak Mehta"* | Opens YouTube search results in your default browser |
| *"Play the first video"* | Reuses the most recent YouTube search query and opens the first matching result |
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
│   ├── windows_gui.py             # Supported desktop server entry point
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
| OpenAI | gpt-4o-mini | No | Full agent loop, 10 iterations |
| Gemini | Gemini 2.0 Flash | Yes (limited) | Native function calling, 5 iterations |
| OpenCode | deepseek-v4-flash-free | Yes | Via opencode.ai Zen API |
| OpenRouter | nvidia/nemotron-nano-9b-v2:free | Yes | Via openrouter.ai |

At least one provider API key is required. The server auto-detects which provider to use based on which key is configured.

## Requirements

- **Server:** Windows 10+, Python 3.10+ for source setup, Playwright Chromium for browser features
- **Client:** Android 8+ (API 26+), Node.js 18+
- **Network:** Phone and PC on same local network

## Supported Versions

- **Windows:** Windows 10 or later
- **Python (source server):** Python 3.12 is the CI-tested version; Python 3.10+ may work, but releases are validated on 3.12
- **Node.js (client source build):** Node 20 is the CI-tested version
- **Android:** Android 8+ (API 26+)

## Security

- **API keys & SMTP credentials** encrypted at rest using Fernet (PBKDF2-HMAC-SHA256, 600k iterations)
- **Trusted LAN only** — WebSocket traffic is cleartext `ws://`; do not expose this server to the internet or untrusted networks because provider API keys travel over the socket
- **Session limits** — Max 50 sessions, 30 messages per session to prevent memory exhaustion

## Configuration And Recovery

- **Config location:** `%APPDATA%\VoiceTalk\config.json`
- **Master key:** `%APPDATA%\VoiceTalk\.master`
- **Master-key backup:** `%APPDATA%\VoiceTalk\.master.bak`
- **Logs:** `%APPDATA%\VoiceTalk\logs\voicetalk-server.log`
- **Diagnostics bundles:** `%APPDATA%\VoiceTalk\diagnostics\`

If the GUI says the saved configuration could not be unlocked:

1. Use **Restore Backup** first if `.master.bak` exists.
2. Use **Reset Saved Secrets** only if you accept losing stored API keys and SMTP credentials.
3. For CLI use, restore `.master` from `.master.bak`, then rerun `python server.py`.

## Firewall, Updates, Backup, Rollback

- Allow the server through **Windows Firewall on Private networks only**.
- Keep a backup copy of `%APPDATA%\VoiceTalk\config.json`, `.master`, and `.master.bak` before upgrades.
- When updating from source, reinstall dependencies with `pip install -r requirements.txt` and rerun `playwright install chromium` if browser features stop working.
- When updating the Android app, increment `versionCode` and `versionName` before building the next release artifact.
- If a new build regresses, roll back to the previous EXE or Android artifact together with the matching config/master-key backup.

## Diagnostics Bundle

Create a support bundle from either path:

- GUI: click **Export Diagnostics**
- CLI/source server:

```powershell
cd voicetalk/server
python diagnostics.py
```

The bundle includes:

- server version
- config schema version
- Android build version from source checkout when available
- sanitized server logs
- dependency versions
- local TCP connectivity test output for the configured host/port

Use this bundle plus the exported logs when reporting install, connection, or upgrade problems.

## Android Release Builds

Release signing is not checked into the repo. Release builds fail unless you provide signing values via environment variables or Gradle properties:

- `VOICETALK_RELEASE_STORE_FILE`
- `VOICETALK_RELEASE_STORE_PASSWORD`
- `VOICETALK_RELEASE_KEY_ALIAS`
- `VOICETALK_RELEASE_KEY_PASSWORD`

Recommended distribution artifact:

```powershell
cd voicetalk/client/android
.\gradlew.bat bundleRelease
```

This produces an Android App Bundle (AAB) for distribution. Use an APK only for documented sideloading:

```powershell
cd voicetalk/client/android
.\gradlew.bat assembleRelease
```

Release builds enable R8/resource shrinking and do not include Flipper. Increment `versionCode` and `versionName` as part of the release process.
