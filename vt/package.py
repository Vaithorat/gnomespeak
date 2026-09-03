"""Build the extension zip that extensions.gnome.org accepts.

The store wants one thing the local install does not: a uuid whose domain half
belongs to the author. "@local" is fine for a symlink into a checkout and is
not a name anyone can publish under, so the zip carries the store uuid while
the checkout keeps its own. Nothing else is rewritten -- same code, same bus
name -- so a machine can run either build and vt cannot tell the difference.

The layout matters too: the review tooling reads metadata.json at the root of
the archive, so the files go in flat rather than inside a directory named after
the extension.
"""

import json
import sys
import sysconfig
import zipfile
from pathlib import Path

from vt.shell import EXTENSION_UUID, STORE_EXTENSION_UUID

# Where the wheel puts the extension. A checkout has it beside the package, but
# `pip install gnomespeak` unpacks the package alone -- and an install that
# cannot then run `vt install-extension` sends the user back to `git clone`,
# which is the onboarding step the store listing exists to remove.
DATA_SUBDIR = Path("share") / "gnomespeak" / "gnome-extension"

# What must be in metadata.json before a submission is worth uploading. The
# review queue is measured in weeks, so a field caught here costs nothing and
# the same field caught there costs a round trip.
REQUIRED_FIELDS = ("name", "description", "uuid", "shell-version", "url")

SOURCE_FILES = ("extension.js", "metadata.json")


def source_candidates(uuid: str = EXTENSION_UUID) -> list:
    """Every place the extension source could be, best first.

    The checkout comes first so a developer always installs the tree they are
    editing, even when a release is installed in the same environment.
    """
    paths = [Path(__file__).parent.parent / "gnome-extension" / uuid]
    for key in ("data", "userbase"):
        try:
            base = sysconfig.get_path(key) if key == "data" else sysconfig.get_config_var(key)
        except Exception:
            base = None
        if base:
            paths.append(Path(base) / DATA_SUBDIR / uuid)
    paths.append(Path(sys.prefix) / DATA_SUBDIR / uuid)
    return paths


def is_checkout(path: Path, uuid: str = EXTENSION_UUID) -> bool:
    """Whether this source is the repository tree rather than an installed copy.

    It decides symlink versus copy in `vt install-extension`, and the two are
    not interchangeable. A symlink into a checkout is what a developer wants:
    edit `extension.js`, log back in, and the change is live. A symlink into
    the directory a wheel unpacked is a trap -- `pip uninstall` or an upgrade
    takes that directory away, and GNOME Shell drops an extension whose symlink
    dangles without saying a word, which is exactly the failure the rename left
    behind once already.
    """
    try:
        return Path(path).resolve() == source_candidates(uuid)[0].resolve()
    except OSError:  # pragma: no cover - resolve() on an unreadable path
        return False


def metadata_version(path: Path) -> int:
    """The integer `version` in a directory's metadata.json, or 0.

    0 means "older than anything", which is the right answer for a copy whose
    metadata is missing or unreadable: it gets replaced rather than kept.
    """
    try:
        value = json.loads((Path(path) / "metadata.json").read_text()).get("version")
    except Exception:
        return 0
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def source_dir(uuid: str = EXTENSION_UUID) -> Path:
    """The extension source to install or package.

    Returns the first candidate that exists, and the checkout path when none
    does -- so the caller's "no extension source at ..." message names the
    place a developer would look.
    """
    candidates = source_candidates(uuid)
    for path in candidates:
        if (path / "metadata.json").is_file():
            return path
    return candidates[0]


def metadata_problems(metadata: dict) -> list:
    """Everything extensions.gnome.org would reject, as prose."""
    problems = []
    for field in REQUIRED_FIELDS:
        if not metadata.get(field):
            problems.append(f"metadata.json has no {field}")
    version = metadata.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        problems.append("metadata.json needs an integer version (a string is rejected)")
    shell_versions = metadata.get("shell-version")
    if shell_versions and not isinstance(shell_versions, list):
        problems.append("shell-version must be a list")
    modes = metadata.get("session-modes")
    if modes and "unlock-dialog" in modes:
        problems.append(
            "session-modes claims unlock-dialog; an extension that injects input "
            "must not run on the lock screen"
        )
    return problems


def build(out_dir: Path = None, uuid: str = STORE_EXTENSION_UUID,
          source: Path = None) -> dict:
    """Write <uuid>.shell-extension.zip and say where it landed.

    Returns the usual result dict, with `path` when it was written.
    """
    src = Path(source) if source else source_dir()
    if not src.is_dir():
        return {"ok": False, "message": f"No extension source at {src}"}

    missing = [name for name in SOURCE_FILES if not (src / name).is_file()]
    if missing:
        return {"ok": False, "message": f"{src} is missing {', '.join(missing)}"}

    try:
        metadata = json.loads((src / "metadata.json").read_text())
    except Exception as e:
        return {"ok": False, "message": f"metadata.json is not readable JSON: {e}"}

    metadata["uuid"] = uuid
    problems = metadata_problems(metadata)
    if problems:
        return {"ok": False, "message": problems[0], "problems": problems}

    destination = Path(out_dir) if out_dir else Path.cwd()
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / f"{uuid}.shell-extension.zip"

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json.dumps(metadata, indent=2) + "\n")
        for name in SOURCE_FILES:
            if name != "metadata.json":
                archive.write(src / name, name)

    return {
        "ok": True,
        "path": path,
        "uuid": uuid,
        "version": metadata.get("version"),
        "message": f"Wrote {path}",
    }
