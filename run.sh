#!/usr/bin/env bash
# GnomeSpeak Instant Runner — install (if needed) and run in one command without cloning
#
# Quick start:
#   curl -fsSL https://raw.githubusercontent.com/Vaithorat/gnomespeak/main/run.sh | bash
#
# Options:
#   curl -fsSL https://raw.githubusercontent.com/Vaithorat/gnomespeak/main/run.sh | bash -s -- --service
#   curl -fsSL https://raw.githubusercontent.com/Vaithorat/gnomespeak/main/run.sh | bash -s -- --tls
set -e

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"
INSTALLER_URL="https://raw.githubusercontent.com/Vaithorat/gnomespeak/main/install.sh"

# Ensure ~/.local/bin is on PATH if vt is there
if ! command -v vt >/dev/null 2>&1 && [ -x "$HOME/.local/bin/vt" ]; then
    export PATH="$HOME/.local/bin:$PATH"
fi

# If vt is not installed, install it
if ! command -v vt >/dev/null 2>&1; then
    echo "⚡ GnomeSpeak not found. Setting up first..."
    if [ -n "$HERE" ] && [ -x "$HERE/install.sh" ]; then
        "$HERE/install.sh"
    else
        curl -fsSL "$INSTALLER_URL" | bash
    fi
    if ! command -v vt >/dev/null 2>&1 && [ -x "$HOME/.local/bin/vt" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
fi

# Run as background service if requested
if [ "${1:-}" = "--service" ]; then
    vt install-service
    echo ""
    echo "🎉 GnomeSpeak is running in the background."
    echo "Pair your phone by running: vt pair"
    exit 0
fi

# Launch server immediately
echo "🚀 Starting GnomeSpeak..."
exec vt serve "$@"
