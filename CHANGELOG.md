# Changelog

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
