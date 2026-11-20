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

SOURCE="${BASH_SOURCE[0]:-}"

# When run from a checkout, defer to the one place that knows the package names.
# It checks capabilities rather than a package database, asks for sudo only when
# something is missing, and never fails the run.
if [ -n "$SOURCE" ]; then
    HERE="$(cd "$(dirname "$SOURCE")" && pwd)"
fi
if [ -n "$SOURCE" ] && [ -x "$HERE/scripts/setup-system.sh" ]; then
    "$HERE/scripts/setup-system.sh" || true
else
    SETUP_URL="https://raw.githubusercontent.com/Vaithorat/gnomespeak/main/scripts/setup-system.sh"
    if setup_script="$(curl -fsSL "$SETUP_URL")"; then
        bash -c "$setup_script" || true
    else
        echo "⚠ Could not fetch the system dependency helper. Check optional dependencies with vt doctor."
    fi
fi

# Install the Python package.
#
# `pip install` into the system interpreter fails outright on any distro that
# ships PEP 668 (Ubuntu 24.04, Debian 12, Fedora 39 and later): "error:
# externally-managed-environment". That error is the single most likely way
# this script ends with nothing installed, so the three cases are handled
# explicitly rather than left to whatever pip does today.
#
# The extras are the ones a phone remote is expected to have: a QR code at
# startup, YouTube search, and Web Push (which is also what --tls uses).
PACKAGE="gnomespeak[qr,youtube,push]"
GIT_PACKAGE="$PACKAGE @ git+https://github.com/Vaithorat/gnomespeak.git"

externally_managed() {
    python3 - <<'PY'
import os, sys, sysconfig
sys.exit(0 if os.path.exists(
    os.path.join(sysconfig.get_path("stdlib"), "EXTERNALLY-MANAGED")) else 1)
PY
}

echo "📥 Installing GnomeSpeak..."
if ! externally_managed; then
    python3 -m pip install --user --upgrade "$PACKAGE" || {
        echo "   (PyPI install failed, falling back to GitHub repository)"
        python3 -m pip install --user --upgrade "$GIT_PACKAGE"
    }
elif command -v pipx >/dev/null 2>&1; then
    # --system-site-packages is not optional here: dbus-python and gi are
    # distro packages that cannot be pip-installed, and without them there are
    # no media players and no window control.
    echo "   (this distro manages its Python packages, so installing with pipx)"
    pipx install --system-site-packages --force "$PACKAGE" || {
        echo "   (PyPI install failed, falling back to GitHub repository)"
        pipx install --system-site-packages --force "$GIT_PACKAGE"
    }
else
    echo "   (this distro manages its Python packages, and pipx is not installed;"
    echo "    installing into your user site with --break-system-packages, which"
    echo "    touches nothing the distro owns. 'sudo apt install pipx' first if"
    echo "    you would rather have it isolated.)"
    python3 -m pip install --user --upgrade --break-system-packages "$PACKAGE" || {
        echo "   (PyPI install failed, falling back to GitHub repository)"
        python3 -m pip install --user --upgrade --break-system-packages "$GIT_PACKAGE"
    }
fi

# An install that put `vt` somewhere unreachable looks exactly like an install
# that failed, and the next line of this script is `vt install-extension`.
if ! command -v vt >/dev/null 2>&1; then
    if [ -x "$HOME/.local/bin/vt" ]; then
        export PATH="$HOME/.local/bin:$PATH"
        echo "⚠ ~/.local/bin is not on your PATH — add this to your shell rc:"
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
    else
        echo "✗ GnomeSpeak installed but 'vt' is not on PATH; stopping here."
        exit 1
    fi
fi

# The GNOME extension is what window, workspace, touchpad and typing control go
# through. Installing it here means a fresh machine has them at the next login
# rather than after a separate command nobody knew to run. Not fatal: without
# it, media, apps, volume and system control still work.
echo "🧩 Installing the GNOME extension..."
vt install-extension --if-needed || true

# Handle immediate action flags
SERVE=0
SERVICE=0
for arg in "$@"; do
    case "$arg" in
        --serve|-s) SERVE=1 ;;
        --service)  SERVICE=1 ;;
    esac
done

echo ""
echo "✅ Installation complete!"
echo ""

if [ "$SERVICE" -eq 1 ]; then
    echo "⚙️ Installing and starting systemd user service..."
    vt install-service
    echo ""
    echo "🎉 GnomeSpeak is running in the background."
    echo "Pair your phone by running:"
    echo "   vt pair"
    exit 0
elif [ "$SERVE" -eq 1 ]; then
    echo "🚀 Launching GnomeSpeak..."
    exec vt serve
fi

echo "🔍 Verify with:"
echo "   vt doctor"
echo ""
echo "🚀 Start the server with:"
echo "   vt serve"
echo ""
