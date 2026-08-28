# Security Policy

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through GitHub:

1. Go to the [Security tab](https://github.com/Vaithorat/gnomespeak/security/advisories/new)
2. Choose **Report a vulnerability**

That opens a private advisory only you and the maintainers can read, and it
stays private until a fix ships.

What helps most in a report:

- what an attacker gains (control of the desktop, access to another user's
  session, reading credentials — the impact, not just the faulty line)
- the position they need to start from: unauthenticated on the LAN, a paired
  device, a local user account, someone who can reach the tunnel URL
- the smallest reproduction you have — a `curl` against `/api/action` is ideal
- the version (`pip show gnomespeak`) and how the server was reachable at the
  time (`--host`, LAN, or `--tunnel`)

### What to expect

| | |
|---|---|
| First response | within 7 days |
| Assessment and severity | within 14 days |
| Fix for a confirmed high-severity issue | as the next release |

This is a small volunteer project, not a funded product — there is no bounty,
and those windows are honest intentions rather than a contractual SLA. You will
be credited in the advisory and the changelog unless you would rather not be.

## Supported versions

| Version | Supported |
|---------|-----------|
| 3.1.x   | ✅ |
| < 3.1   | ❌ |

Fixes land on the latest release. There are no backport branches.

## The security model

Understanding what GnomeSpeak is *meant* to allow will save you time deciding
whether something is a bug.

GnomeSpeak runs a local HTTP server as your own user account, and its entire
purpose is to let a phone control that desktop session — adjust volume, focus
and quit apps, run the commands you configured in `commands.toml`. So:

**A client that authenticates is trusted to control the desktop.** That is the
feature. A paired device quitting your apps or running one of your configured
commands is not a vulnerability.

What the project *does* commit to:

- **Authentication cannot be bypassed.** Every `/api/*` route requires a valid
  token or paired-device credential. A way around that is a vulnerability.
- **Credentials cannot be recovered from disk or the wire.** Device secrets are
  stored only as SHA-256 hashes, in files created `0600`. Comparisons are
  timing-safe. Recovering a usable secret is a vulnerability.
- **Pairing cannot be brute-forced.** Codes are short-lived and rate-limited.
  A way to cheaply enumerate them is a vulnerability.
- **An authenticated client cannot exceed the action it asked for.** Actions
  take a target and an action id; making one of those reach the shell, or
  turning one action into a broader one, is a vulnerability. (A real example:
  a target named `app:-9` once reached `pkill` as an option rather than a
  process name, turning "quit one app" into "kill every process I own".)
- **Configured commands stay argv.** `commands.toml` requires `run` to be a
  list, never a shell string. A path from config to a shell is a vulnerability.

### In scope

- Authentication or pairing bypass on any `/api/*` route
- Command, argument, or path injection reachable from a request
- Recovering device secrets or tokens from disk, logs, or responses
- Cross-site issues in the web remote (XSS, CSRF, token leakage via referrer)
- Anything that lets an *unauthenticated* party on the LAN act on the desktop
- Tunnel misconfiguration that exposes more than the intended endpoints

### Out of scope

- **An attacker who already runs code as your user.** They can edit
  `commands.toml` or your `.desktop` files directly; the server is not a
  boundary against someone already inside it.
- **What a paired device can do.** Pair only devices you trust, and use
  `vt devices --revoke <id>` when you no longer do.
- **Denial of service**, resource exhaustion, or crashing the server.
- **Running with `--no-token`.** That flag exists for trusted-LAN debugging and
  says so; it is not a security control that failed.
- **Vulnerabilities in dependencies** — report those upstream. Do tell us if
  GnomeSpeak uses one in a way that makes it materially worse.
- Missing hardening headers with no demonstrated impact, and scanner output
  submitted without a working reproduction.

## Notes for running it safely

- Prefer LAN binding over a tunnel when you can. `--tunnel` puts a URL for your
  desktop on the public internet; the token is all that stands in front of it.
- Revoke devices you no longer use: `vt devices` lists them,
  `vt devices --revoke <id>` removes one, `vt devices --revoke-all` clears them.
- `vt audit` shows the recent security log, written to
  `~/.local/state/gnomespeak/audit.log`. It records every action and who asked
  for it, which is what answers "did someone else do that?"
- Keep `commands.toml` minimal. Every entry is something a paired phone can run.
