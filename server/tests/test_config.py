import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module
from config import Config, ConfigUnlockError


class TestConfig:
    def test_relative_config_path_uses_appdata(self, tmp_path, monkeypatch):
        appdata_dir = tmp_path / "AppData" / "Roaming" / "VoiceTalk"
        monkeypatch.setattr(config_module, "_APPDATA_DIR", appdata_dir)

        cfg = Config("config.json")

        assert cfg.config_path == (appdata_dir / "config.json").resolve()

    def test_absolute_config_path_is_preserved(self, tmp_path):
        config_path = (tmp_path / "custom.json").resolve()

        cfg = Config(str(config_path))

        assert cfg.config_path == config_path

    def test_auto_unlock_does_not_silently_reset_wrong_master(self, tmp_path):
        config_path = tmp_path / "config.json"
        cfg = Config(str(config_path))
        cfg.auto_unlock()
        cfg.set_secret("api_key", "secret")
        cfg.save()
        cfg._master_path.write_text("wrong-master")

        broken = Config(str(config_path))
        with pytest.raises(ConfigUnlockError):
            broken.auto_unlock()

        assert broken._master_path.read_text() == "wrong-master"
        assert broken.data["encrypted_data"] == cfg.data["encrypted_data"]

    def test_restore_master_backup_replaces_master(self, tmp_path):
        cfg = Config(str(tmp_path / "config.json"))
        cfg._master_backup_path.write_text("backup-master")
        cfg._master_path.write_text("current-master")

        cfg.restore_master_backup()

        assert cfg._master_path.read_text() == "backup-master"
        assert cfg._master_backup_path.read_text() == "backup-master"

    def test_reset_encrypted_config_clears_data_and_keeps_master_backup(self, tmp_path):
        cfg = Config(str(tmp_path / "config.json"))
        cfg.auto_unlock()
        old_master = cfg._master_path.read_text()
        cfg.set_secret("api_key", "secret")
        cfg.save()

        cfg.reset_encrypted_config()

        assert cfg.data["encrypted_data"] is None
        assert cfg.data["salt"] is None
        assert cfg._master_backup_path.read_text() == old_master
        assert cfg._master_path.read_text() != old_master
        saved = Config(str(tmp_path / "config.json"))
        assert saved.data["encrypted_data"] is None
