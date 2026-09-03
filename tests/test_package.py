"""Tests for the extensions.gnome.org submission zip and the two uuids.

The store install and the development symlink carry different uuids for the
same extension, and the point of these tests is that neither is privileged:
`vt doctor` has to see a store install exactly as readily as a symlinked one.
"""

import json
import zipfile

from vt import package, shell


def source(tmp_path, **overrides):
    """A miniature extension checkout, with metadata that can be broken."""
    directory = tmp_path / "src"
    directory.mkdir()
    metadata = {
        "name": "GnomeSpeak",
        "description": "Window control",
        "uuid": shell.EXTENSION_UUID,
        "version": 4,
        "shell-version": ["45", "50"],
        "url": "https://github.com/Vaithorat/gnomespeak",
    }
    metadata.update(overrides)
    (directory / "metadata.json").write_text(json.dumps(metadata))
    (directory / "extension.js").write_text("export default class {}\n")
    return directory


def test_the_zip_carries_the_store_uuid_not_the_local_one(tmp_path):
    result = package.build(out_dir=tmp_path / "out", source=source(tmp_path))
    assert result["ok"]
    with zipfile.ZipFile(result["path"]) as archive:
        metadata = json.loads(archive.read("metadata.json"))
    assert metadata["uuid"] == shell.STORE_EXTENSION_UUID
    assert result["path"].name == f"{shell.STORE_EXTENSION_UUID}.shell-extension.zip"


def test_metadata_sits_at_the_root_of_the_archive(tmp_path):
    result = package.build(out_dir=tmp_path / "out", source=source(tmp_path))
    with zipfile.ZipFile(result["path"]) as archive:
        assert sorted(archive.namelist()) == ["extension.js", "metadata.json"]


def test_a_string_version_is_refused_before_the_upload(tmp_path):
    result = package.build(out_dir=tmp_path / "out",
                           source=source(tmp_path, version="3.4.0"))
    assert not result["ok"]
    assert "integer version" in result["message"]


def test_a_missing_url_is_refused(tmp_path):
    result = package.build(out_dir=tmp_path / "out", source=source(tmp_path, url=""))
    assert not result["ok"] and "url" in result["message"]


def test_running_on_the_lock_screen_is_refused(tmp_path):
    result = package.build(
        out_dir=tmp_path / "out",
        source=source(tmp_path, **{"session-modes": ["user", "unlock-dialog"]}),
    )
    assert not result["ok"] and "unlock-dialog" in result["message"]


def test_a_missing_source_is_a_message_not_a_traceback(tmp_path):
    result = package.build(out_dir=tmp_path / "out", source=tmp_path / "nowhere")
    assert not result["ok"] and "No extension source" in result["message"]


def test_the_checkouts_own_metadata_would_be_accepted():
    metadata = json.loads((package.source_dir() / "metadata.json").read_text())
    assert package.metadata_problems(metadata) == []


def test_a_store_install_counts_as_installed(tmp_path):
    (tmp_path / shell.STORE_EXTENSION_UUID).mkdir()
    assert shell.install_problems(tmp_path) == []
    assert shell.installed_uuid(tmp_path) == shell.STORE_EXTENSION_UUID


def test_two_installs_are_reported_because_they_share_a_bus_name(tmp_path):
    (tmp_path / shell.STORE_EXTENSION_UUID).mkdir()
    (tmp_path / shell.EXTENSION_UUID).mkdir()
    problems = shell.install_problems(tmp_path)
    assert len(problems) == 1 and "two copies" in problems[0]


def test_the_store_uuid_alone_counts_as_enabled(monkeypatch):
    monkeypatch.setattr(shell, "enabled_uuids", lambda: [shell.STORE_EXTENSION_UUID])
    assert shell.is_enabled()


def test_an_unrelated_extension_does_not_count_as_enabled(monkeypatch):
    monkeypatch.setattr(shell, "enabled_uuids", lambda: ["someone-else@example.com"])
    assert not shell.is_enabled()


def test_load_state_asks_about_the_store_uuid_too(monkeypatch):
    asked = []

    class Result:
        def __init__(self, code, out=""):
            self.returncode, self.stdout = code, out

    def fake_run(argv, **kwargs):
        asked.append(argv[-1])
        if argv[-1] == shell.STORE_EXTENSION_UUID:
            return Result(0, "State: ACTIVE\n")
        return Result(2, "")

    monkeypatch.setattr(shell.shutil, "which", lambda name: "/usr/bin/gnome-extensions")
    monkeypatch.setattr(shell.subprocess, "run", fake_run)
    assert shell.load_state() == "active"
    assert asked == [shell.EXTENSION_UUID, shell.STORE_EXTENSION_UUID]


def test_the_wheels_copy_is_used_when_there_is_no_checkout(tmp_path, monkeypatch):
    """`pip install gnomespeak` ships the extension; there is no clone to find."""
    installed = tmp_path / "share" / "gnomespeak" / "gnome-extension" / shell.EXTENSION_UUID
    installed.mkdir(parents=True)
    (installed / "metadata.json").write_text("{}")
    monkeypatch.setattr(
        package, "source_candidates",
        lambda uuid=shell.EXTENSION_UUID: [tmp_path / "nowhere", installed],
    )
    assert package.source_dir() == installed


def test_a_checkout_wins_over_an_installed_copy(tmp_path):
    """A developer installs the tree being edited, not the release beside it."""
    checkout = package.Path(package.__file__).parent.parent
    assert package.source_candidates()[0] == checkout / "gnome-extension" / shell.EXTENSION_UUID


def test_the_installed_copy_is_looked_for_under_the_environments_data_dir():
    paths = [str(p) for p in package.source_candidates()]
    assert any(str(package.DATA_SUBDIR) in p for p in paths)
