"""Vendored pywayland bindings for COSMIC's window-management protocols, plus
keystroke injection.

Generated with `pywayland.scanner` from the upstream protocol XML files kept
alongside this module (cosmic-toplevel-*.xml, ext-foreign-toplevel-list-v1.xml,
virtual-keyboard-unstable-v1.xml, all untouched -- the last one vendored from
wlroots's own protocol/ directory, since it is no longer carried by
wayland-protocols or wlr-protocols) plus ext-workspace-v1-stub.xml, a local
stand-in for two external interfaces the real files reference but this
project never instantiates (see that file's own comment for why). Checked in
rather than generated at install/runtime, since that would require
`wayland-protocols`/`pywayland-scanner` on every machine `pip install`s this
package -- the whole point of shipping wheels.

qwerty.xkb is a different kind of vendored file -- not a protocol binding but
the static XKB keymap zwp_virtual_keyboard_v1.keymap() needs uploaded before
any key() call. Generated once, not from an XML file, with:

    xkbcli compile-keymap --rules evdev --model pc105 --layout us \\
        > vt/sources/_cosmic_wayland/qwerty.xkb

See sources/cosmic_input.py for what reads it.

IMPORTANT: never remove an individual <request>/<event> from the middle of a
vendored protocol XML to dodge a scanner dependency. The Wayland wire format
addresses events and requests by position (declaration order), not by name --
deleting one from the middle silently renumbers everything after it, so the
generated bindings decode a live compositor's messages as the wrong method
entirely. (This project did that once, trimming workspace-related members
out of the toplevel-info/-management XML, and it produced exactly that: a
"state" event that appeared to just never fire, and on a second connection in
the same process, a hard crash decoding a garbled opcode. The fix was
ext-workspace-v1-stub.xml -- stub the *external type*, never edit the real
protocol's own member list.)

Regenerate with:
    python -m pywayland.scanner -i /usr/share/wayland/wayland.xml \\
        vt/sources/_cosmic_wayland/*.xml -o <tmp-dir>
then copy the five protocol .py files back here (not wayland.py -- pywayland
already bundles core-protocol bindings at pywayland.protocol.wayland) and
replace their `from .wayland import ...` lines with
`from pywayland.protocol.wayland import ...`.
"""
