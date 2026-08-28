# KDE Connect Feature Parity

Notes on overlap with KDE Connect and which of its features are worth
borrowing. Not a competitor analysis — KDE Connect is open source and DE-agnostic;
GnomeSpeak is a web UI (no phone app) tied into GNOME specifically. This is a
prioritized backlog of features to pull in.

## Already covered

- Media control (MPRIS players) — KDE Connect only does play/pause/next, we do
  full player state + capability-aware controls.
- App launching — KDE Connect has nothing like this.
- Window/workspace control — KDE Connect doesn't do this.

## Candidates, prioritized

### 1. Clipboard sync (bidirectional)
- Phone → PC: paste into a text box, server writes via `wl-clipboard`/`xclip`.
- PC → phone: browser Clipboard API, works since the Cloudflare tunnel is HTTPS.
- Effort: low. No GNOME extension changes needed.

### 2. File transfer
- Phone → PC: file input + upload endpoint, save to `~/Downloads`.
- PC → phone: simple file browser + download link.
- Effort: low-medium. Plain REST, no extension changes.

### 3. Remote input (phone as trackpad/keyboard)
- Touch gestures on the web page → input events on PC.
- Wayland blocks synthetic input from a normal process — needs uinput or a
  D-Bus call through the existing GNOME extension (same pattern as window
  focus/close today).
- Effort: high. Useful for presentation-remote use case.

### 4. Notification mirroring (PC → phone)
- Would need `dbus-monitor` on `org.freedesktop.Notifications` (`Notify` calls)
  pushed to the phone over the existing WebSocket.
- No official "read all notifications" API on Wayland; this is the common
  workaround other tools use, but it's fragile across GNOME versions.
- Effort: high.

### Not planned
- **SMS/phone notification mirroring** — out of scope, no phone-side app.
- **"Find my phone" / ring phone** — GnomeSpeak's phone UI is passive (only
  reachable when the page is open), can't push a ring to it.
- **Phone battery status on PC** — Battery Status API is removed from most
  mobile browsers now.

## Suggested order

Clipboard sync and file transfer first (low effort, no extension work,
high daily-use value). Remote input next if there's a concrete use case
(e.g. presentation remote). Notification mirroring last — highest effort,
most fragile.
