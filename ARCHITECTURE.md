# Architecture

## Overview

VoiceTalk is a Linux CLI that reports what is running on your PC and serves a
small web page any phone browser can open. There is no app to install, no voice
pipeline, and no language model — the phone shows real system state and invokes
a fixed set of concrete actions.

```
┌──────────────────────┐          ┌──────────────────────────────────────────┐
│   Phone browser      │          │   Linux PC — make dev                    │
│                      │          │                                          │
│  index.html          │  HTTP    │  ┌────────────────────────────────────┐  │
│  • polls /api/state  ├──────────┤  │ server.py (aiohttp)                │  │
│    once a second     │  1 Hz    │  │ • token auth (X-VT-Token)          │  │
│  • posts /api/do     │          │  │ • snapshot cache, refreshed at 1Hz │  │
│  • token in          │          │  │ • one worker thread for blocking   │  │
│    localStorage      │          │  └───────────┬───────────┬────────────┘  │
└──────────────────────┘          │              │           │               │
                                  │   state.py ──┘           └── actions.py  │
                                  │      │                          │        │
                                  │      ▼                          ▼        │
                                  │  ┌────────────────┐   ┌──────────────┐   │
                                  │  │ sources/       │   │ execute_     │   │
                                  │  │ • mpris.py     │   │ action()     │   │
                                  │  │ • windows.py   │   │              │   │
                                  │  │ • apps.py      │   │ wpctl        │   │
                                  │  │ • audio.py     │   │ D-Bus        │   │
                                  │  │ commands.py    │   │ pkill        │   │
                                  │  └───────┬────────┘   │ argv exec    │   │
                                  │          │            └──────┬───────┘   │
                                  └──────────┼───────────────────┼───────────┘
                                             ▼                   ▼
                                    D-Bus · PipeWire · /proc · GNOME Shell
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
| `sources/windows.py` | Open windows on the active workspace | GNOME extension |
| `sources/apps.py` | Running apps, matched to `.desktop` entries | `psutil` |
| `sources/apps.py` | Installed apps (`/api/apps`, not the snapshot) | — |
| `sources/youtube.py` | YouTube search results (`/api/youtube`, not the snapshot) | `yt-dlp` |
| `sources/audio.py` | Default sink volume and mute | `wpctl` (PipeWire) |
| `commands.py` | User-defined commands | `~/.config/gnomespeak/commands.toml` |

## The GNOME extension

`gnome-extension/gnomespeak@local/` exports three D-Bus methods on
`org.gnome.Shell.Extensions.VoiceTalk`: `List() → JSON`, `Focus(id)`, and
`Close(id)`. Window ids are Mutter stable sequences, which survive restacking.

It is optional. Without it, the Windows section is empty and app Focus fails
with a clear message — everything else works.

Two operational notes, both learned the hard way:

- **GNOME Shell caches extension ES modules.** `gnome-extensions disable`
  followed by `enable` re-runs the *old* code. Editing `extension.js` requires a
  full shell restart, which on Wayland means logging out and back in.
- **A JS exception inside the extension arrives as a D-Bus error**, exactly like
  the extension being absent. `actions.shell_error()` separates them: only
  `ServiceUnknown`/`NameHasNoOwner` mean "not installed"; anything else is
  reported verbatim. Collapsing the two once hid a live `TypeError` behind
  "GNOME extension not available" and sent debugging in the wrong direction.

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
| `POST /api/do` | token/device | `{target, action, value?}` → `{ok, message}` |

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

The Cloudflare tunnel provides HTTPS end-to-end. On the LAN, plain HTTP is the
documented trade-off — run it on a network you trust.

## Configuration

`~/.config/gnomespeak/commands.toml` (or `$XDG_CONFIG_HOME/gnomespeak/`):

```toml
[[command]]
id = "lock"
label = "Lock screen"
run = ["loginctl", "lock-session"]   # argv, never a shell string
icon = "🔒"
confirm = true                        # UI asks before running
```

Validation happens at load. Invalid entries are skipped with a message rather
than failing the server: a typo in one command should not take the remote down.
Ids may not shadow a built-in action name (`volume`, `mute`, `focus`, …), since
command targets are addressed as `command:<id>` with the action `run`.

## Testing

`pytest` covers models, sources, command validation, server auth, dispatch, and
the injection regressions. `tests/test_ui.py` runs the real UI render functions
under node with DOM stubs and asserts that hostile window titles come out as
text — the escaping is tested, not just read.

CI runs the suite on Python 3.11–3.13 with `dbus-python` installed, plus a
second job without it that asserts the degraded path still imports and serves.
