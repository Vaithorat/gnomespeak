# GnomeSpeak 4.0: Release verification and what's next

See the [changelog](CHANGELOG.md) for the shipped feature set and the
[README](README.md) for installation and platform requirements.

## Release channels

The [GitHub release](https://github.com/Vaithorat/gnomespeak/releases/tag/v4.0.0)
and [PyPI](https://pypi.org/project/gnomespeak/) use the same wheel and source
distribution. The wheel contains the GNOME extension, so `vt install-extension`
does not need a source checkout. GitHub Actions publishes both from the version
tag. The PyPI job needs a Trusted Publisher for `Vaithorat/gnomespeak`,
workflow `publish.yml`, environment `pypi`.

## Device checks still open

| Check | How to verify |
| --- | --- |
| Desktop autostart after reboot and login | Install the user service with a named Cloudflare Tunnel, pair with its HTTPS address, reboot and log in. Check `systemctl --user is-active gnomespeak` and reconnect from the paired phone without changing the link. |
| Android installation and native share sheet | Pair at a stable HTTPS address in Chrome, choose **Install app**, then share a photo to GnomeSpeak from Google Photos. Check that it appears under Files on the remote and in the PC's GnomeSpeak downloads folder. |
| Ring while locked | With the PC locked and speakers available, ring it from a paired phone and confirm **Stop** silences it. |
| One-hour phone idle cost | Keep the paired app open for an hour. Check connection survival, traffic, and battery drain against an idle browser tab. |
| Action-to-update latency on a phone | Measure from a control action to the visible update over the actual network. The earlier local run recorded a 253 ms median and 372 ms worst case (12 actions); 300 ms is a target, not a guarantee. |

## Limitations and non-goals

- Notification mirroring supports dismiss and mute, not default actions or
  inline replies. GnomeSpeak is not the desktop notification daemon.
- Window controls work on GNOME and COSMIC; workspace switching is GNOME-only.
  See [COSMIC input parity](COSMIC_INPUT_PARITY.md).
- Quick Tunnel URLs rotate, and web app installation and pairing are bound to
  the URL's origin. Use a stable HTTPS address for repeat use.
- Screen streaming, SMS/call mirroring, native Android, Windows/macOS servers,
  and a GNOME Extensions store listing are outside the 4.0 scope. The web app,
  screenshots, and bundled extension are the supported paths.

## Candidate work after 4.0

These are not release commitments: phone lock-screen media controls,
adaptive updates on cellular, COSMIC workspace switching, monitor layout
controls, screenshot OCR, keyboard layouts, presence automation,
accessibility, and localization.
