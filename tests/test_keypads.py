"""Tests for the per-application key pads.

The rule the tests exist to hold: the phone sends the *name* of a key, never a
chord. A pad is a fixed table, so a request that is not in it is a request for
a key the application was never said to answer -- and nothing reaches the
compositor for it.
"""

from vt.actions import execute_action
from vt.sources import keypads
from vt.sources.remote_input import valid_chord


def window(wm_class, title="A window", focused=True):
    return {"wm_class": wm_class, "title": title, "focused": focused}


def test_every_chord_in_the_table_is_one_the_extension_knows():
    """A pad that offers a key the compositor cannot send is a dead button."""
    bad = [(pad, action, chord)
           for pad, _t, _i, _f, keys in keypads.KEYPADS
           for action, _label, chord in keys if not valid_chord(chord)]
    assert bad == []


def test_action_ids_are_unique_within_a_pad():
    for pad, _t, _i, _f, keys in keypads.KEYPADS:
        ids = [action for action, _label, _chord in keys]
        assert len(ids) == len(set(ids)), f"{pad} repeats an action id"


def test_the_focused_browser_gets_the_browser_pad():
    targets = keypads.get_keypad_targets([window("org.mozilla.firefox")])
    assert [t.id for t in targets] == ["keys:browser"]
    assert "new_tab" in [a.id for a in targets[0].actions]


def test_a_window_that_is_not_focused_gets_no_pad():
    assert keypads.get_keypad_targets([window("vlc", focused=False)]) == []


def test_an_application_with_no_table_entry_gets_no_pad():
    """No guessed keys: an app we know nothing about gets nothing."""
    assert keypads.get_keypad_targets([window("com.example.SomeApp")]) == []


def test_no_windows_at_all_is_not_an_error():
    assert keypads.get_keypad_targets([]) == []
    assert keypads.get_keypad_targets(None if False else []) == []


def test_the_pad_names_the_window_it_reaches():
    targets = keypads.get_keypad_targets([window("vlc", "Cars 2.mkv")])
    assert targets[0].subtitle == "Cars 2.mkv"


def test_a_variant_spelling_still_matches():
    for spelling in ("Firefox", "firefox-esr", "org.mozilla.firefox"):
        assert keypads.get_keypad_targets([window(spelling)]), spelling


def test_an_unknown_key_name_sends_nothing(monkeypatch):
    monkeypatch.setattr(
        "vt.sources.remote_input.send_keys", _must_not_run
    )
    result = keypads.execute("vlc", "self_destruct")
    assert result["ok"] is False


def test_a_key_name_from_another_pad_is_refused(monkeypatch):
    """"reopen_tab" is a browser key; asking VLC for it must not send ctrl+shift+t."""
    monkeypatch.setattr("vt.sources.remote_input.send_keys", _must_not_run)
    assert keypads.execute("vlc", "reopen_tab")["ok"] is False


def test_a_known_key_sends_its_chord(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "vt.sources.remote_input.send_keys",
        lambda chords: sent.append(chords) or {"ok": True, "message": "Sent"},
    )
    assert keypads.execute("browser", "reopen_tab")["ok"] is True
    assert sent == ["ctrl+shift+t"]


def test_the_dispatcher_routes_a_pad(monkeypatch):
    monkeypatch.setattr(
        keypads, "execute", lambda pad, action: {"ok": True, "message": f"{pad}/{action}"}
    )
    assert execute_action("keys:browser", "find")["message"] == "browser/find"


def _must_not_run(*args, **kwargs):
    raise AssertionError("a key that is not in the table reached the compositor")
