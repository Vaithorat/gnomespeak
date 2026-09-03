#!/usr/bin/env bash
# GnomeSpeak Instant Runner — install (if needed) and run in one command without cloning
#
# Quick start (uses Cloudflare tunnel if cloudflared is available):
#   curl -fsSL https://raw.githubusercontent.com/Vaithorat/gnomespeak/main/run.sh | bash
#
# Options:
#   --local           Serve on local LAN IP only (no tunnel)
#   --service         Install as autostarting background systemd service
#   --tls             Serve HTTPS on the LAN with self-signed certificate
#   --port <port>     Custom port (default: 8765)
set -e

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"
INSTALLER_URL="https://raw.githubusercontent.com/Vaithorat/gnomespeak/main/install.sh"

# Ensure ~/.local/bin is on PATH
if [ -d "$HOME/.local/bin" ]; then
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) export PATH="$HOME/.local/bin:$PATH" ;;
    esac
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
    shift
    vt install-service "$@"
    echo ""
    echo "🎉 GnomeSpeak is running in the background."
    echo "Pair your phone by running: vt pair"
    exit 0
fi

# Detect whether to enable Cloudflare tunnel by default
USE_TUNNEL=0
ARGS=()
for arg in "$@"; do
    case "$arg" in
        --local|--no-tunnel) USE_TUNNEL=-1 ;;
        --tunnel|--tunnel-name) USE_TUNNEL=1; ARGS+=("$arg") ;;
        *) ARGS+=("$arg") ;;
    esac
done

if [ "$USE_TUNNEL" -eq 0 ] && command -v cloudflared >/dev/null 2>&1; then
    # cloudflared is present and user didn't ask for --local
    ARGS=("--tunnel" "${ARGS[@]}")
fi

echo "🚀 Starting GnomeSpeak..."
exec vt serve "${ARGS[@]}"
