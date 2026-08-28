"""Keystroke injection for COSMIC via `zwp_virtual_keyboard_manager_v1`.

See COSMIC_INPUT_PARITY.md for the design rationale and the Phase 0 spike
that confirmed this compositor lets an ordinary client (not portal-brokered)
create a virtual keyboard and upload a keymap -- bind the manager, call
`create_virtual_keyboard()`, upload a keymap, and neither errors nor
disconnects, all without ever calling `key()`.

This module owns two things, and opens no Wayland connection of its own:
sources/cosmic_windows.py owns the one connection this process will ever
make (see its module docstring) and calls in here with an already-bound
`zwp_virtual_keyboard_v1` proxy.

1. **The bundled keymap** (`_cosmic_wayland/qwerty.xkb`). `keymap()` takes a
   file descriptor holding an XKB keymap in text form -- there is no "just
   start sending keys" shortcut, and this project only ever types a small,
   fixed vocabulary of chords, never arbitrary user text, so a static keymap
   generated once is enough. Regenerate it with:

       xkbcli compile-keymap --rules evdev --model pc105 --layout us \
           > vt/sources/_cosmic_wayland/qwerty.xkb

2. **The evdev keycode table and chord parser.** `key()` wants a Linux evdev
   keycode (KEY_A, KEY_1, ... from linux/input-event-codes.h), not a key name
   or an XKB keycode (XKB keycode = evdev + 8, the traditional X11 offset --
   verified against the bundled keymap's own `<KEYNAME> = N` lines, but
   irrelevant to the wire value `key()` actually sends). The chord vocabulary
   this project needs is small and enumerable -- letters from YouTube's
   shortcuts and Ctrl+W, digits for Firefox tab selection, arrows for
   YouTube seek/volume, a handful of specials -- so this is a hardcoded
   dict, not a general XKB-symbol-lookup layer.
"""

import os
import time
from pathlib import Path

_KEYMAP_PATH = Path(__file__).parent / "_cosmic_wayland" / "qwerty.xkb"

# wl_keyboard.keymap_format.xkb_v1 (wayland.xml) -- the only format
# zwp_virtual_keyboard_v1.keymap() accepts in practice.
_KEYMAP_FORMAT_XKB_V1 = 1

_KEY_RELEASED = 0
_KEY_PRESSED = 1

# Real-modifier bit positions. XKB's eight "real" modifiers (Shift, Lock,
# Control, Mod1..Mod5) always occupy bits 0-7 in that fixed order -- this is
# an XKB-wide convention, not something a keymap chooses -- and the bundled
# keymap's own `modifier_map` section confirms Control -> Mod bit 2 and Alt
# -> Mod1 -> bit 3 for this specific one.
_MOD_BITS = {"ctrl": 1 << 2, "alt": 1 << 3}

# Linux evdev keycodes (linux/input-event-codes.h), cross-checked against
# the bundled keymap's own `<KEYNAME> = evdev + 8` lines. See the module
# docstring for why this is a small fixed table rather than a symbol lookup.
_KEYCODES = {
    "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10,
    "f": 33, "j": 36, "k": 37, "l": 38, "m": 50, "w": 17,
    "up": 103, "down": 108, "left": 105, "right": 106,
    "escape": 1, "page_down": 109, "space": 57,
}

# Matches the GNOME extension's own timing (extension.js: FOCUS_SETTLE_MS /
# KEY_GAP_MS) -- Firefox drops keys sent before it has repainted since the
# window was activated or the previous key landed.
_FOCUS_SETTLE_S = 0.15
_KEY_GAP_S = 0.06


class UnknownKey(Exception):
    """A chord step named a key or modifier outside the fixed vocabulary above."""


def read_keymap() -> bytes:
    """The bundled keymap, NUL-terminated the way XKB_V1 requires."""
    return _KEYMAP_PATH.read_bytes() + b"\x00"


def upload_keymap(vkbd) -> None:
    """Upload the bundled keymap to a freshly created virtual keyboard.

    keymap() wants a real file descriptor, not a byte string -- memfd_create
    supplies one without touching the filesystem.
    """
    data = read_keymap()
    fd = os.memfd_create("vt-cosmic-keymap")
    try:
        os.write(fd, data)
        os.lseek(fd, 0, os.SEEK_SET)
        vkbd.keymap(_KEYMAP_FORMAT_XKB_V1, fd, len(data))
    finally:
        os.close(fd)


def _parse_step(step: str) -> tuple:
    """One "ctrl+alt+w"-shaped chord step -> (modifier bitmask, keycode)."""
    parts = step.split("+")
    key = parts[-1]
    if key not in _KEYCODES:
        raise UnknownKey(f"no evdev keycode for {key!r}")
    mods = 0
    for mod in parts[:-1]:
        if mod not in _MOD_BITS:
            raise UnknownKey(f"unknown modifier {mod!r}")
        mods |= _MOD_BITS[mod]
    return mods, _KEYCODES[key]


def send_chord(vkbd, chord: str) -> None:
    """Type a "ctrl+l,alt+3,escape" style chord into whatever holds focus.

    See actions.py's `_guarded` and windows.py's `_tab_chord` for how these
    strings get built -- same format as the GNOME extension's SendKeys.

    Each step announces its modifiers, taps its key, then clears the
    modifiers before the next step, mirroring a real keystroke rather than
    holding modifiers across steps (which would leave the compositor's
    modifier state stuck if a step in the middle ever failed).
    """
    steps = [s.strip() for s in chord.split(",") if s.strip()]
    for i, step in enumerate(steps):
        time.sleep(_FOCUS_SETTLE_S if i == 0 else _KEY_GAP_S)
        mods, keycode = _parse_step(step)
        now = int(time.monotonic() * 1000) & 0xFFFFFFFF

        if mods:
            vkbd.modifiers(mods, 0, 0, 0)
        vkbd.key(now, keycode, _KEY_PRESSED)
        vkbd.key(now, keycode, _KEY_RELEASED)
        if mods:
            vkbd.modifiers(0, 0, 0, 0)
