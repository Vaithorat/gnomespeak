---
name: Bug report
about: Something in GnomeSpeak isn't working right
title: ""
labels: bug
assignees: ""
---

## What happened

<!-- A clear description of the bug. What did you expect instead? -->

## Environment

Run `vt doctor` and paste its full output here:

```
(paste vt doctor output)
```

Fill in anything `vt doctor` doesn't already cover:

- **Distro & version:** (e.g. Ubuntu 26.04, Fedora 41)
- **Desktop environment:** (GNOME / KDE / XFCE / other, and version)
- **Session type:** Wayland or X11? (`echo $XDG_SESSION_TYPE`)
- **Firefox packaging:** snap, deb, or flatpak? (matters for autoplay/MPRIS bugs)
- **GnomeSpeak version:** (`pip show gnomespeak` or `vt --version`)
- **Install method:** `install.sh`, PyPI (`pip install gnomespeak`), or from source (`make setup`)?
- **GNOME extension installed?** (`vt install-extension` run, and logged out/in since?)

## Steps to reproduce

1.
2.
3.

## Relevant logs

<!-- Server output, browser console errors, or `vt audit` output if it's a
security/auth-related issue. Redact your token/pairing codes if pasting
server output. -->

```
(paste here)
```

## Additional context

<!-- Anything else — does it happen every time, only under specific
conditions, only with a specific player/app/browser, etc. -->
