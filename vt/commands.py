"""Pre-configured command loader from commands.toml."""

import os
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # Python < 3.11


# A macro is a handful of taps in a row, not a program: the cap is what keeps
# "one button" from becoming a script with a loop somebody has to debug.
MAX_STEPS = 20

# The longest a step may pause. Anything longer belongs in a timer, which the
# phone can see and cancel.
MAX_WAIT = 10.0

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
            steps = cmd.get("steps")

            if not self._shape_is_usable(cmd, id_, label, run, steps):
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

            if steps is not None:
                steps = self._clean_steps(id_, steps)
                if steps is None:
                    continue

            self.commands.append({
                "id": id_,
                "label": label,
                "run": run or [],
                "steps": steps or [],
                "icon": cmd.get("icon", ""),
                "confirm": cmd.get("confirm", False),
            })

    def _shape_is_usable(self, cmd, id_, label, run, steps) -> bool:
        """Whether this entry is a command at all: a name, and one way to act."""
        if not id_ or not label or (not run and not steps):
            self.errors.append(f"Command missing required fields: {cmd}")
            return False
        if run and steps:
            self.errors.append(
                f"Command '{id_}' has both run and steps; it can be one or the other"
            )
            return False
        if run and isinstance(run, str):
            # A string would be a shell line, which is the one thing
            # commands.toml never becomes.
            self.errors.append(f"Command '{id_}' has string run; must be a list")
            return False
        if run and not all(isinstance(part, str) for part in run):
            self.errors.append(f"Command '{id_}' has a non-string entry in run")
            return False
        return True

    def _clean_steps(self, id_: str, steps):
        """Validate a macro's steps, or None with an error recorded.

        A step is either something the phone could have tapped -- a target and
        an action -- or a wait. Nothing here can name a program: a macro is a
        sequence of things vt already does, so the argv boundary that keeps
        `commands.toml` out of a shell is not widened by it.
        """
        if not isinstance(steps, list) or not steps:
            self.errors.append(f"Command '{id_}' has steps that are not a non-empty list")
            return None
        if len(steps) > MAX_STEPS:
            self.errors.append(f"Command '{id_}' has more than {MAX_STEPS} steps")
            return None

        cleaned = []
        for index, step in enumerate(steps, start=1):
            entry = self._clean_step(id_, index, step)
            if entry is None:
                return None
            cleaned.append(entry)
        return cleaned

    def _clean_step(self, id_: str, index: int, step) -> Optional[dict]:
        """One step: a wait, or a target and an action. None records an error."""
        if not isinstance(step, dict):
            self.errors.append(f"Command '{id_}' step {index} is not a table")
            return None

        if "wait" in step:
            try:
                seconds = float(step["wait"])
            except (TypeError, ValueError):
                self.errors.append(f"Command '{id_}' step {index} has a bad wait")
                return None
            if not 0 < seconds <= MAX_WAIT:
                self.errors.append(
                    f"Command '{id_}' step {index} waits longer than {MAX_WAIT}s"
                )
                return None
            return {"wait": seconds}

        target = step.get("target")
        action = step.get("action")
        if not isinstance(target, str) or not isinstance(action, str) or ":" not in target:
            self.errors.append(
                f"Command '{id_}' step {index} needs a target like \"system:audio\" "
                "and an action, or a wait"
            )
            return None
        entry = {"target": target, "action": action}
        if "value" in step:
            try:
                entry["value"] = float(step["value"])
            except (TypeError, ValueError):
                self.errors.append(f"Command '{id_}' step {index} has a bad value")
                return None
        return entry

    def get_commands(self) -> list[dict]:
        """Return validated commands."""
        return self.commands

    def get_errors(self) -> list[str]:
        """Return any validation errors."""
        return self.errors
