#!/usr/bin/env bash
# GnomeSpeak installer — Install system deps and Python package in one command

set -e

echo "🚀 GnomeSpeak Installer"
echo ""

# Detect distro
if [ -f /etc/debian_version ]; then
    DISTRO="debian"
elif [ -f /etc/redhat-release ]; then
    DISTRO="redhat"
else
    echo "❌ Unsupported Linux distribution"
    echo "   Supported: Debian/Ubuntu, Fedora/RHEL"
    exit 1
fi

# Install system dependencies
echo "📦 Installing system dependencies..."
if [ "$DISTRO" = "debian" ]; then
    sudo apt-get update -qq
    sudo apt-get install -y -qq python3-dbus python3-gi xdotool wmctrl
elif [ "$DISTRO" = "redhat" ]; then
    sudo dnf install -y -q python3-dbus python3-gi xdotool wmctrl
fi

# Install Python package
echo "📥 Installing GnomeSpeak from PyPI..."
pip install gnomespeak

echo ""
echo "✅ Installation complete!"
echo ""
echo "🔍 Verify with:"
echo "   vt doctor"
echo ""
echo "🚀 Start the server with:"
echo "   vt serve"
echo ""
