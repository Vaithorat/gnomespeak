"""Tests for how the snapshot is collected, not for what any source returns.

Two sources run on their own threads because they touch no D-Bus, and the
D-Bus sources stay on the calling thread because they share one connection.
The tests here pin both halves of that: nothing is dropped, and the sources
that must stay serialized still run one at a time on the thread that called.
"""

import threading
import time

import vt.state as state
from vt.model import Target


def target(tid, kind="system", title="Row"):
    return Target(id=tid, kind=kind, title=title)


def test_the_threaded_sources_land_in_the_snapshot(monkeypatch):
    monkeypatch.setattr(state, "get_app_targets", lambda: [target("app:x", "app", "X")])
    monkeypatch.setattr(state, "get_audio_targets", lambda: [target("system:audio")])

    ids = [t.id for t in state.get_snapshot().targets]

    assert "app:x" in ids and "system:audio" in ids


def test_a_slow_source_does_not_hold_up_the_others(monkeypatch):
    """The whole point: the app scan and the audio reads wait together."""
    monkeypatch.setattr(state, "get_app_targets", lambda: time.sleep(0.3) or [])
    monkeypatch.setattr(state, "get_audio_targets", lambda: time.sleep(0.3) or [])

    started = time.monotonic()
    state.get_snapshot()
    elapsed = time.monotonic() - started

    assert elapsed < 0.55, f"{elapsed:.2f}s looks like a queue, not two threads"


def test_the_dbus_sources_stay_on_the_calling_thread(monkeypatch):
    """They share one connection, so running two of them at once is a crash."""
    here = threading.current_thread().ident
    seen = {}

    def record(name):
        # *args because the snapshot hands the window list to the sources that
        # can reuse it rather than asking the extension twice.
        def source(*args, **kwargs):
            seen[name] = threading.current_thread().ident
            return []
        return source

    for name in ("get_mpris_targets", "get_window_targets", "get_workspace_targets",
                 "get_bluetooth_targets", "get_system_targets", "get_extension_targets"):
        monkeypatch.setattr(state, name, record(name))

    state.get_snapshot()

    assert seen, "no D-Bus source ran"
    assert set(seen.values()) == {here}


def test_a_source_that_raises_is_not_swallowed_into_an_empty_snapshot(monkeypatch):
    """A collection that half-failed must not look like a quiet desktop."""
    def explode():
        raise RuntimeError("wpctl went away")

    monkeypatch.setattr(state, "get_audio_targets", explode)

    try:
        state.get_snapshot()
    except RuntimeError:
        return
    raise AssertionError("the failure was hidden")
