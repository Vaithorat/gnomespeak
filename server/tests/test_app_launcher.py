import pytest
import os
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handlers.app_launcher import AppLauncher


class TestAppLauncher:
    def setup_method(self):
        self.launcher = AppLauncher()

    def test_aliases_defined(self):
        assert "browser" in self.launcher.aliases
        assert "terminal" in self.launcher.aliases
        assert "notepad" in self.launcher.aliases
        assert "calculator" in self.launcher.aliases
        assert "vs code" in self.launcher.aliases

    def test_find_app_with_alias(self):
        with patch.object(self.launcher, '_search_name', return_value="C:\\path\\to\\notepad.exe"):
            result = self.launcher.find_app("notepad")
            assert result == "C:\\path\\to\\notepad.exe"

    def test_find_app_alias_expansion(self):
        with patch.object(self.launcher, '_search_name', return_value="C:\\path\\to\\chrome.exe"):
            result = self.launcher.find_app("browser")
            assert result == "C:\\path\\to\\chrome.exe"

    def test_find_app_no_match(self):
        with patch.object(self.launcher, '_search_name', return_value=None):
            result = self.launcher.find_app("nonexistent_app_xyz")
            assert result is None

    def test_find_app_strips_quotes(self):
        with patch.object(self.launcher, 'find_app', wraps=self.launcher.find_app) as mock_find:
            with patch.object(self.launcher, '_search_name', return_value=None):
                with patch.object(self.launcher, '_search_with_powershell', return_value=None):
                    self.launcher.launch('"notepad"')
                    # The launch method strips quotes before calling find_app
                    mock_find.assert_called_with("notepad")

    def test_launch_found(self):
        with patch.object(self.launcher, 'find_app', return_value="C:\\path\\to\\app.exe"):
            with patch("handlers.app_launcher.os.startfile") as mock_start:
                result = self.launcher.launch("notepad")
                assert result["success"] is True
                mock_start.assert_called_once_with("C:\\path\\to\\app.exe")

    def test_launch_uses_resolved_path(self):
        with patch.object(self.launcher, 'find_app') as mock_find:
            with patch("handlers.app_launcher.os.startfile") as mock_start:
                result = self.launcher.launch("notepad", "C:\\resolved\\app.exe")
                assert result["success"] is True
                mock_start.assert_called_once_with("C:\\resolved\\app.exe")
                mock_find.assert_not_called()

    def test_launch_not_found_fallback(self):
        with patch.object(self.launcher, 'find_app', return_value=None):
            result = self.launcher.launch("some_weird_app")
            assert result["success"] is False
            assert "App not found" in result["message"]

    def test_launch_error(self):
        with patch.object(self.launcher, 'find_app', return_value="C:\\path\\to\\app.exe"):
            with patch("handlers.app_launcher.os.startfile", side_effect=OSError("Permission denied")):
                result = self.launcher.launch("notepad")
                assert result["success"] is False
                assert "Failed to open" in result["message"]

    def test_launch_not_found_error(self):
        with patch.object(self.launcher, 'find_app', return_value=None):
            result = self.launcher.launch("nonexistent")
            assert result["success"] is False
            assert "App not found" in result["message"]

    def test_search_name_returns_none_for_nonexistent(self):
        result = self.launcher._search_name("totally_nonexistent_app_12345")
        assert result is None

    def test_env_model_integration(self):
        mock_model = MagicMock()
        mock_model.get_app_path.return_value = "C:\\cached\\app.exe"
        launcher = AppLauncher(env_model=mock_model)
        result = launcher.find_app("notepad")
        assert result == "C:\\cached\\app.exe"
        mock_model.get_app_path.assert_called_once_with("notepad")

    def test_resolve_cached(self):
        mock_model = MagicMock()
        mock_model.get_app_path.return_value = "C:\\cached\\only.exe"
        launcher = AppLauncher(env_model=mock_model)
        result = launcher.resolve_cached("Notepad")
        assert result == "C:\\cached\\only.exe"
        mock_model.get_app_path.assert_called_once_with("notepad")

    def test_env_model_cache_miss_falls_through(self):
        mock_model = MagicMock()
        mock_model.get_app_path.return_value = None
        launcher = AppLauncher(env_model=mock_model)
        with patch.object(launcher, '_search_with_powershell', return_value=None):
            with patch.object(launcher, '_search_name', return_value=None):
                result = launcher.find_app("nonexistent")
                assert result is None
                mock_model.get_app_path.assert_called_once()

    def test_search_with_powershell_escapes_quotes(self):
        with patch("handlers.app_launcher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            self.launcher._search_with_powershell("test'app")
            call_args = mock_run.call_args
            cmd = call_args[0][0]
            ps_cmd = cmd[-1]
            assert "test''app" in ps_cmd

    def test_get_start_menu_dirs(self):
        dirs = self.launcher._get_start_menu_dirs()
        assert len(dirs) >= 1
        for d in dirs:
            assert "Start Menu" in str(d)

    def test_common_dirs_defined(self):
        assert len(self.launcher.common_dirs) >= 2
        for d in self.launcher.common_dirs:
            assert isinstance(d, type(self.launcher.common_dirs[0]))
