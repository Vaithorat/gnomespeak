"""Chord parsing and keymap upload for COSMIC's virtual-keyboard backend.

No Wayland connection involved -- these test the pure translation from chord
strings to key()/modifiers() calls, and that the bundled keymap is a real,
NUL-terminated file. See tests/test_cosmic_windows.py for the send_keys()
integration (activate + type through a fake connection).
"""

import os

import pytest

from vt.sources import cosmic_input


class _FakeVkbd:
    def __init__(self):
        self.calls = []

    def keymap(self, fmt, fd, size):
        # Read the fd while it's still open, proving it's a real, rewound,
        # correctly-sized memfd -- the same thing a compositor would do.
        data = os.read(fd, size)
        self.calls.append(("keymap", fmt, len(data)))

    def key(self, time_, key, state):
        self.calls.append(("key", key, state))

    def modifiers(self, depressed, latched, locked, group):
        self.calls.append(("modifiers", depressed, latched, locked, group))


def test_read_keymap_is_nul_terminated_xkb_text():
    data = cosmic_input.read_keymap()
    assert data.endswith(b"\x00")
    assert b"xkb_keymap" in data


def test_upload_keymap_sends_a_real_fd_of_the_right_size():
    vkbd = _FakeVkbd()
    cosmic_input.upload_keymap(vkbd)
    assert vkbd.calls == [
        ("keymap", cosmic_input._KEYMAP_FORMAT_XKB_V1, len(cosmic_input.read_keymap())),
    ]


def test_send_chord_presses_and_releases_with_modifiers(monkeypatch):
    monkeypatch.setattr(cosmic_input.time, "sleep", lambda s: None)
    vkbd = _FakeVkbd()
    cosmic_input.send_chord(vkbd, "ctrl+l,alt+3,escape")

    ctrl = cosmic_input._MOD_BITS["ctrl"]
    alt = cosmic_input._MOD_BITS["alt"]
    key_l = cosmic_input._KEYCODES["l"]
    key_3 = cosmic_input._KEYCODES["3"]
    key_esc = cosmic_input._KEYCODES["escape"]
    pressed, released = cosmic_input._KEY_PRESSED, cosmic_input._KEY_RELEASED

    assert vkbd.calls == [
        ("modifiers", ctrl, 0, 0, 0),
        ("key", key_l, pressed),
        ("key", key_l, released),
        ("modifiers", 0, 0, 0, 0),
        ("modifiers", alt, 0, 0, 0),
        ("key", key_3, pressed),
        ("key", key_3, released),
        ("modifiers", 0, 0, 0, 0),
        ("key", key_esc, pressed),
        ("key", key_esc, released),
    ]


def test_send_chord_skips_blank_steps(monkeypatch):
    monkeypatch.setattr(cosmic_input.time, "sleep", lambda s: None)
    vkbd = _FakeVkbd()
    cosmic_input.send_chord(vkbd, "k,,")
    assert vkbd.calls == [
        ("key", cosmic_input._KEYCODES["k"], cosmic_input._KEY_PRESSED),
        ("key", cosmic_input._KEYCODES["k"], cosmic_input._KEY_RELEASED),
    ]


@pytest.mark.parametrize("chord", ["ctrl+z", "shift+w", "meta+tab", "alt+"])
def test_send_chord_rejects_keys_and_modifiers_outside_the_fixed_vocabulary(monkeypatch, chord):
    monkeypatch.setattr(cosmic_input.time, "sleep", lambda s: None)
    with pytest.raises(cosmic_input.UnknownKey):
        cosmic_input.send_chord(_FakeVkbd(), chord)
