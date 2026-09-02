# Contributing to GnomeSpeak

<<<<<<< Updated upstream
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
=======
Thanks for looking at this. GnomeSpeak is a small volunteer project — a Linux
CLI + web remote, no LLM, no cloud dependency. Contributions of any size are
welcome: a typo fix, a bug report with a good repro, a new source, a new
action.

## Before you start

If you're planning something bigger than a small fix (a new source type, a
new action category, a protocol change), open an issue first to talk it
through. It's much easier to agree on the shape of a change before code
exists than to review a large PR that took a different path than the
maintainer would have.

For anything else — bug fixes, docs, small features — just send a PR.

## Development setup

```bash
git clone https://github.com/Vaithorat/gnomespeak
cd gnomespeak
sudo apt-get install python3-dbus python3-gi xdotool wmctrl   # system deps
make setup                                                     # venv + editable install + dev/test extras
```

`make setup` is idempotent — safe to re-run any time. If your environment
ever behaves differently from what's documented, `make env` prints the
resolved interpreter, venv path, and installed packages, which is the first
thing to check.

## Running things

```bash
make dev      # start the server (the only command you need day to day)
make test     # run the pytest suite
make lint     # the same flake8 checks CI runs
make doctor   # preflight checks (D-Bus, PipeWire, GNOME extension, etc.)
make status   # print current state as a table, no server
```

`make hooks` installs a pre-push hook (`.githooks/pre-push`) that runs lint +
tests before a push to `main` — it runs the same commands CI does, so passing
locally means passing there. `make setup` installs it for you automatically.

## Making a change

1. Branch off `main`.
2. Write the code. Match the style of the file you're editing — this
   codebase favors explicit, defensive checks (see `vt/sources/*.py` for the
   pattern of guarding D-Bus/dbus-python availability) over clever
   abstraction.
3. Add or update tests. `tests/` is organized roughly one file per module
   (`test_sources.py`, `test_actions.py`, `test_server.py`, etc.) — put new
   tests next to the thing they cover.
4. Run `make test` and `make lint` before pushing. If you installed the
   pre-push hook this happens automatically.
5. Open a PR against `main` with a clear description of *why*, not just
   *what* — the commit history in this repo favors that style too.

## Testing across environments

GnomeSpeak's behavior depends heavily on environment: Wayland vs. X11, GNOME
vs. other DEs, snap-confined vs. native Firefox, dbus-python present or
absent. CI runs the suite both with and without the `dbus` extra installed —
if you touch anything that imports `dbus`, make sure it still degrades
gracefully when the import fails (`vt.server.HAS_DBUS` is the flag most
modules check).

You don't need every environment to contribute — just say what you tested in
the PR description, and note if a code path is untested (e.g. "not tested on
X11, only Wayland/GNOME").

## Reporting bugs

Please use the bug report issue template — it asks for the environment
details (distro, GNOME version, Wayland/X11, `vt doctor` output) that nearly
every bug in this project turns on. A report without them usually just
produces a round of "what does `vt doctor` say" before anything can be
diagnosed.

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). Be
respectful; assume good faith.

## Security issues

Do not open a public issue for a security vulnerability — see
[SECURITY.md](SECURITY.md) for how to report privately.
>>>>>>> Stashed changes
