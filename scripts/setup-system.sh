#!/usr/bin/env bash
# Install the system packages GnomeSpeak needs, and nothing else.
#
# `make dev` runs this before it builds the venv, which is why it checks
# capabilities rather than package names: "is dbus importable", "is wl-copy on
# PATH". A package database says what was installed, not what works, and the
# check has to be fast enough to run on every `make dev` -- it is a handful of
# `command -v` calls and two imports when nothing is missing, so there is no
# stamp file to go stale.
#
# It asks for sudo only when something is actually missing, and it never fails
# the build: a machine with no sudo, no network, or an unknown distro gets a
# summary of what is degraded and carries on. Every feature that depends on one
# of these packages already reports its own absence at the point of use.
#
# Usage:
#   scripts/setup-system.sh            # install what is missing, ask for sudo
#   scripts/setup-system.sh --check    # report only, install nothing
#   scripts/setup-system.sh --yes      # never prompt (CI); skip if sudo needs a password

set -u

CHECK_ONLY=0
ASSUME_YES=0
# --package <capability> <distro> prints one package name and exits. It exists
# so the table below can be checked without a machine of that distribution: a
# capability with no package name is a feature that silently never installs.
PKG_QUERY_CAP=""
PKG_QUERY_DISTRO=""

if [ "${1:-}" = "--package" ]; then
    PKG_QUERY_CAP="${2:-}"
    PKG_QUERY_DISTRO="${3:-}"
    if [ -z "$PKG_QUERY_CAP" ] || [ -z "$PKG_QUERY_DISTRO" ]; then
        echo "usage: $0 --package <capability> <distro>" >&2
        exit 2
    fi
else
    for arg in "$@"; do
        case "$arg" in
            --check) CHECK_ONLY=1 ;;
            --yes|-y) ASSUME_YES=1 ;;
            *) echo "usage: $0 [--check] [--yes]" >&2; exit 2 ;;
        esac
    done
fi

PYTHON="${BASE_PYTHON:-python3}"

# --- what we need, and why ---------------------------------------------------
#
# Each entry is: capability|how to test it|what it buys you. The package name
# per distro lives in pkg_for() below, because only the name differs.
#
# Order matters only in that python3-venv comes first: `make dev` cannot build
# the venv without it, and everything else is a feature rather than a
# prerequisite.
REQUIRED=(
    "venv|${PYTHON} -c 'import venv, ensurepip'|building the project venv"
    "dbus|${PYTHON} -c 'import dbus'|media players, window and workspace control"
    "gi|${PYTHON} -c 'import gi'|GNOME integration"
    "wl-clipboard|command -v wl-copy|clipboard sync on Wayland"
    "xclip|command -v xclip|clipboard sync on X11"
    "dbus-monitor|command -v dbus-monitor|notification mirroring"
    "wireplumber|command -v wpctl|volume control"
    "xdg-user-dirs|command -v xdg-user-dir|finding your Downloads folder"
    "libnotify|command -v notify-send|banners on the PC when the phone asks for one"
    "udisks|command -v udisksctl|ejecting a USB drive from the phone"
)

# Both clipboard tools go in regardless of session type -- they are tiny, and it
# means the same machine works after switching between Wayland and X11 at the
# login screen. The keystroke fallbacks are the opposite: under Wayland only the
# compositor may synthesize input, so xdotool there is a package that can never
# do anything.
if [ "${XDG_SESSION_TYPE:-}" = "x11" ]; then
    REQUIRED+=(
        "xdotool|command -v xdotool|keystroke fallback without the extension"
        "wmctrl|command -v wmctrl|window fallbacks on X11"
    )
fi

# gnome-shell is checked but never installed: pulling a desktop environment onto
# a machine that did not ask for one is not a dependency fix. Without it the
# extension features are simply unavailable, which the app already says.
OPTIONAL_REPORT=(
    "gnome-shell|command -v gnome-extensions|window, workspace and touchpad control"
)

# --- distro ------------------------------------------------------------------

detect_distro() {
    if command -v apt-get >/dev/null 2>&1; then echo debian
    elif command -v dnf >/dev/null 2>&1; then echo fedora
    elif command -v pacman >/dev/null 2>&1; then echo arch
    elif command -v zypper >/dev/null 2>&1; then echo suse
    else echo unknown
    fi
}

pkg_for() {
    # $1 capability, $2 distro. Empty output means "this distro ships it in the
    # base system", which is the honest answer for e.g. venv on Fedora.
    case "$2:$1" in
        debian:venv)          echo "python3-venv" ;;
        debian:dbus)          echo "python3-dbus" ;;
        debian:gi)            echo "python3-gi" ;;
        debian:dbus-monitor)  echo "dbus-bin" ;;
        debian:wireplumber)   echo "wireplumber" ;;
        debian:libnotify)     echo "libnotify-bin" ;;
        debian:udisks)        echo "udisks2" ;;
        debian:*)             echo "$1" ;;

        fedora:venv)          echo "" ;;
        fedora:dbus)          echo "python3-dbus" ;;
        fedora:gi)            echo "python3-gobject" ;;
        fedora:dbus-monitor)  echo "dbus-tools" ;;
        fedora:libnotify)     echo "libnotify" ;;
        fedora:udisks)        echo "udisks2" ;;
        fedora:*)             echo "$1" ;;

        arch:venv)            echo "" ;;
        arch:dbus)            echo "python-dbus" ;;
        arch:gi)              echo "python-gobject" ;;
        arch:dbus-monitor)    echo "dbus" ;;
        arch:libnotify)       echo "libnotify" ;;
        arch:udisks)          echo "udisks2" ;;
        arch:*)               echo "$1" ;;

        suse:venv)            echo "" ;;
        suse:dbus)            echo "python3-dbus-python" ;;
        suse:gi)              echo "python3-gobject" ;;
        suse:dbus-monitor)    echo "dbus-1-tools" ;;
        suse:libnotify)       echo "libnotify-tools" ;;
        suse:udisks)          echo "udisks2" ;;
        suse:*)               echo "$1" ;;

        *) echo "" ;;
    esac
}

if [ -n "$PKG_QUERY_CAP" ]; then
    pkg_for "$PKG_QUERY_CAP" "$PKG_QUERY_DISTRO"
    exit 0
fi

install_cmd() {
    case "$1" in
        debian) echo "apt-get install -y" ;;
        fedora) echo "dnf install -y" ;;
        arch)   echo "pacman -S --needed --noconfirm" ;;
        suse)   echo "zypper install -y" ;;
        *)      echo "" ;;
    esac
}

# --- check -------------------------------------------------------------------

missing_caps=()
missing_why=()
for entry in "${REQUIRED[@]}"; do
    cap="${entry%%|*}"
    rest="${entry#*|}"
    test_cmd="${rest%%|*}"
    why="${rest#*|}"
    if ! eval "$test_cmd" >/dev/null 2>&1; then
        missing_caps+=("$cap")
        missing_why+=("$why")
    fi
done

degraded=()
for entry in "${OPTIONAL_REPORT[@]}"; do
    rest="${entry#*|}"
    test_cmd="${rest%%|*}"
    why="${rest#*|}"
    eval "$test_cmd" >/dev/null 2>&1 || degraded+=("$why")
done

report_degraded() {
    for why in "${degraded[@]:-}"; do
        [ -n "$why" ] && echo "  ℹ no GNOME Shell here — unavailable: $why"
    done
}

if [ ${#missing_caps[@]} -eq 0 ]; then
    echo "→ system dependencies: all present"
    report_degraded
    exit 0
fi

DISTRO="$(detect_distro)"
INSTALL="$(install_cmd "$DISTRO")"

echo "→ system dependencies: ${#missing_caps[@]} missing"
i=0
for cap in "${missing_caps[@]}"; do
    echo "    $cap — ${missing_why[$i]}"
    i=$((i + 1))
done

packages=()
unpackaged=()
for cap in "${missing_caps[@]}"; do
    pkg="$(pkg_for "$cap" "$DISTRO")"
    if [ -n "$pkg" ]; then packages+=("$pkg"); else unpackaged+=("$cap"); fi
done

if [ "$CHECK_ONLY" = "1" ]; then
    [ ${#packages[@]} -gt 0 ] && echo "  install with: sudo $INSTALL ${packages[*]}"
    report_degraded
    exit 0
fi

skip() {
    # Missing system packages are never fatal here. Everything they back reports
    # its own absence in `vt doctor` and on the phone, so the server still comes
    # up and the features that do not need them still work.
    echo "  ⚠ $1"
    echo "    features stay unavailable until these are installed; vt doctor lists them"
    report_degraded
    exit 0
}

if [ "$DISTRO" = "unknown" ] || [ -z "$INSTALL" ]; then
    skip "unrecognised distribution — install the equivalents of: ${missing_caps[*]}"
fi
if [ ${#packages[@]} -eq 0 ]; then
    skip "no packages known for: ${unpackaged[*]}"
fi

if [ "$(id -u)" = "0" ]; then
    SUDO=""
elif command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"
else
    skip "sudo is not available — run as root: $INSTALL ${packages[*]}"
fi

# --yes is for CI and unattended runs: if sudo would stop to ask for a password
# there is nobody to type it, so skip rather than hang forever on a prompt.
if [ "$ASSUME_YES" = "1" ] && [ -n "$SUDO" ]; then
    sudo -n true >/dev/null 2>&1 || skip "sudo needs a password and --yes was given"
fi

echo ""
echo "  This needs administrator rights to run:"
echo "    $SUDO $INSTALL ${packages[*]}"
echo ""

if [ "$DISTRO" = "debian" ]; then
    $SUDO apt-get update -qq || true
fi

# shellcheck disable=SC2086
if $SUDO $INSTALL "${packages[@]}"; then
    echo "→ installed: ${packages[*]}"
else
    skip "package installation failed"
fi

[ ${#unpackaged[@]} -gt 0 ] && echo "  ⚠ no package known for: ${unpackaged[*]}"
report_degraded
exit 0
