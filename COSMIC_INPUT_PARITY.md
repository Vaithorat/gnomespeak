# GNOME/COSMIC Feature Parity: Closing the Input-Injection Gap

## Context

`sources/windows.py` (GNOME) and `sources/cosmic_windows.py` (COSMIC) already
have parity on everything that is a plain protocol *request*: list windows,
focus, close, minimize, maximize. See `ARCHITECTURE.md`'s "COSMIC window
control" section for how that backend works.

What COSMIC is still missing is everything that requires **typing keystrokes
into a window** rather than sending it a structured command. On GNOME this
goes through the extension's `SendKeys(id, chord)`, which works because the
extension runs *inside* the compositor (GNOME Shell/Mutter/Clutter) and can
therefore synthesize input the way only a compositor is allowed to under
Wayland. `sources/cosmic_windows.py` has no equivalent, and three things fall
back to "not available on this backend" as a result (see `_send_keys()` /
`_execute_tab_action()` in `vt/actions.py`, and `sources/youtube_player.py`):

1. **Firefox tab-switching** — a multi-tab Firefox window's individual tabs
   (`_tab_targets()` in `windows.py`), addressed by typing `Alt+1..9` /
   `Ctrl+PageDown` into the window. COSMIC windows currently skip
   tab-expansion entirely rather than offer buttons that can't work.
2. **"Close tab"** on a single-tab (unexpanded) browser window — types
   `Ctrl+W`. COSMIC currently offers only "Close window".
3. **YouTube playback keys** (`sources/youtube_player.py`) — fullscreen
   toggle and close-tab specifically; **play/pause/seek/volume/mute already
   work identically on both backends**, because those go through MPRIS
   (`sources/mpris.py`), which is D-Bus and has nothing to do with the window
   manager. Fullscreen and "close tab" are the only two YouTube actions that
   are GNOME-only today.

There is also a **separate, unrelated, and much smaller gap**: workspace
listing/switching (`sources/workspaces.py`, `move_ws_*` actions in
`windows.py`) isn't implemented for COSMIC at all yet. Unlike the three items
above, this needs no keystroke injection — it's a plain protocol call
(`ext-workspace-v1` or `cosmic-workspace-unstable-v1`, the same request/event
shape as the toplevel-management work already done), deliberately deferred
during that work rather than tackled now. Worth doing, but it's independent
of everything below and considerably cheaper — see "Recommended order".

## The protocol: `zwp_virtual_keyboard_manager_v1`

Confirmed present on this machine's COSMIC session (`vt doctor` / the
registry dump from the window-control work both saw `zwp_virtual_keyboard_
manager_v1 v1`). It's the standard wlroots-originated protocol (also used by
`wtype`, `ydotool`'s Wayland backend, etc.), not COSMIC-specific — so unlike
the toplevel protocols, whatever gets built here should transfer to a future
wlroots-family backend (Sway, Hyprland, ...) largely unchanged.

Shape (from `virtual-keyboard-unstable-v1.xml`):

```
zwp_virtual_keyboard_manager_v1.create_virtual_keyboard(seat) -> zwp_virtual_keyboard_v1

zwp_virtual_keyboard_v1.keymap(format, fd, size)   # once, before any key()
zwp_virtual_keyboard_v1.key(time, key, state)      # key = Linux evdev keycode, not a keysym
zwp_virtual_keyboard_v1.modifiers(depressed, latched, locked, group)
```

Three real pieces of work, not one:

1. **A keymap to upload.** `keymap()` takes a file descriptor holding an XKB
   keymap in text form (the same format `wl_keyboard.keymap` hands *to*
   clients) — there is no "just start sending keys" shortcut. The lowest-risk
   route is a **static, bundled QWERTY keymap** (a few hundred lines of fixed
   XKB text, generated once and checked in, the same way `wtype` and similar
   tools do it) rather than pulling in `libxkbcommon`/`python-xkbcommon` as a
   new dependency just to compile one at runtime. A static keymap is also
   sufficient here: the project only ever needs to type a small, fixed
   vocabulary of chords (see below), never arbitrary user text.
2. **Evdev keycodes, not key names.** `key()` wants a Linux evdev keycode
   (`KEY_A`, `KEY_1`, ...; XKB keycode = evdev + 8, the traditional X11
   offset — matters only if cross-checking against the keymap, not for the
   wire value itself). The chord vocabulary this project actually needs is
   small and enumerable, not general-purpose:
   - Letters: `k j l m f w` (YouTube keys + `ctrl+w`) — from `_TAB_KEYS` /
     `_KEYS` in `youtube_player.py` and the close-tab chord in `actions.py`.
   - Digits `1`-`9` (tab selection) and arrows (`up`/`down`/`left`/`right`,
     YouTube seek/volume).
   - Modifiers `ctrl`, `alt`; specials `escape`, `page_down`, `space`.
   That's on the order of 25 keys — a hardcoded `dict[str, int]` of evdev
   codes, not a general XKB-symbol-lookup layer.
3. **Modifier state**, tracked separately from `key()`. A chord like
   `ctrl+w` isn't "hold ctrl, press w" at the wire level the way it reads in
   this project's chord strings — it's a `modifiers()` call announcing Ctrl
   depressed, then `key()` for W, then another `modifiers()` clearing it (and
   the existing chord parser — `_chord_for`, `_guarded`, `_tab_chord` in
   `actions.py`/`windows.py`/`youtube_player.py` — already produces
   multi-step sequences like `"ctrl+l,alt+3,escape"`, so this mostly slots
   into the same place `SendKeys` is called today rather than requiring a new
   chord representation).

## Open question to resolve first (Phase 0)

Whether COSMIC lets an ordinary client (not portal-brokered, not a
compositor-trusted process) create a virtual keyboard at all. Some
compositors gate `zwp_virtual_keyboard_manager_v1` behind
`wp_security_context_manager_v1` or an equivalent trust boundary for
exactly the reason this document exists — unrestricted synthetic input is a
real capability to hand out. `com.system76.CosmicComp`'s D-Bus `Ei`
interface (libei, used by the XDG remote-desktop portal for screen-sharing
input) suggests COSMIC may expect input injection to go through the portal
route rather than this raw protocol; if so, the right implementation is
different (portal `RemoteDesktop.NotifyKeyboardKeycode` over D-Bus/libei,
with a one-time user consent dialog) and meaningfully heavier — a portal
session, not a Wayland global bind.

**Test this before writing any real implementation**, the same way the
toplevel-management work started with a spike (see `ARCHITECTURE.md`): bind
`zwp_virtual_keyboard_manager_v1`, call `create_virtual_keyboard()`, upload a
keymap via `keymap()`, and check for a protocol error or disconnect —
**without ever calling `key()`**, so the spike can't type into whatever the
user's session happens to be focused on. If binding + keymap upload succeed
cleanly, the raw-protocol route is viable. If it's rejected, this document's
plan changes to a portal-based one.

## Effort estimate

| Piece | Effort | Notes |
| --- | --- | --- |
| Workspace switching (COSMIC) | Low | Same shape as existing toplevel work; independent of everything else here |
| Phase 0 permission spike | Low | A few hours; answers whether the rest of this is buildable as designed |
| Static XKB keymap asset | Low-Medium | One-time; copy a known-working minimal keymap rather than generating one |
| Evdev keycode table + modifier tracking | Low | Small fixed vocabulary, see above |
| Wiring into `actions.py`/`youtube_player.py` | Medium | The chord-string plumbing already exists; needs a COSMIC-side `_send_keys` equivalent and the same `backend == "cosmic"` gating pattern removed once this lands |
| **If Phase 0 says "use the portal instead"** | High | New D-Bus/libei code path, user consent UX, materially different design |

## Recommended order

1. Workspace switching for COSMIC — cheapest, fully decoupled, closes one of
   the four gaps on its own.
2. Phase 0 spike (above) — cheap, and gates whether 3-5 below are worth
   starting at all in their current design.
3. Static keymap + evdev table, as a small standalone module
   (`sources/_cosmic_wayland/` alongside the existing vendored protocol
   bindings feels like the right home, or a new `sources/cosmic_input.py`).
4. Wire it into `sources/cosmic_windows.py`'s connection (same one Wayland
   connection already open — see its module docstring on why there is only
   ever one) as a `send_keys(identifier, chord)` alongside `execute()`.
5. Remove the `backend == "cosmic"` gates in `windows.py` and
   `youtube_player.py` that currently skip tab-expansion, close-tab, and
   fullscreen for this backend, now that they have somewhere to go.
