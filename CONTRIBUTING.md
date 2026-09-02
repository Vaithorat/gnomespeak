# Contributing to GnomeSpeak

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
make dev
```

That is the whole setup. `make dev` installs any missing system packages
(asking for sudo at that point, and only then), creates `venv/`, installs the
package in editable mode with the dev and test extras, installs or repairs the
GNOME extension, installs the pre-push hook, and starts the server.

Every step is idempotent, so re-running it is safe and fast, and none of them
can fail the run — a missing package means a missing feature, not a missing
server. Useful variants:

```bash
make setup                 # everything above, without starting the server
make dev SKIP_SYSTEM=1     # never install system packages
scripts/setup-system.sh --check   # what it would install, installing nothing
make env                   # resolved interpreter, venv path, optional deps
```

`make env` is the first thing to check whenever your environment behaves
differently from what the docs say.

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
5. Update `CHANGELOG.md` for anything user-facing.
6. Open a PR against `main` with a clear description of *why*, not just
   *what* — the commit history in this repo favors that style too.

## Testing across environments

GnomeSpeak's behavior depends heavily on environment: Wayland vs. X11, GNOME
vs. COSMIC vs. other desktops, snap-confined vs. native Firefox, dbus-python
present or absent. CI runs the suite both with and without the `dbus` extra
installed — if you touch anything that imports `dbus`, make sure it still
degrades gracefully when the import fails (`vt.server.HAS_DBUS` is the flag
most modules check, and CI's `test-without-dbus` job checks exactly this).

You don't need every environment to contribute — just say what you tested in
the PR description, and note if a code path is untested (e.g. "not tested on
X11, only Wayland/GNOME").

## Reporting bugs / requesting features

Please use the [issue templates](.github/ISSUE_TEMPLATE) — they ask for the
environment details (distro, GNOME version, Wayland/X11, `vt doctor` output)
that nearly every bug in this project turns on. A report without them usually
just produces a round of "what does `vt doctor` say" before anything can be
diagnosed.

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). Be
respectful; assume good faith.

## Security issues

Do not open a public issue for a security vulnerability — see
[SECURITY.md](SECURITY.md) for how to report privately.
