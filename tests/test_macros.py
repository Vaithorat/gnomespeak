"""Tests for macros: one button, several things the phone could have tapped.

The boundary that matters is the one that is *not* moved. A macro's steps name
targets and actions, never a program -- so `commands.toml` still cannot reach a
shell, and a macro is a sequence of things vt already does.
"""

import textwrap

import pytest

from vt import actions
from vt.commands import MAX_STEPS, MAX_WAIT, CommandsConfig


@pytest.fixture
def config(tmp_path, monkeypatch):
    """Write a commands.toml and load it."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    directory = tmp_path / "gnomespeak"
    directory.mkdir()

    def write(body: str) -> CommandsConfig:
        (directory / "commands.toml").write_text(textwrap.dedent(body))
        return CommandsConfig()

    return write


def test_a_macro_loads_with_its_steps(config):
    loaded = config('''
        [[command]]
        id = "movie"
        label = "Movie mode"
        steps = [
          {target = "system:notifications", action = "dnd_on"},
          {wait = 0.5},
          {target = "system:audio", action = "volume", value = 0.4},
        ]
    ''')
    assert loaded.get_errors() == []
    command = loaded.get_commands()[0]
    assert command["steps"][0] == {"target": "system:notifications", "action": "dnd_on"}
    assert command["steps"][1] == {"wait": 0.5}
    assert command["steps"][2]["value"] == 0.4


def test_a_plain_command_still_works(config):
    loaded = config('''
        [[command]]
        id = "notes"
        label = "Notes"
        run = ["gnome-text-editor"]
    ''')
    assert loaded.get_errors() == []
    assert loaded.get_commands()[0]["run"] == ["gnome-text-editor"]
    assert loaded.get_commands()[0]["steps"] == []


def test_a_command_cannot_be_both(config):
    loaded = config('''
        [[command]]
        id = "both"
        label = "Both"
        run = ["true"]
        steps = [{wait = 1}]
    ''')
    assert loaded.get_commands() == []
    assert "one or the other" in loaded.get_errors()[0]


def test_a_step_cannot_name_a_program(config):
    """The whole point: steps are taps, not argv, so no new path to a shell."""
    loaded = config('''
        [[command]]
        id = "sneaky"
        label = "Sneaky"
        steps = [{run = ["sh", "-c", "rm -rf ~"]}]
    ''')
    assert loaded.get_commands() == []
    assert loaded.get_errors()


def test_a_target_without_a_kind_is_refused(config):
    loaded = config('''
        [[command]]
        id = "bad"
        label = "Bad"
        steps = [{target = "audio", action = "mute"}]
    ''')
    assert loaded.get_commands() == []


def test_a_long_wait_is_refused(config):
    loaded = config(f'''
        [[command]]
        id = "sleepy"
        label = "Sleepy"
        steps = [{{wait = {MAX_WAIT + 1}}}]
    ''')
    assert loaded.get_commands() == []
    assert str(int(MAX_WAIT)) in loaded.get_errors()[0]


def test_a_negative_wait_is_refused(config):
    loaded = config('''
        [[command]]
        id = "backwards"
        label = "Backwards"
        steps = [{wait = -1}]
    ''')
    assert loaded.get_commands() == []


def test_too_many_steps_are_refused(config):
    steps = ", ".join(['{wait = 0.1}'] * (MAX_STEPS + 1))
    loaded = config(f'''
        [[command]]
        id = "long"
        label = "Long"
        steps = [{steps}]
    ''')
    assert loaded.get_commands() == []
    assert "more than" in loaded.get_errors()[0]


def test_an_empty_step_list_is_refused(config):
    loaded = config('''
        [[command]]
        id = "empty"
        label = "Empty"
        steps = []
    ''')
    assert loaded.get_commands() == []


# --- running ----------------------------------------------------------------

def macro(**overrides):
    command = {"id": "movie", "label": "Movie mode", "run": [], "icon": "", "confirm": False,
               "steps": [{"target": "system:notifications", "action": "dnd_on"},
                         {"target": "system:audio", "action": "volume", "value": 0.4}]}
    command.update(overrides)
    return command


def test_the_steps_run_in_order(monkeypatch):
    done = []
    monkeypatch.setattr(actions, "execute_action",
                        lambda t, a, v=None: done.append((t, a, v)) or {"ok": True, "message": ""})

    result = actions._run_macro(macro())

    assert result["ok"] is True
    assert done == [("system:notifications", "dnd_on", None),
                    ("system:audio", "volume", 0.4)]


def test_a_failed_step_stops_the_rest(monkeypatch):
    """"Mute, then suspend" must not suspend when the mute failed."""
    done = []

    def run(target, action, value=None):
        done.append(target)
        return {"ok": False, "message": "D-Bus went away"}

    monkeypatch.setattr(actions, "execute_action", run)
    result = actions._run_macro(macro())

    assert result["ok"] is False
    assert done == ["system:notifications"]
    assert "step 1" in result["message"] and "D-Bus went away" in result["message"]


def test_a_wait_is_honoured(monkeypatch):
    slept = []
    monkeypatch.setattr(actions, "execute_action", lambda *a, **k: {"ok": True, "message": ""})
    monkeypatch.setattr("time.sleep", slept.append)

    actions._run_macro(macro(steps=[{"wait": 0.25},
                                    {"target": "system:audio", "action": "mute"}]))

    assert slept == [0.25]


def test_the_dispatcher_runs_a_macro(monkeypatch, config):
    config('''
        [[command]]
        id = "movie"
        label = "Movie mode"
        steps = [{target = "system:audio", action = "mute"}]
    ''')
    done = []
    monkeypatch.setattr(actions, "execute_action",
                        lambda t, a, v=None: done.append(t) or {"ok": True, "message": ""})
    monkeypatch.setattr(actions.subprocess, "run", _must_not_run)

    result = actions.execute_command_action("movie")

    assert result["ok"] is True and done == ["system:audio"]


def _must_not_run(*args, **kwargs):
    raise AssertionError("a macro reached subprocess, which it must never do")
