# VoiceTalk v3: Pending Work

## Current State

- ✅ **Core remote control** — MPRIS players, system audio, window management
- ✅ **Installed apps launcher** — Search and launch any installed app
- ✅ **YouTube search** — Find and play YouTube videos via `yt-dlp`
- ✅ **D-Bus/snap confinement handling** — Diagnosed and reported clearly
- ✅ **Error reporting** — Real reasons shown instead of silent failures
- ✅ **Cloudflare Tunnel** — `make dev` starts a quick tunnel by default
- ✅ **Device pairing** — off-network callers must pair a device
- ✅ **Security headers** — CSP, HSTS, X-Frame-Options, nosniff
- ✅ **Rate limiting** — auth and pairing attempts rate-limited
- ✅ **Audit log** — every action and rejection recorded
- ✅ **Full test coverage** — 287 tests, all passing
- ✅ **Night light toggle** — `system:display` gets a night-light action via `gsettings`, alongside brightness
- ✅ **Keep-awake toggle** — `system:power` can inhibit the idle screensaver via `org.gnome.SessionManager`, for casting a long video without the screen locking
- ✅ **Dark/light theme toggle** — `system:display` flips `org.gnome.desktop.interface color-scheme`
- ✅ **Microphone control** — `system:mic` mirrors `system:audio`'s volume slider and mute, for the default input node
- ✅ **Wi-Fi radio toggle** — `system:wifi` flips `WirelessEnabled` via NetworkManager (`vt/sources/network.py`), radio on/off only, no network picking
- ✅ **Touchpad, typing and presentation remote** — pointer, scroll, click, literal text and key chords through the GNOME extension (`vt/sources/remote_input.py`, `/api/input`); works under Wayland, where only the compositor may synthesize input
- ✅ **Clipboard sync** — read and set the PC clipboard from the phone (`vt/sources/clipboard.py`, `/api/clipboard`) via wl-clipboard, xclip or xsel
- ✅ **Notification mirroring** — desktop notifications streamed to the phone, read-only, by reading `dbus-monitor` (`vt/sources/notifications_mirror.py`, `/api/notifications`)
- ✅ **File transfer** — phone → `~/Downloads/GnomeSpeak` and back, with open-on-PC (`vt/sources/transfer.py`, `/api/upload`, `/api/files`)
- ✅ **Extension identity in one place** — bus name, object path, uuid and expected method set live in `vt/shell.py`; `vt doctor` introspects the live extension and names the features a stale build is missing

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
**Affected:** Users running `python3 -m vt serve` (system Python) instead of the project venv  
**Prevented by:** `make dev`, which always runs `venv/bin/vt` by absolute path

### "I tap a video on the phone and still have to press play on the PC"
**Root cause:** Firefox blocks autoplay of audible media by default, so the tab opened paused and published no MPRIS player  
**Status:** ✅ Fixed — `vt allow-autoplay` sets the pref, `vt doctor` reports it, and the YouTube screen offers a one-tap fix that restarts Firefox and resumes the video  
**Note:** the setting only applies at Firefox startup, which is why the fix restarts it

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

### Fixed in this round

- **`vt doctor` always said the extension was missing** — the rename to
  GnomeSpeak changed the bus name in `cli.py` only, so doctor probed
  `org.gnome.Shell.Extensions.GnomeSpeak`, which nothing has ever exported. The
  name now lives once, in `vt/shell.py`.
- **The rename left a dangling extension symlink** — an install from before it
  is `voicetalk@local` pointing into a directory the rename deleted. GNOME
  Shell drops such an extension silently, so windows, workspaces and tab
  control all stopped at once with nothing on screen to say why.
  `vt install-extension` now removes it (and drops it from
  `org.gnome.shell enabled-extensions`), and `vt doctor` names the state.
- **`gnome-extensions enable` cannot enable a newly copied extension** — the
  running shell only scans the extensions directory at session start, so it
  answered "does not exist" and the printed fallback was the same failing
  command. The uuid is written straight into the dconf enabled list instead.
- **A missing extension was invisible on the phone** — `system:extension` is
  now a snapshot target, so the System tab and the touchpad screen say it once
  instead of every dependent feature failing separately.
- **Clipboard writes reported a timeout on success** — `wl-copy` forks a
  process that owns the selection, and it inherited the stderr *pipe*, so
  `subprocess.run` waited out its full timeout on a copy that had already
  worked.

### Would Require New Dependencies
- **WebDriver playback control** — Chromium or Firefox WebDriver to control videos (heavy, user's browser)
- **Native video metadata** — ffprobe/mediainfo for local videos (new source type)
- **Text-to-speech feedback** — espeak or pyttsx3 (invasive for a remote control)

### Would Require User Input Channel
- **Phrase parsing / NLP** — vt's design stays: concrete controls, no guessing.
  (Typing literal text at the PC is now supported, but it is a keyboard, not an
  interpreter -- the phone sends characters, vt does not read them.)
- **Multi-step workflows** — "search for X, then play the second result" (would need state machine)

### Still Missing (see FEATURE_PARITY.md)
- **Screen mirroring / screenshots** — needs the portal or PipeWire screencast;
  scrot and ImageMagick are X11-only
- **Find-my-phone / ring** — needs a persistent phone-side connection
  (WebSocket), not the 1 Hz poll the UI is built on
- **Phone battery on the PC** — same reverse channel
- **Per-app volume mixer** — wpctl can do it; the snapshot has no per-app node model yet

## Known Issues (Won't Fix / By Design)

1. **Snap confinement** — snapd policy intentionally isolates confined apps; use real terminal
2. **Wayland keystrokes** — Wayland security model blocks input synthesis; use MPRIS instead
3. **Firefox MPRIS gap** — Firefox only exposes MPRIS when at least one media element is playing; can't pre-stage controls. Press play once in the tab and the player appears under Players.
4. **Firefox cannot seek** — Firefox advertises `CanSeek=true` but implements neither `Seek` nor `SetPosition`. Calling either does not move playback and permanently resets the player's reported `Position` to 0 and drops `mpris:length` for the rest of the track. vt therefore withholds seek for Firefox and explains why on the target. Verified against Firefox 154 (snap), GNOME 50, Wayland. Seek in the page instead.
5. **Window IDs** — GNOME extension stable window IDs work only on GNOME (no KDE/XFCE support)
6. **Android app** — v3 is CLI + web UI; native Android would need separate codebase

## Testing Checklist

- [x] 270 unit tests passing
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

# For Cloudflare Tunnel (global access)
# Download from: https://github.com/cloudflare/cloudflared/releases
# Or: sudo apt install cloudflared
```

### Environment Requirements
- **Linux** — GNOME Shell 45+, systemd, PipeWire/ALSA
- **Python** — 3.11+
- **Session** — Wayland or X11 (both supported; feature set varies)
- **Network** — LAN access from phone to PC; Cloudflare tunnel for global access

## Future Directions (Out of Scope for v3)

- **Desktop recording** — ffmpeg integration for screen capture and playback
- **Voice input** — speech-to-text and intent matching (adds complexity; vt avoids this)
- **Media library** — Plex, Jellyfin, Kodi integration (separate control domain)
- **Brightness/backlight** — systemd-logind or ACPI tools (power management)
- **Network streams** — mpv remote control for streaming (MPRIS covers most use cases)

## Stable Release Readiness

**Current:** `v3.1.0` on PyPI — design frozen  
**Blockers:** None — all known issues are documented limitations or by-design trade-offs  
**Test status:** 287 tests, all passing  
**CI/CD:** GitHub Actions, Python 3.11–3.13, with and without optional deps

The v2 tree (`client/`, `server/`, its OpenSpec specs, and the v2 root test
scripts) was removed in the release commit; it remains recoverable in git
history at `v2.2.0` and earlier.
