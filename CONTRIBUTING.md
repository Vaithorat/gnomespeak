# Contributing to GnomeSpeak

## Setup

```bash
git clone https://github.com/Vaithorat/gnomespeak.git
cd gnomespeak
make dev
```

`make dev` creates `venv/`, installs everything (including the `dev` and `dbus`
extras), installs the pre-push hook, and starts the server. See the
[Development](README.md#development) section of the README for the full list
of `make` targets.

## Before opening a PR

```bash
make lint   # flake8, same checks as CI
make test   # pytest suite
```

The pre-push hook (`make hooks`, installed automatically by `make dev`) runs
both of these before a push to `main` reaches the remote, so a passing `git
push` already means CI should be green.

## Making changes

- Match the existing code style in the file you're editing; `flake8` config
  lives in the `[flake8]`-equivalent settings baked into `make lint`.
- Add or update tests under `tests/` for any behavior change — see
  `tests/test_sources.py` and friends for the pattern used per-source.
- If you change a D-Bus-backed source (`vt/sources/mpris.py`,
  `vt/sources/windows.py`, `vt/sources/bluetooth.py`), make sure it still
  degrades gracefully when `python-dbus` is unavailable — CI's
  `test-without-dbus` job checks exactly this.
- Update `CHANGELOG.md` for user-facing changes.

## Reporting bugs / requesting features

Use the [issue templates](.github/ISSUE_TEMPLATE) — they ask for the output
of `vt doctor`, which covers most of what's needed to reproduce a problem on
someone else's machine.

## Security issues

Do not open a public issue — see [SECURITY.md](SECURITY.md) for how to report
privately.
