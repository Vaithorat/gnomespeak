"""The keys the focused application actually answers to.

Unified Remote's per-app remotes, built from parts that were already here: the
snapshot knows which window has focus, and the extension already sends key
chords to it. What was missing was the table -- VLC's keys over VLC, the
browser's over the browser -- so that the pad on the phone is a list of things
that work rather than a keyboard the user has to know.

Nothing is invented. Every chord below is a documented default of the
application it sits under, and an application with no entry gets no pad rather
than a guessed one.
"""

from vt.model import Target, Action
from vt.sources.remote_input import valid_chord

# (pad id, title, icon, [wm_class fragments], [(action id, label, chord)]).
# Matched against the focused window's wm_class, casefolded, as a substring:
# "org.mozilla.firefox", "firefox-esr" and "Firefox" are all one browser.
KEYPADS = [
    ("browser", "Browser keys", "🌐",
     ["firefox", "chromium", "chrome", "brave", "vivaldi", "epiphany", "zen"],
     [
         ("new_tab", "New tab", "ctrl+t"),
         ("close_tab", "Close tab", "ctrl+w"),
         ("reopen_tab", "Reopen closed", "ctrl+shift+t"),
         ("back", "Back", "alt+left"),
         ("forward", "Forward", "alt+right"),
         ("reload", "Reload", "ctrl+r"),
         ("find", "Find", "ctrl+f"),
         ("address", "Address bar", "ctrl+l"),
         ("fullscreen", "Fullscreen", "f11"),
     ]),
    ("vlc", "VLC keys", "🎬",
     ["vlc"],
     [
         ("play", "Play / pause", "space"),
         ("fullscreen", "Fullscreen", "f"),
         ("back10", "Back 10s", "left"),
         ("forward10", "Forward 10s", "right"),
         ("subtitles", "Subtitle track", "v"),
         ("audio_track", "Audio track", "b"),
         ("mute", "Mute", "m"),
         ("next", "Next", "n"),
         ("previous", "Previous", "p"),
     ]),
    ("mpv", "mpv keys", "🎬",
     ["mpv"],
     [
         ("play", "Play / pause", "space"),
         ("fullscreen", "Fullscreen", "f"),
         ("back5", "Back 5s", "left"),
         ("forward5", "Forward 5s", "right"),
         ("back60", "Back a minute", "down"),
         ("forward60", "Forward a minute", "up"),
         ("subtitles", "Subtitle track", "j"),
         ("mute", "Mute", "m"),
     ]),
    ("slides", "Presentation keys", "📽",
     ["impress", "libreoffice-impress", "soffice"],
     [
         ("start", "Start from first", "f5"),
         ("next", "Next slide", "right"),
         ("previous", "Previous slide", "left"),
         ("black", "Black screen", "b"),
         ("white", "White screen", "w"),
         ("end", "End show", "escape"),
     ]),
    ("terminal", "Terminal keys", "▮",
     ["ptyxis", "gnome-terminal", "konsole", "kitty", "alacritty", "wezterm",
      "foot", "xterm", "tilix"],
     [
         ("copy", "Copy", "ctrl+shift+c"),
         ("paste", "Paste", "ctrl+shift+v"),
         ("new_tab", "New tab", "ctrl+shift+t"),
         ("interrupt", "Interrupt (Ctrl+C)", "ctrl+c"),
         ("clear", "Clear", "ctrl+l"),
         ("search", "Search", "ctrl+shift+f"),
     ]),
    ("editor", "Editor keys", "⌨",
     ["code", "vscodium", "sublime_text", "gnome-text-editor", "gedit"],
     [
         ("save", "Save", "ctrl+s"),
         ("palette", "Command palette", "ctrl+shift+p"),
         ("find", "Find", "ctrl+f"),
         ("undo", "Undo", "ctrl+z"),
         ("redo", "Redo", "ctrl+shift+z"),
         ("comment", "Toggle comment", "ctrl+/"),
     ]),
    ("files", "File manager keys", "📁",
     ["nautilus", "org.gnome.nautilus", "nemo", "thunar", "dolphin"],
     [
         ("new_folder", "New folder", "ctrl+shift+n"),
         ("rename", "Rename", "f2"),
         ("delete", "Delete", "delete"),
         ("search", "Search", "ctrl+f"),
         ("up", "Up a folder", "alt+up"),
         ("back", "Back", "alt+left"),
     ]),
]


def _pad_for(wm_class: str, title: str = ""):
    """The pad matching a focused window, or None."""
    haystack = f"{wm_class} {title}".casefold()
    for pad_id, pad_title, icon, fragments, keys in KEYPADS:
        if any(fragment in haystack for fragment in fragments):
            return pad_id, pad_title, icon, keys
    return None


def chord_for(pad_id: str, action_id: str) -> str:
    """The chord an action sends, or "" when the pair is not in the table.

    The phone never sends a chord; it sends the name of one. A pad is a fixed
    list, so a request that does not match it is a request for a key this
    application was never said to answer.
    """
    for known_id, _title, _icon, _fragments, keys in KEYPADS:
        if known_id != pad_id:
            continue
        for known_action, _label, chord in keys:
            if known_action == action_id:
                return chord
    return ""


def get_keypad_targets(windows=None) -> list[Target]:
    """A pad for the focused window, when there is one worth showing."""
    if windows is None:
        from vt.sources.windows import list_windows

        windows = list_windows()

    focused = next((w for w in windows or [] if w.get("focused")), None)
    if not focused:
        return []

    pad = _pad_for(str(focused.get("wm_class") or ""), str(focused.get("title") or ""))
    if pad is None:
        return []

    pad_id, title, icon, keys = pad
    return [Target(
        id=f"keys:{pad_id}",
        kind="window",
        title=title,
        # The window's own name, so it is obvious which thing the keys reach.
        subtitle=str(focused.get("title") or "")[:60],
        icon=icon,
        status="focused",
        actions=[
            Action(id=action_id, label=label)
            for action_id, label, chord in keys if valid_chord(chord)
        ],
    )]


def execute(pad_id: str, action_id: str) -> dict:
    """Send one of a pad's keys to whatever has focus."""
    chord = chord_for(pad_id, action_id)
    if not chord:
        return {"ok": False, "message": f"Unknown key for {pad_id}: {action_id}"}
    from vt.sources.remote_input import send_keys

    return send_keys(chord)
