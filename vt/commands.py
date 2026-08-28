"""Pre-configured command loader from commands.toml."""

import os
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python < 3.11


# Action ids the built-in sources emit; a command id may not shadow one.
BUILTIN_ACTION_IDS = frozenset({
    "volume", "mute", "play_pause", "next", "prev", "seek_back", "seek_fwd",
    "stop", "raise", "focus", "quit", "close", "run",
})


class CommandsConfig:
    """Load and validate commands.toml configuration."""

    def __init__(self):
        self.commands = []
        self.errors = []
        self._load()

    def _find_config_file(self) -> Optional[Path]:
        """Locate commands.toml in config directories."""
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            config_dir = Path(xdg_config) / "gnomespeak"
        else:
            config_dir = Path.home() / ".config" / "gnomespeak"

        config_file = config_dir / "commands.toml"
        if config_file.exists():
            return config_file
        return None

    def _load(self):
        """Load commands.toml if it exists."""
        config_file = self._find_config_file()
        if not config_file:
            return

        try:
            with open(config_file, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            self.errors.append(f"Failed to load {config_file}: {e}")
            return

        # Extract and validate commands
        seen_ids: set[str] = set()
        for cmd in data.get("command", []):
            id_ = cmd.get("id")
            label = cmd.get("label")
            run = cmd.get("run")

            if not id_ or not label or not run:
                self.errors.append(f"Command missing required fields: {cmd}")
                continue

            # Reject if run is a string (not an argv list)
            if isinstance(run, str):
                self.errors.append(f"Command '{id_}' has string run; must be a list")
                continue

            # Reject ids that collide with built-in action names. Command
            # targets are addressed as "command:<id>" and their action is always
            # "run", so only action-name collisions actually matter -- names like
            # lock/suspend are ordinary command ids and must stay usable.
            if id_ in BUILTIN_ACTION_IDS:
                self.errors.append(f"Command '{id_}' collides with a built-in action")
                continue

            if id_ in seen_ids:
                self.errors.append(f"Duplicate command id '{id_}'")
                continue
            seen_ids.add(id_)

            # Every argv element must be a string for subprocess(shell=False).
            if not all(isinstance(part, str) for part in run):
                self.errors.append(f"Command '{id_}' has a non-string entry in run")
                continue

            self.commands.append({
                "id": id_,
                "label": label,
                "run": run,
                "icon": cmd.get("icon", ""),
                "confirm": cmd.get("confirm", False),
            })

    def get_commands(self) -> list[dict]:
        """Return validated commands."""
        return self.commands

    def get_errors(self) -> list[str]:
        """Return any validation errors."""
        return self.errors
