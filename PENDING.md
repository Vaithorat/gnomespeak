# VoiceTalk v3: Pending Work

## Current State

- ✅ **Core remote control** — MPRIS players, system audio, window management
- ✅ **Installed apps launcher** — Search and launch any installed app
- ✅ **YouTube search** — Find and play YouTube videos via `yt-dlp`
- ✅ **D-Bus/snap confinement handling** — Diagnosed and reported clearly
- ✅ **Error reporting** — Real reasons shown instead of silent failures
- ✅ **Full test coverage** — 94 tests, all passing

## Known Limitations (By Design)

### YouTube Playback Control
- **Wayland only** — Keystroke injection (`xdotool`) cannot work on Wayland (no client-to-client input synthesis)
- **Alternative** — Use Firefox MPRIS player instead (appears under Players when YouTube tab is active)
- **X11 fallback** — Keystroke control available on X11 with `xdotool` and `wmctrl` installed
- **Why not WebDriver?** — Would require opening a separate controlled instance, not controlling the user's real browser

### Snap Confinement Issues
- **VS Code snap terminal** — `vt serve` inherits `snap.code.code` label, blocking D-Bus access to other snaps
- **Workaround** — Start from GNOME Terminal instead (reported by `/vt doctor`)
- **Snap Firefox issue** — Snap-packaged Firefox also confined; AppArmor denials now caught and explained

## What Users Report (Addressed)

### "YouTube search shows no results"
**Root cause:** `yt-dlp` installed in venv but not available to system Python  
**Status:** ✅ Fixed — now shows "yt-dlp is not available to this interpreter" with install instructions  
**Affected:** Users running `python3 -m vt serve` (system Python) instead of `venv/bin/python -m vt serve`

### "YouTube videos won't control"
**Root cause:** Running on Wayland; keystroke injection can only work on X11  
**Status:** ✅ Fixed — keystroke controls don't appear on Wayland, clear message shown  
**Workaround:** Use Firefox MPRIS player (available under Players when video plays)

### "Window controls in Windows section show only Focus/Quit"
**Root cause:** Windows are window-frame controls; playback belongs to the media player (MPRIS)  
**Status:** ✅ By design — MPRIS player appears under Players section with full playback control

### "Keyboard closes when typing YouTube search"
**Root cause:** State poll (1 Hz) was re-rendering the search view  
**Status:** ✅ Fixed — view signature guards prevent re-render while user is typing

## Unimplemented Features

### Would Require New Dependencies
- **WebDriver playback control** — Chromium or Firefox WebDriver to control videos (heavy, user's browser)
- **Native video metadata** — ffprobe/mediainfo for local videos (new source type)
- **Text-to-speech feedback** — espeak or pyttsx3 (invasive for a remote control)

### Would Require User Input Channel
- **Arbitrary text input** — phrase parsing, NLP, or a text form (vt's design: pre-configured commands only)
- **Multi-step workflows** — "search for X, then play the second result" (would need state machine)

### Would Require X11-Only Features
- **Screenshot capture** — scrot/ImageMagick (Wayland-incompatible, X11 only)
- **Window arrangement** — wmctrl (X11 only, window positions meaningless on Wayland)

## Known Issues (Won't Fix / By Design)

1. **Snap confinement** — snapd policy intentionally isolates confined apps; use real terminal
2. **Wayland keystrokes** — Wayland security model blocks input synthesis; use MPRIS instead
3. **Firefox MPRIS gap** — Firefox only exposes MPRIS when at least one media element is playing; can't pre-stage controls
4. **Window IDs** — GNOME extension stable window IDs work only on GNOME (no KDE/XFCE support)
5. **Android app** — v3 is CLI + web UI; native Android would need separate codebase

## Testing Checklist

- [x] 94 unit tests passing
- [x] YouTube search via module backend (venv)
- [x] YouTube search via CLI backend (system Python with yt-dlp on PATH)
- [x] YouTube search error messages (missing yt-dlp, network timeout, etc.)
- [x] App launching (gio + argv fallback)
- [x] App launching error messages (missing binary, immediate failure)
- [x] Installed apps search and filtering
- [x] Window controls (focus, close)
- [x] MPRIS playback (play/pause, seek, volume — subject to player capabilities)
- [x] D-Bus access denied detection and explanation
- [x] Snap confinement detection and explanation
- [x] Audio volume and mute

## Deployment Notes

### Required for Full Feature Set
```bash
sudo apt install python3-dbus python3-psutil yt-dlp
# Optional: window decoration (GNOME only)
# vt install-extension
```

### Optional System Dependencies
```bash
# For YouTube playback control (X11 only; Wayland users: use MPRIS instead)
sudo apt install xdotool wmctrl

# For QR code in server output
pip install qrcode[pil]
```

### Environment Requirements
- **Linux** — GNOME Shell 45+, systemd, PipeWire/ALSA
- **Python** — 3.11+
- **Session** — Wayland or X11 (both supported; feature set varies)
- **Network** — LAN access from phone to PC (no internet required)

## Future Directions (Out of Scope for v3)

- **Desktop recording** — ffmpeg integration for screen capture and playback
- **Voice input** — speech-to-text and intent matching (adds complexity; vt avoids this)
- **Media library** — Plex, Jellyfin, Kodi integration (separate control domain)
- **Brightness/backlight** — systemd-logind or ACPI tools (power management)
- **Network streams** — mpv remote control for streaming (MPRIS covers most use cases)

## Stable Release Readiness

**Current:** Released as `v3.0.0` on 2026-08-23 — design frozen  
**Blockers:** None — all known issues are documented limitations or by-design trade-offs  
**Test status:** 94 tests, all passing  
**CI/CD:** GitHub Actions, Python 3.11–3.13, with and without optional deps

The v2 tree (`client/`, `server/`, its OpenSpec specs, and the v2 root test
scripts) was removed in the release commit; it remains recoverable in git
history at `v2.2.0` and earlier.
