#!/usr/bin/env bash
# GnomeSpeak installer — Install system deps and Python package in one command
#
# For a clone of the repository, `make dev` does all of this and more (venv,
# GNOME extension, git hooks). This script is the standalone path: one command
# on a machine that will install GnomeSpeak from PyPI rather than run it from a
# checkout.

set -e

echo "🚀 GnomeSpeak Installer"
echo ""

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# When run from a checkout, defer to the one place that knows the package names.
# It checks capabilities rather than a package database, asks for sudo only when
# something is missing, and never fails the run.
if [ -x "$HERE/scripts/setup-system.sh" ]; then
    "$HERE/scripts/setup-system.sh" || true
else
    # Detect distro
    if [ -f /etc/debian_version ]; then
        DISTRO="debian"
    elif [ -f /etc/redhat-release ]; then
        DISTRO="redhat"
    else
        echo "⚠ Unsupported Linux distribution — install these yourself:"
        echo "  python3-dbus python3-gi wl-clipboard xclip dbus-monitor"
        echo "  wireplumber xdg-user-dirs"
        DISTRO="unknown"
    fi

    # wl-clipboard and xclip back clipboard sync -- one per session type, and
    # installing both means the same install works on Wayland and X11.
    # dbus-monitor (dbus-bin / dbus-tools) is what notification mirroring reads,
    # wpctl (wireplumber) is volume, and xdg-user-dir finds the Downloads folder
    # that file transfer lands in.
    echo "📦 Installing system dependencies..."
    if [ "$DISTRO" = "debian" ]; then
        sudo apt-get update -qq
        sudo apt-get install -y -qq python3-dbus python3-gi wl-clipboard xclip \
            dbus-bin wireplumber xdg-user-dirs
    elif [ "$DISTRO" = "redhat" ]; then
        sudo dnf install -y -q python3-dbus python3-gobject wl-clipboard xclip \
            dbus-tools wireplumber xdg-user-dirs
    fi
fi

# Install Python package
echo "📥 Installing GnomeSpeak from PyPI..."
pip install gnomespeak

# The GNOME extension is what window, workspace, touchpad and typing control go
# through. Installing it here means a fresh machine has them at the next login
# rather than after a separate command nobody knew to run. Not fatal: without
# it, media, apps, volume and system control still work.
echo "🧩 Installing the GNOME extension..."
vt install-extension --if-needed || true

echo ""
echo "✅ Installation complete!"
echo ""
echo "🔍 Verify with:"
echo "   vt doctor"
echo ""
echo "🚀 Start the server with:"
echo "   vt serve"
echo ""
