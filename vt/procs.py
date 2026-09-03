"""Run several short read-only commands at once.

The snapshot is collected on a single worker thread, once a second, and its
cost is dominated by small subprocesses that spend all their time waiting:
`wpctl get-volume` for each stream, `gsettings get` for each desktop setting.
Run one after another they add up to a quarter of a second, which is most of
the budget the live channel has for getting a change to the phone.

Waiting on them together costs the same processes and a fraction of the time,
and it is safe precisely because these are reads: nothing here may be used for
a command with a side effect, where the order of two calls is part of what the
caller asked for.
"""

import subprocess

DEFAULT_TIMEOUT = 2.0


def run_all(commands: list, timeout: float = DEFAULT_TIMEOUT) -> list:
    """Run every argv concurrently; return (returncode, stdout) per command.

    A command that fails to start, or outruns the timeout, comes back as
    (1, "") -- the same shape every caller already handles for a command that
    simply had nothing to say.
    """
    started = []
    for argv in commands:
        try:
            started.append(subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            ))
        except Exception:
            started.append(None)

    results = []
    for proc in started:
        if proc is None:
            results.append((1, ""))
            continue
        try:
            out, _ = proc.communicate(timeout=timeout)
            results.append((proc.returncode, out or ""))
        except Exception:
            proc.kill()
            try:
                proc.communicate(timeout=0.5)
            except Exception:
                pass
            results.append((1, ""))
    return results
