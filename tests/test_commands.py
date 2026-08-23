"""Tests for commands.toml loading and validation."""

import textwrap

import pytest

from vt.commands import CommandsConfig


@pytest.fixture
def config_for(tmp_path, monkeypatch):
    """Build a CommandsConfig against a throwaway XDG_CONFIG_HOME."""

    def build(toml: str | None):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        if toml is not None:
            d = tmp_path / "voicetalk"
            d.mkdir(exist_ok=True)
            (d / "commands.toml").write_text(textwrap.dedent(toml))
        return CommandsConfig()

    return build


def test_no_config_file_is_not_an_error(config_for):
    config = config_for(None)
    assert config.get_commands() == []
    assert config.get_errors() == []


def test_valid_command_loads(config_for):
    config = config_for(
        """
        [[command]]
        id = "lock"
        label = "Lock screen"
        run = ["loginctl", "lock-session"]
        icon = "🔒"
        confirm = true
        """
    )
    assert config.get_errors() == []
    (cmd,) = config.get_commands()
    assert cmd["id"] == "lock"
    assert cmd["run"] == ["loginctl", "lock-session"]
    assert cmd["confirm"] is True


def test_string_run_is_rejected(config_for):
    """run must be argv: a shell string is the injection boundary."""
    config = config_for(
        """
        [[command]]
        id = "bad"
        label = "Bad"
        run = "rm -rf ~"
        """
    )
    assert config.get_commands() == []
    assert any("must be a list" in e for e in config.get_errors())


def test_non_string_argv_entry_is_rejected(config_for):
    config = config_for(
        """
        [[command]]
        id = "bad"
        label = "Bad"
        run = ["echo", 42]
        """
    )
    assert config.get_commands() == []
    assert any("non-string" in e for e in config.get_errors())


def test_missing_fields_are_rejected(config_for):
    config = config_for(
        """
        [[command]]
        id = "nolabel"
        run = ["true"]
        """
    )
    assert config.get_commands() == []
    assert config.get_errors()


def test_builtin_action_id_collision_is_rejected(config_for):
    config = config_for(
        """
        [[command]]
        id = "mute"
        label = "Shadow the built-in"
        run = ["true"]
        """
    )
    assert config.get_commands() == []
    assert any("built-in" in e for e in config.get_errors())


def test_ordinary_ids_that_look_builtin_are_allowed(config_for):
    """lock/suspend are command ids, not action names -- they must stay usable."""
    config = config_for(
        """
        [[command]]
        id = "suspend"
        label = "Suspend"
        run = ["systemctl", "suspend"]
        """
    )
    assert config.get_errors() == []
    assert config.get_commands()[0]["id"] == "suspend"


def test_duplicate_ids_keep_only_the_first(config_for):
    config = config_for(
        """
        [[command]]
        id = "dup"
        label = "First"
        run = ["true"]

        [[command]]
        id = "dup"
        label = "Second"
        run = ["false"]
        """
    )
    assert [c["label"] for c in config.get_commands()] == ["First"]
    assert any("Duplicate" in e for e in config.get_errors())


def test_malformed_toml_reports_an_error(config_for):
    config = config_for("this is not = valid = toml")
    assert config.get_commands() == []
    assert any("Failed to load" in e for e in config.get_errors())
