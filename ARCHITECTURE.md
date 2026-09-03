# Architecture

## Overview

GnomeSpeak is a Linux CLI that reports what is running on your PC and serves a
small web page any phone browser can open. There is no app to install, no voice
pipeline, and no language model — the phone shows real system state and invokes
a fixed set of concrete actions.

```
┌──────────────────────┐          ┌──────────────────────────────────────────┐
│   Phone browser      │          │   Linux PC — vt serve                    │
│                      │   WS     │                                          │
│  index.html          │◄────────►│  ┌────────────────────────────────────┐  │
│  • holds /ws, gets   │  patches │  │ server.py (aiohttp)                │  │
│    only what changed │          │  │ • token auth (X-VT-Token)          │  │
│  • polls /api/state  │  HTTP    │  │ • device auth (X-VT-Device/Secret) │  │
│    when it cannot    ├──────────┤  │ • snapshot cache, refreshed at 1Hz │  │
│  • posts /api/do     │          │  │ • one worker thread for blocking   │  │
│  • credential in     │          │  └──┬────────┬───────────┬────────────┘  │
│    localStorage      │          │     │        │           │               │
└──────────────────────┘          │ live.py   state.py   actions.py          │
                                  │     │        │           │               │
                                  │     ▼        ▼           ▼               │
                                  │  ┌────────────────┐  ┌──────────────┐    │
                                  │  │ sources/       │  │ execute_     │    │
                                  │  │ • mpris.py     │  │ action()     │    │
                                  │  │ • windows.py   │  │              │    │
                                  │  │ • apps.py      │  │ wpctl        │    │
                                  │  │ • audio.py     │  │ D-Bus        │    │
                                  │  │ • monitor.py   │  │ pkill        │    │
                                  │  │ commands.py    │  │ argv exec    │    │
                                  │  └───────┬────────┘  └──────┬───────┘    │
                                  └──────────┼──────────────────┼────────────┘
                                             ▼                  ▼
                          D-Bus · PipeWire · /proc · portals · GNOME Shell
```

`vt/cli.py` is the other entry point. `vt status` prints the same snapshot
`/api/state` returns, and `vt do` calls the same `execute_action` the server
calls — the CLI and the web UI cannot drift apart.

## The model

Everything the user can act on is a **Target**; everything they can do to it is
an **Action** (`vt/model.py`).

```python
Target(id="mpris:org.mpris.MediaPlayer2.firefox", kind="player",
       title="Cars 2", subtitle="Firefox", status="playing",
       position=812.0, length=6132.0,
       actions=[Action(id="play_pause", label="Pause"), ...])
```

- `id` is always `"<kind>:<spec>"`. The dispatcher splits on the first colon,
  so the spec may contain colons of its own (MPRIS bus names do).
- `kind` is one of `player`, `window`, `app`, `system`, `command`, `launcher`, `youtube`.
- Actions are **capability-driven**: a player that reports `CanGoNext = false`
  gets no Next button. The UI renders what the snapshot offers and nothing more.
- `Action.kind` is `button`, `slider` (a 0..1 value), or `confirm` (destructive;
  the UI asks first).

## Sources

`vt/state.py` assembles one `Snapshot` per refresh by calling each source in
turn. Every source degrades to `[]` rather than raising, so a missing optional
dependency costs you one section of the UI, not the server.

| Source | Reads | Requires |
| --- | --- | --- |
| `sources/mpris.py` | Players, metadata, position, capabilities | `python3-dbus` |
| `sources/art.py` | Album art for playing track (`/api/art`, not snapshot) | `python3-dbus` |
| `sources/windows.py` | Open windows on the active workspace | GNOME extension, or `sources/cosmic_windows.py` |
| `sources/cosmic_windows.py` | Wayland foreign toplevel window control | `pywayland` (optional extra: `wayland`) |
| `sources/cosmic_input.py` | Wayland virtual keyboard keystroke injection | `pywayland` (optional extra: `wayland`) |
| `sources/firefox.py` | Open tabs from Firefox recovery session store | `lz4` (built-in fallback parser) |
| `sources/apps.py` | Running apps, matched to `.desktop` entries | `psutil` |
| `sources/apps.py` | Installed apps (`/api/apps`, not the snapshot) | — |
| `sources/audio.py` | System volume, per-stream mixers, sink/source devices | `wpctl` (PipeWire) |
| `sources/youtube.py` | YouTube search results (`/api/youtube`, not snapshot) | `yt-dlp` |
| `sources/youtube_player.py` | YouTube Wayland media keys & fullscreen/close-tab | GNOME extension or `cosmic_input.py` |
| `sources/browser_autoplay.py`| Firefox autoplay policy verification and fix | — |
| `sources/workspaces.py` | Workspace listing and switching | GNOME extension |
| `sources/bluetooth.py` | Bluetooth adapter radio, paired devices, battery levels | `python3-dbus` (BlueZ) |
| `sources/streaming.py` | Streaming shortcuts (desktop app or web fallback) | — |
| `sources/steam.py` | Installed Steam games from library manifests | — |
| `sources/system.py` | Lock, suspend, restart, shutdown, brightness, DND, battery | `systemd-logind`, `gsettings`, UPower |
| `sources/network.py` | Wi-Fi radio on/off and saved connection switching | `python3-dbus`, NetworkManager |
| `sources/clipboard.py` | The PC clipboard (`/api/clipboard`, not snapshot) | `wl-clipboard`, or `xclip`/`xsel` |
| `sources/clipboard_history.py` | Last copied clips (`/api/clipboard/history`, not snapshot) | a clipboard tool |
| `sources/remote_input.py` | Pointer, typing and chords write-only (`/api/input`) | GNOME extension |
| `sources/notifications_mirror.py` | Desktop notifications (`/api/notifications`, not snapshot) | `dbus-monitor` |
| `sources/transfer.py` | Files sent from phone (`/api/files`, not snapshot) | — |
| `sources/monitor.py` | CPU, memory, disk, thermals, uptime (`system:machine`) | `psutil` |
| `sources/disks.py` | Removable drives and safe ejection | `psutil`, `udisksctl` |
| `sources/keypads.py` | Contextual shortcut keys for focused app | GNOME extension / COSMIC input |
| `sources/ring.py` | Ring this PC alarm sound | `canberra-gtk-play`, `pw-play` or `paplay` |
| `sources/screenshot.py` | One still frame (`/api/screenshot`, not snapshot) | `org.freedesktop.portal.Screenshot` |
| `sources/wallpaper.py` | Set desktop background image (light/dark) | `gsettings` |
| `sources/open_url.py` | Open link in PC default browser | `xdg-open` / `gio` |
| `sources/wake.py` | Broadcast Wake-on-LAN magic packets | — |
| `notify.py` | PC low-battery notifications and banners | `notify-send` / libnotify |
| `push.py` | Encrypted Web Push delivery to service worker | `cryptography` (optional extra: `push`) |
| `schedule.py` | Timers held in memory (sleep timers, delayed actions) | — |
| `commands.py` | User-defined shell commands and multi-step macros | `~/.config/gnomespeak/commands.toml` |

Several of those are deliberately outside the 1 Hz snapshot. The clipboard, its
history, the notification feed, album art, a screenshot and the transferred-file
list are all things the phone asks for when a screen that shows them is open;
pushing them to every phone every second would be a poll that mostly re-sends
what nobody is looking at. Remote input is not state at all -- it produces
nothing to display, only deltas to apply, and it streams the other way at 20 Hz.

`procs.py` is what keeps the sources that shell out from adding up. A source
like `audio.py` or `system.py` needs several small subprocesses that spend
their whole lives waiting on someone else (`wpctl`, `gsettings`), so `run_all`
starts them together and collects them together rather than paying each one's
latency in turn on the single worker thread.

## The live channel

`vt/live.py` holds one WebSocket per phone (`GET /ws`) and sends only what
changed: a target whose title, status or actions differ from the copy that
phone already has. A PC with nothing happening therefore costs no traffic at
all, where the 1 Hz poll it replaces re-sent the whole snapshot every second on
mobile data.

Three details are load-bearing:

- **The ticket, not the credential.** A browser's WebSocket handshake cannot
  carry headers, and a device secret must never travel in a URL — a URL is
  logged by proxies, kept in history, and handed to the next page in a
  referrer. `POST /api/ws-ticket` mints a single-use, short-lived ticket
  instead, and the socket presents that.
- **An action wakes the collector.** Doing something and then waiting up to a
  second for the snapshot to notice is what made the UI feel remote. `/api/do`
  and `/ws` both nudge the collector, so the change comes back in roughly a
  quarter of a second.
- **The poll is still there.** A browser that cannot hold a socket, or a phone
  that just lost one, falls back to `GET /api/state` and loses nothing but the
  latency. Nothing is only reachable over the socket.

Pointer and scroll deltas ride the same socket in the other direction, which
replaced a POST every 50 ms, and notifications are pushed onto it by the mirror
as they arrive rather than found by the phone asking.

## Reaching a phone whose page is closed

A tab that is not open runs no code, so everything above stops at the moment
someone locks their phone. `vt/push.py` is the exception: a Web Push
subscription, encrypted per RFC 8291 and authorized per RFC 8292, posted to the
endpoint the browser handed back and delivered to `vt/ui/sw.js`. Both RFCs are
implemented here against `cryptography` rather than by adding a push library —
together they are about a hundred lines, and the RFC's own worked example is in
the test suite, so the code is checked against the standard rather than against
itself. Without the `push` extra every entry point degrades to "not available"
with a reason, like the rest of the sources.

`vt/ui/manifest.webmanifest` and `sw.js` are the other half of that page: a
home-screen icon, a fullscreen window, an offline "PC unreachable" screen
instead of a browser error, and a GnomeSpeak entry in Android's share sheet. A
share POST arrives at the service worker with no credential attached, so the
worker parks the payload and the page — which holds the credential — uploads it
through the ordinary endpoints.

## Running as a service, and on the LAN over TLS

`vt/service.py` writes a systemd **user** unit bound to
`graphical-session.target`. Not a system unit: every source vt reads — MPRIS,
the Shell extension, the session bus, PipeWire — lives in the desktop session
and does not exist outside it. The unit requires pairing, because a service
prints its startup banner where nobody will read it, so a token nobody has seen
must not be a way in; `vt pair` mints a code from a terminal instead.

`vt/tls.py` is the LAN half of the security story. Off-network traffic already
rides the tunnel's TLS; on the LAN the token travelled in a header over plain
HTTP, which anyone on the same Wi-Fi could read. A self-signed certificate is
the only kind a desktop can make for itself, so `vt serve --tls` is opt-in and
states the cost plainly: the phone warns once, and the fingerprint printed at
startup is what the person is meant to check. The certificate covers this
machine's LAN address, hostname and loopback, and is regenerated when that
address changes, since moving between networks would otherwise add a name
mismatch to the warning already on screen.

`vt/schedule.py` holds timers ("suspend in thirty minutes") in memory, checked
by the collector that already runs once a second. They die with the server on
purpose: a timer that survived a restart would fire against a desktop that has
been doing something else for an hour.

## The GNOME extension

`gnome-extension/gnomespeak@local/` exports one D-Bus interface,
`org.gnome.Shell.Extensions.VoiceTalk`, in three groups: windows (`List() →
JSON`, `Focus`, `Close`, `Minimize`, `Unminimize`, `Maximize`, `Unmaximize`),
workspaces (`MoveToWorkspace`, `SwitchWorkspace`, `Workspaces`) and input
(`SendKeys` into a named window; `Pointer`, `Click`, `Scroll`, `TypeText` and
`Keys` into whatever has focus). Window ids are Mutter stable sequences, which
survive restacking.

Under Wayland only the compositor may synthesize input, so the input group is
not an optimisation over `xdotool` — it is the only thing that works at all.

The bus name keeps its pre-rename spelling on purpose. It is a wire identifier
shared with an extension that reloads only at login, so changing it would break
every installed extension until its owner logged out, for no visible gain. Every
module reads it from `vt/shell.py`; the one time a copy of that string lived
somewhere else, the rename reached only that copy and `vt doctor` reported the
extension missing on machines where it was answering every call.

`make dev` installs it (`vt install-extension --if-needed`), so a fresh clone
has window and touchpad control at the developer's next login rather than after
a command nobody knew to run. That step is a no-op once the directory is present
and the uuid is in `org.gnome.shell enabled-extensions`, skips itself entirely
on a machine with no GNOME Shell, and never fails the run.

It is optional. Without it, the Windows section is empty, the touchpad says so
at the top of its own screen, app Focus fails with a clear message, and the
server says once at startup that it is not loaded — everything else works. `vt/shell.py` also reads the on-disk install state, so
"not active" can distinguish never installed, installed-not-yet-loaded, and the
dangling symlink a rename leaves behind.

Two operational notes, both learned the hard way:

- **GNOME Shell caches extension ES modules.** `gnome-extensions disable`
  followed by `enable` re-runs the *old* code. Editing `extension.js` requires a
  full shell restart, which on Wayland means logging out and back in.
- **A JS exception inside the extension arrives as a D-Bus error**, exactly like
  the extension being absent. `actions.shell_error()` separates them: only
  `ServiceUnknown`/`NameHasNoOwner` mean "not installed"; anything else is
  reported verbatim. Collapsing the two once hid a live `TypeError` behind
  "GNOME extension not available" and sent debugging in the wrong direction.

## Installing, and keeping the extension current

There are two supported ways in, and they differ in one thing only: where the
extension source lives.

- **From a checkout** — `make dev` installs the system packages that are
  missing, builds `venv/` with `--system-site-packages` (dbus-python and gi are
  distro packages and cannot be pip-installed), installs the project editable,
  and runs `vt install-extension --if-needed`. The extension is *symlinked*, so
  editing `extension.js` and logging back in is the whole edit cycle.
- **From PyPI** — `install.sh`, or `pip install gnomespeak` by hand. The
  extension travels in the wheel as data (`share/gnomespeak/gnome-extension/`),
  which is why `vt install-extension` works with no clone. Here it is *copied*,
  not symlinked: that directory belongs to pip, an upgrade or an uninstall
  takes it away, and GNOME Shell drops an extension whose directory is a
  dangling symlink without a word — the same silent failure the pre-rename
  `voicetalk@local` install produced.

Copying costs something the symlink did not: nothing else updates the copy. A
`pip install -U gnomespeak` replaces the source and leaves the extensions
directory alone, and an extension one version behind the server that calls it
is exactly what `vt doctor` reports as "running an older build", one failing
feature at a time. So `--if-needed` compares the integer `version` in both
`metadata.json` files and reinstalls when the shipped one is newer, which makes
`make dev` and `install.sh` self-repairing. `vt --version` prints both numbers
for the same reason.

`install.sh` also has to survive PEP 668. Ubuntu 24.04, Debian 12 and Fedora 39
onwards mark the system interpreter externally managed, and a bare
`pip install` there fails outright with `error:
externally-managed-environment`. The script prefers `pipx install
--system-site-packages` (the flag is not optional — without the system site
packages there is no dbus-python, so no media players and no window control),
falls back to `pip install --user --break-system-packages`, and says which it
chose and why.

## COSMIC window control

`sources/cosmic_windows.py` is the fallback `sources/windows.py` reaches for
when the GNOME extension isn't there. COSMIC (System76's Smithay-based
compositor) has no in-process extension model and no D-Bus surface for window
management (`com.system76.CosmicComp` was checked by hand -- it exposes only
`Ei`, libei input-emulation for the remote-desktop portal, nothing for
listing or controlling windows). So this backend speaks COSMIC's own Wayland
protocols directly, via `pywayland` (optional dep, `gnomespeak[wayland]`):
`ext-foreign-toplevel-list-v1` for enumeration (title, app_id, and a
cross-connection-stable `identifier`), `cosmic-toplevel-info-unstable-v1` for
state (minimized/maximized), and `cosmic-toplevel-management-unstable-v1` for
control (activate/close/maximize/minimize). The bindings for these three are
vendored, generated code under `sources/_cosmic_wayland/` -- see that
package's docstring before touching the XML there, it explains a real
opcode-numbering bug this project hit once from trimming the wrong thing.

It differs from the GNOME extension in one structural way: **it is not
stateless.** Creating a second `pywayland.client.Display()` in the same
process after a prior one disconnected reliably crashed the process
(segfault, reproduced repeatedly), so this module opens exactly one
connection, lazily, on first use, and keeps it for the process's whole life --
`list_windows()`/`execute()` reuse it rather than reconnecting. The one
connection is also why a live Display left for the garbage collector at
interpreter shutdown segfaulted too: `atexit.register`s an explicit
`disconnect()`, which runs ahead of GC-driven finalization and doesn't.

**Keystroke injection.** `SendKeys`'s equivalent here is `send_keys()`, via
`zwp_virtual_keyboard_manager_v1` -- a standard wlroots-family protocol (not
COSMIC-specific), confirmed on this machine's COSMIC session by a Phase 0
spike (bind the manager, create a virtual keyboard, upload a keymap, check
for a protocol error -- see `COSMIC_INPUT_PARITY.md`) before any real
implementation was written. `send_keys()` activates the target toplevel, the
same way `SendKeys` does on the GNOME side, then types a chord through the
virtual keyboard; `sources/cosmic_input.py` owns the bundled static XKB
keymap (`_cosmic_wayland/qwerty.xkb`, generated once with `xkbcli
compile-keymap`, not compiled at runtime) and the small hardcoded evdev
keycode table the project's fixed chord vocabulary needs. Unlike the
toplevel globals, `zwp_virtual_keyboard_manager_v1` is optional to bind --
window listing/control still works without it, only `send_keys()` fails.
This closes the Firefox tab-switching, per-tab close, and YouTube-keys gaps
that `windows.py`/`youtube_player.py` used to route around by checking
`backend == "cosmic"`.

Workspace listing/switching is still not implemented, though the protocol
supports it -- see `_cosmic_wayland/__init__.py` for why the XML still
declares it. Unlike the keystroke gap above, this needs no input injection,
just a plain protocol call; it's independent of everything above and cheaper
to add.

## Server

`vt/server.py` is aiohttp with these routes:

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /` | none | Serves the UI; `?t=<token>` stores the token and reloads; `?p=<code>` opens pairing |
| `GET /api/session` | optional | Who am I, and do I need to pair? Always 200. |
| `POST /api/pair` | code | Trade a one-time code for a device credential |
| `POST /api/pair/self` | token | An authenticated session mints its own device (zero-friction LAN upgrade) |
| `GET /api/devices` | device | List paired devices (no secrets) |
| `POST /api/devices/revoke` | device | Drop a device credential |
| `GET /api/state` | token/device | Current snapshot as JSON |
| `GET /api/apps` | token/device | Installed apps, optionally filtered by `?q=` |
| `GET /api/youtube` | token/device | YouTube videos, searched by `?q=` |
| `GET /api/youtube/related` | token/device | What to watch after the video already playing |
| `POST /api/do` | token/device | `{target, action, value?}` → `{ok, message}` |
| `POST /api/ws-ticket` | token/device | Trade a credential for a single-use socket ticket |
| `GET /ws` | ticket | The live channel: patches out, pointer deltas in |
| `GET /api/clipboard` | token/device | The PC's clipboard as text |
| `POST /api/clipboard` | token/device | `{text}` → put it on the PC's clipboard |
| `GET`/`DELETE /api/clipboard/history` | token/device | The last few things copied, or forget them |
| `POST /api/input` | token/device | `{op: move\|click\|scroll\|type\|keys, ...}` |
| `GET /api/notifications` | token/device | Desktop notifications after `?since=<seq>` |
| `POST /api/notifications/dismiss` | token/device | `{id}` → Close one on the PC |
| `POST /api/notifications/mute` | token/device | Do not disturb, from the phone |
| `GET /api/push/key` | token/device | The VAPID public key the browser subscribes with |
| `POST /api/push/subscribe` · `/unsubscribe` | token/device | Register or drop a Web Push endpoint |
| `GET /api/screenshot` | token/device | One still frame, through the portal, then deleted |
| `GET /api/art` | token/device | Album art for the playing track, by key |
| `GET /api/diagnostics` | token/device | `vt doctor`, rendered on the phone |
| `POST /api/open` | token/device | `{url}` → open an http(s) link on the PC |
| `POST /api/wake` | token/device | `{mac}` → a wake-on-LAN packet to another machine |
| `POST /api/probe` | token/device | Ask whether another machine on the LAN is up |
| `GET /api/audit` | device | The security log, from the phone |
| `GET /api/files` | token/device | What has been transferred, newest first |
| `POST /api/upload` | token/device | Multipart `file` field, streamed to disk |
| `GET /api/files/{name}` | token/device | Download one transferred file |
| `POST /api/files/open` | token/device | `{name}` → open it on the PC |
| `POST /api/files/wallpaper` | token/device | `{name}` → make it the desktop background |
| `POST /share` | none | Where Android's share sheet posts; the worker normally catches it first, and the server's reply only explains why it did not |
| `GET /{name}` | none | Static PWA assets (`sw.js`, `manifest.webmanifest`, app icons) |

**Why remote input is not an action.** `/api/do` looks a target up in the
snapshot and writes an audit line per call. A trackpad has no target and sends
twenty deltas a second, which would bury every other line in the log. `/api/input`
therefore skips both, and audits only what was typed and which chords were sent
— the parts anyone reading the log afterwards would actually want.

**Why installed apps are not in the snapshot.** They are a different kind of
data: hundreds of rows that change about once a week, against a snapshot of a
handful of rows that change every second. Folding them in would have made every
1 Hz poll, from every phone, mostly a re-send of the applications menu. `/api/apps`
is fetched once when the user opens the list; the search then filters client-side,
so typing costs the PC nothing. The scan behind it is cached for 60 seconds, which
is also what lets a long-running server notice an app installed after startup.

Launching goes back through the ordinary `/api/do` path as `launcher:<desktop-id>`
with the action `launch`, so the CLI reaches it too (`vt do launcher:firefox launch`).
`gio launch` runs the entry when glib's CLI is present, because it applies the
desktop file's own semantics — field codes, `Terminal=true`, `DBusActivatable` —
instead of our approximation of them; the parsed argv is the fallback. Either way
the child gets its own session, so Ctrl+C on `vt serve` does not close the browser
it just opened.

**Concurrency.** Snapshot collection and action execution are both blocking
(subprocess, D-Bus). They run on a single-worker `ThreadPoolExecutor`, not the
event loop: a configured command with a 10-second timeout used to stall every
other request. One worker, not a pool — python-dbus shares a connection, so the
calls must stay serialized.

**Snapshot cache.** A background task refreshes at 1 Hz and `/api/state` serves
the cached copy, so N phones cost the same as one.

## YouTube Search

`/api/youtube` searches YouTube using `yt-dlp` and returns video metadata: id,
title, channel, duration, and a watch URL. The search has a 5-second timeout and
returns up to 15 results. The phone renders them as clickable items that open in
the browser. The search is live: typing updates results in real time, cached for
0.6 seconds to avoid hammering yt-dlp.

## D-Bus under confinement

Two operational lessons live in the D-Bus code.

**Nothing introspects.** Every proxy is built with `introspect=False`, since the
interface is always named explicitly a line later. The round trip bought nothing
and cost a great deal: a player that refuses `Introspect` made dbus-python log an
error of its own, for every player, on every 1 Hz refresh. The one thing
introspection did provide was argument signatures, so `Seek` now passes an
explicit `dbus.Int64` — a bare Python int would be guessed as int32 and rejected.

**AccessDenied is not "no players".** A `vt` started from a snap's built-in
terminal — the VS Code snap's, most often — inherits that snap's AppArmor label,
and snapd's policy then blocks it from reaching other snaps. Snap-packaged
Firefox refuses every property read, `_get` returns the default, the player is
dropped for want of a `PlaybackStatus`, and the UI shows exactly what it shows
when nothing is playing. The denial is now recognised, reported once with the
confinement label that caused it (`actions.confinement_label`), and checked by
`vt doctor`, which reads a real property rather than trusting the bus-name list.
No code can lift the policy: the fix is to start `vt` from an ordinary terminal.

## Security model

Two tiers of access, deliberately unequal:

- **LAN** — the startup token in the URL is enough. It travels in a bookmark
  and a QR code, which is fine for a network you already control.
- **Remote** — the token is not accepted at all. The caller must present a
  paired-device credential, and a device is paired once, from a code that only
  ever appears on this PC's own terminal.

That split is the whole security model: exposing the public URL leaks nothing,
because the URL is not a credential off-network.

1. **Token auth.** A 22-character `secrets.token_urlsafe(16)` is generated per
   run and required on every `/api/*` request from the LAN, compared with
   `secrets.compare_digest`. `--no-token` disables it for LAN callers.
2. **Device pairing.** `vt pair` mints a 31^10-entropy, single-use, 10-minute
   code. Redeeming it registers a device with a 32-byte random secret (SHA-256
   hashed for storage). The device presents `X-VT-Device` + `X-VT-Secret`
   headers on every request. Max 32 devices.
3. **Rate limiting.** 5 failed auth attempts per IP triggers a 15-minute
   lockout. Pairing attempts are rate-limited globally (30/hour).
4. **Audit log.** Every authenticated action and rejected attempt is recorded
   in `~/.local/state/gnomespeak/audit.log` as JSONL.
5. **No arbitrary execution.** `/api/do` takes a target id and an action id, not
   a command. Configured commands are addressed by id; their `run` must be an
   argv list, and a string is rejected at load time — `subprocess` is never
   invoked with `shell=True`.
6. **Untrusted text stays text.** Window titles and MPRIS metadata are whatever
   the user has open — a web page title becomes a Firefox window title. The UI
   escapes every field it renders and passes data through `data-*` attributes
   rather than inline `onclick` handlers, because an inline handler puts the
   value through two parsers (HTML entities, then JS) and no single escape is
   correct for both. The token-capture page reads `?t=` from `location.search`
   in the browser instead of reflecting it into the response.
7. **Security headers.** CSP (nonce-based), HSTS, X-Frame-Options DENY,
   nosniff, no-referrer, COOP on every response.
8. **Scopes.** A device is paired `full` or `guest` (`vt pair --guest`), and a
   guest holds one capability: `media`. Power, input, files, the clipboard,
   notifications, screenshots and pairing are all refused for it. `vt pair
   --hours N` additionally gives a credential an expiry, so a visitor's phone
   stops working by itself rather than staying paired until someone remembers
   to revoke it.
9. **The socket is not a second front door.** `/ws` is reachable only with a
   ticket minted by an already-authenticated POST, single-use and good for
   seconds, and every action arriving over it goes through the same scope check
   as `/api/do`.

The Cloudflare tunnel provides HTTPS end-to-end. On the LAN, plain HTTP is the
default and `vt serve --tls` is the alternative: a certificate this machine
makes for itself, one browser warning, and a fingerprint printed at startup to
check it against (`vt/tls.py`).

## Configuration

`~/.config/gnomespeak/commands.toml` (or `$XDG_CONFIG_HOME/gnomespeak/`):

```toml
[[command]]
id = "lock"
label = "Lock screen"
run = ["loginctl", "lock-session"]   # argv, never a shell string
icon = "🔒"
confirm = true                        # UI asks before running

# Or a macro: sequential target-and-action steps with optional waits
[[command]]
id = "movie_mode"
label = "Movie mode"
icon = "🎬"
steps = [
  {target = "system:notifications", action = "dnd_on"},
  {target = "system:display", action = "night_light_on"},
  {wait = 0.5},
  {target = "system:audio", action = "volume", value = 0.4},
]
```

Validation happens at load. Invalid entries are skipped with a message rather
than failing the server: a typo in one command should not take the remote down.
Ids may not shadow a built-in action name (`volume`, `mute`, `focus`, …), since
command targets are addressed as `command:<id>` with the action `run`.

Macros define a `steps` list instead of `run`. Each step is either a target and
action pair (`{target, action, value?}`) or a delay (`{wait = seconds}`). Steps
never execute external binaries, keeping macros strictly bounded by the same
safe actions available to the phone. A macro aborts at the first step that fails.

## Testing

854 tests cover models, sources, command and macro validation, server auth,
dispatch, the live WebSocket channel and patch diffing, Web Push RFC 8291/8292
encryption, LAN TLS certificate generation, service management, and injection
regressions. `tests/test_ui.py` runs the real UI render functions under Node
with DOM stubs and asserts that hostile window titles come out as text — the
escaping is tested, not just read.

CI runs the suite on Python 3.11–3.14 with `dbus-python` installed, plus a
second job without it that asserts the degraded path still imports and serves.
