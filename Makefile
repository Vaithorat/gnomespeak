# VoiceTalk developer entrypoints.
#
# The point of this file is that `make dev` behaves identically whether you run
# it from a VS Code terminal, a plain shell, a systemd unit, or another
# directory entirely. It does that by refusing to inherit anything:
#
#   * every path is derived from this Makefile's own location, not from $(CURDIR)
#   * every Python call goes through the project venv by absolute path
#   * VIRTUAL_ENV / PYTHONPATH / PYTHONHOME from the calling shell are dropped,
#     so an unrelated activated venv cannot change which interpreter runs
#
# Run `make help` for the target list, `make env` when something still looks off.

ROOT        := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
VENV        := $(ROOT)/venv
PY          := $(VENV)/bin/python
PIP         := $(PY) -m pip
VT          := $(VENV)/bin/vt
STAMP       := $(VENV)/.deps-stamp
BASE_PYTHON ?= python3
BIN_DIR     ?= $(HOME)/.local/bin

# An activated venv, an IDE-injected PYTHONPATH, or a stale PYTHONHOME are the
# usual reasons "it works in one terminal but not the other". Drop them all.
unexport VIRTUAL_ENV
unexport PYTHONPATH
unexport PYTHONHOME
export PYTHONUNBUFFERED := 1

MAKEFLAGS += --no-print-directory
.DEFAULT_GOAL := help

# Optional overrides: make dev PORT=9000 HOST=0.0.0.0 OPEN=1
SERVE_FLAGS := --tunnel
ifdef HOST
SERVE_FLAGS += --host $(HOST)
endif
ifdef PORT
SERVE_FLAGS += --port $(PORT)
endif
ifdef NO_TOKEN
SERVE_FLAGS += --no-token
endif
ifdef OPEN
SERVE_FLAGS += --open
endif

.PHONY: help dev serve setup system pydeps extension deps test lint hooks doctor \
        status commands apps env link unlink clean reset

help: ## Show this help
	@echo ""
	@echo "  VoiceTalk — make targets"
	@echo ""
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "    \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Options:  HOST=0.0.0.0  PORT=9000  NO_TOKEN=1  OPEN=1  ARGS=\"...\""
	@echo "            SKIP_SYSTEM=1 (no package install)  YES=1 (never prompt)"
	@echo "  Example:  make dev PORT=9000"
	@echo ""

# --- the main one ------------------------------------------------------------

dev: setup ## Set up if needed, then start the server (use this)
	@echo "→ $(VT)"
	@$(PY) -c 'import sys; print("→ python %s" % sys.version.split()[0])'
	@echo ""
	@exec $(VT) serve $(SERVE_FLAGS) $(ARGS)

serve: dev ## Alias for dev

# --- environment -------------------------------------------------------------

# Sequential by construction: the venv cannot be built before python3-venv is
# installed, and the extension is installed by the vt inside that venv. Written
# as sub-makes rather than prerequisites so `make -j` cannot reorder them.
setup: ## Install everything and get ready to run (idempotent)
	@$(MAKE) system
	@$(MAKE) pydeps
	@$(MAKE) extension
	@$(MAKE) hooks

# A phony wrapper around the stamp file. `make setup` calls the wrapper so make
# does not announce "'venv/.deps-stamp' is up to date" on every single run; the
# empty recipe keeps it from announcing "nothing to be done" instead.
pydeps: $(STAMP)
	@:

# System packages first: the venv itself needs python3-venv, and dbus-python
# cannot be pip-installed. The script checks capabilities rather than a package
# database, so it costs a few milliseconds when nothing is missing, and it asks
# for sudo only when something is. It never fails the build -- a machine with no
# sudo or an unknown distro just runs with fewer features, each of which reports
# its own absence. Skip it with: make dev SKIP_SYSTEM=1
system: ## Install missing system packages (asks for sudo only if needed)
ifdef SKIP_SYSTEM
	@echo "→ system dependencies: skipped (SKIP_SYSTEM=1)"
else
	@$(ROOT)/scripts/setup-system.sh $(if $(YES),--yes,) || true
endif

# The GNOME extension is what window, workspace, touchpad and typing control go
# through, and installing it is two file operations plus a dconf key -- cheap
# enough to check on every `make dev` and much better than discovering it is
# missing from the phone. A no-op when the install is already healthy, and never
# fatal: without it vt still serves media, apps, volume and system controls.
extension: $(STAMP) ## Install or repair the GNOME extension (no-op when healthy)
	@$(VT) install-extension --if-needed || true

# --system-site-packages is mandatory, not a convenience: dbus-python and gi
# ship as distro packages (python3-dbus, python3-gi) and cannot be pip-installed
# without libdbus/glib headers. Without them vt has no media players and no
# window control.
$(PY):
	@echo "→ creating venv at $(VENV)"
	@$(BASE_PYTHON) -m venv --system-site-packages $(VENV)

# Re-runs only when pyproject.toml changes, so `make dev` stays fast.
# The dbus extra is deliberately not installed here -- see the note above.
$(STAMP): $(ROOT)/pyproject.toml | $(PY)
	@echo "→ installing voicetalk (editable) + qr, youtube, wayland, dev extras"
	@$(PIP) install --quiet --upgrade pip setuptools wheel
	@$(PIP) install --quiet --editable "$(ROOT)[qr,youtube,wayland,dev]"
	@$(PY) -c 'import dbus' 2>/dev/null \
		|| { echo ""; \
		     echo "  ⚠ python-dbus is not importable — media players and window"; \
		     echo "    control will be missing. Fix with:"; \
		     echo "      sudo apt install python3-dbus python3-gi   # or dnf"; \
		     echo "      make reset"; \
		     echo ""; }
	@touch $@

deps: ## Force a dependency reinstall
	@rm -f $(STAMP)
	@$(MAKE) setup

env: ## Print the resolved environment (run this when results differ)
	@echo ""
	@echo "  repo root     $(ROOT)"
	@echo "  cwd           $(CURDIR)"
	@echo "  venv          $(VENV)"
	@printf "  base python   "; $(BASE_PYTHON) --version 2>&1
	@printf "  venv python   "; $(PY) --version 2>&1 || echo "MISSING - run: make setup"
	@echo "  shell VIRTUAL_ENV  $${VIRTUAL_ENV:-<unset>}  (ignored by make)"
	@echo "  shell PYTHONPATH   $${PYTHONPATH:-<unset>}  (ignored by make)"
	@echo ""
	@$(PY) $(ROOT)/scripts/envreport.py 2>/dev/null || echo "  venv not built yet - run: make setup"
	@echo ""

link: setup ## Symlink `vt` into ~/.local/bin so any terminal can run it
	@mkdir -p $(BIN_DIR)
	@if [ -e "$(BIN_DIR)/vt" ] && [ ! -L "$(BIN_DIR)/vt" ]; then \
		echo "  ✗ $(BIN_DIR)/vt exists and is not a symlink — leaving it alone"; \
		exit 1; \
	fi
	@ln -sfn $(VT) $(BIN_DIR)/vt
	@echo "→ $(BIN_DIR)/vt -> $(VT)"
	@case ":$$PATH:" in \
		*":$(BIN_DIR):"*) echo "→ 'vt' is now on PATH in every terminal" ;; \
		*) echo "  ⚠ $(BIN_DIR) is not on PATH; add it to your shell rc" ;; \
	esac

unlink: ## Remove the ~/.local/bin/vt symlink
	@rm -f $(BIN_DIR)/vt
	@echo "→ removed $(BIN_DIR)/vt"

# --- passthroughs ------------------------------------------------------------

test: setup ## Run the test suite
	@$(PY) -m pytest $(ARGS)

lint: setup ## Run the same flake8 checks as CI
	@$(PY) -m flake8 vt tests --count --select=E9,F63,F7,F82 --show-source --statistics
	@$(PY) -m flake8 vt tests --count --exit-zero --max-complexity=12 --max-line-length=110 --statistics

# Hooks are versioned in .githooks/ and reached through core.hooksPath, since
# .git/hooks is not part of the repo and every clone would otherwise start
# unprotected. Silent once installed, so `make dev` stays quiet; a tarball with
# no .git is not an error, just nothing to do.
hooks: ## Install the pre-push hook (runs lint + tests before pushing to main)
	@git -C $(ROOT) rev-parse --git-dir >/dev/null 2>&1 || exit 0
	@chmod +x $(ROOT)/.githooks/* 2>/dev/null || true
	@[ "$$(git -C $(ROOT) config --get core.hooksPath)" = ".githooks" ] || { \
		git -C $(ROOT) config core.hooksPath .githooks; \
		echo "→ pre-push hook installed (bypass once with: git push --no-verify)"; }

doctor: setup ## Run preflight checks
	@$(VT) doctor

status: setup ## Print current state as a table
	@$(VT) status

commands: setup ## List configured commands
	@$(VT) commands

apps: setup ## List launchable apps (make apps ARGS=browser)
	@$(VT) apps $(ARGS)

# --- housekeeping ------------------------------------------------------------

clean: ## Remove caches and build artifacts
	@find $(ROOT) -path $(VENV) -prune -o -name '__pycache__' -type d -print0 \
		| xargs -0 rm -rf 2>/dev/null || true
	@rm -rf $(ROOT)/.pytest_cache $(ROOT)/build $(ROOT)/dist $(ROOT)/*.egg-info
	@echo "→ cleaned"

reset: ## Delete the venv and rebuild it from scratch
	@rm -rf $(VENV)
	@$(MAKE) setup
