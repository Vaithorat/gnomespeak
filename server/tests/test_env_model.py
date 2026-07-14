import pytest
import asyncio
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from env_model import EnvironmentModel


class TestEnvironmentModel:
    def setup_method(self):
        self.model = EnvironmentModel()

    def test_initial_state(self):
        assert self.model.desktop_files == {}
        assert self.model.installed_apps == {}
        assert self.model.recent_folders == {}
        assert self.model._last_full_refresh == 0
        assert self.model._initialized is False

    def test_build_context_prompt_empty(self):
        prompt = self.model.build_context_prompt()
        assert "## Current Environment" in prompt

    def test_build_context_prompt_with_desktop_files(self):
        self.model.desktop_files = {
            "test.txt": {"name": "test.txt", "is_dir": False, "extension": ".txt"},
            "MyFolder": {"name": "MyFolder", "is_dir": True, "extension": ""},
        }
        prompt = self.model.build_context_prompt()
        assert "Desktop files:" in prompt
        assert "test.txt" in prompt
        assert "MyFolder" in prompt

    def test_build_context_prompt_with_apps(self):
        self.model.installed_apps = {
            "notepad": "C:\\Windows\\notepad.exe",
            "calc": "C:\\Windows\\calc.exe",
        }
        prompt = self.model.build_context_prompt()
        assert "Installed apps" in prompt
        assert "notepad" in prompt
        assert "calc" in prompt

    def test_build_context_prompt_with_recent_folders(self):
        self.model.recent_folders = {
            "C:\\Users\\test": {
                "path": "C:\\Users\\test",
                "items": [{"name": "file1.txt", "is_dir": False}],
            }
        }
        prompt = self.model.build_context_prompt()
        assert "Recently accessed folders" in prompt
        assert "C:\\Users\\test" in prompt

    def test_get_app_path_found(self):
        self.model.installed_apps = {"notepad": "C:\\Windows\\notepad.exe"}
        result = self.model.get_app_path("notepad")
        assert result == "C:\\Windows\\notepad.exe"

    def test_get_app_path_partial_match(self):
        self.model.installed_apps = {"visual studio code": "C:\\VSCode\\code.exe"}
        result = self.model.get_app_path("code")
        assert result == "C:\\VSCode\\code.exe"

    def test_get_app_path_not_found(self):
        self.model.installed_apps = {"notepad": "C:\\Windows\\notepad.exe"}
        result = self.model.get_app_path("nonexistent")
        assert result is None

    def test_get_app_path_case_insensitive(self):
        self.model.installed_apps = {"spotify": "C:\\Spotify\\spotify.exe"}
        result = self.model.get_app_path("Spotify")
        assert result == "C:\\Spotify\\spotify.exe"

    @pytest.mark.asyncio
    async def test_refresh_folder(self):
        tmpdir = tempfile.mkdtemp()
        try:
            await self.model.refresh_folder(tmpdir)
            assert tmpdir in self.model.recent_folders
            info = self.model.recent_folders[tmpdir]
            assert info["path"] == tmpdir
            assert isinstance(info["items"], list)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_refresh_folder_nonexistent(self):
        await self.model.refresh_folder("C:\\nonexistent_path_12345")
        assert "C:\\nonexistent_path_12345" not in self.model.recent_folders

    @pytest.mark.asyncio
    async def test_refresh_folder_eviction(self):
        tmpdirs = []
        for i in range(10):
            d = tempfile.mkdtemp()
            tmpdirs.append(d)
            self.model.recent_folders[d] = {
                "path": d,
                "items": [],
            }
        try:
            extra = tempfile.mkdtemp()
            tmpdirs.append(extra)
            await self.model.refresh_folder(extra)
            assert len(self.model.recent_folders) == 10
        finally:
            for d in tmpdirs:
                shutil.rmtree(d, ignore_errors=True)

    def test_build_context_prompt_truncates_desktop(self):
        for i in range(250):
            self.model.desktop_files[f"file_{i}.txt"] = {
                "name": f"file_{i}.txt",
                "is_dir": False,
                "extension": ".txt",
            }
        prompt = self.model.build_context_prompt()
        assert "file_0.txt" in prompt
        assert "file_29.txt" in prompt
        lines = [l for l in prompt.split("\n") if l.strip().startswith("- file_")]
        assert len(lines) <= 30

    def test_build_context_prompt_truncates_apps(self):
        for i in range(100):
            self.model.installed_apps[f"app_{i}"] = f"C:\\app_{i}.exe"
        prompt = self.model.build_context_prompt()
        lines = [l for l in prompt.split("\n") if l.strip().startswith("- app_")]
        assert len(lines) <= 50

    @pytest.mark.asyncio
    async def test_initialize_calls_full_refresh(self):
        with patch.object(self.model, '_full_refresh') as mock_refresh:
            await self.model.initialize()
            mock_refresh.assert_called_once()
            assert self.model._initialized is True

    @pytest.mark.asyncio
    async def test_refresh_if_stale_when_stale(self):
        self.model._last_full_refresh = 0
        self.model._refresh_interval = 0
        with patch.object(self.model, '_full_refresh') as mock_refresh:
            with patch('asyncio.create_task') as mock_task:
                await self.model.refresh_if_stale()
                mock_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_if_stale_when_fresh(self):
        import time
        self.model._last_full_refresh = time.time()
        self.model._refresh_interval = 900
        with patch.object(self.model, '_full_refresh') as mock_refresh:
            await self.model.refresh_if_stale()
            mock_refresh.assert_not_called()
