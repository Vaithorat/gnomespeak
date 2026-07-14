import pytest
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestMediaControl:
    def setup_method(self):
        from handlers.media_control import MediaControl
        self.mc = MediaControl()

    def test_all_actions_return_dicts(self):
        actions = [
            "play_pause", "next_track", "prev_track", "volume_up",
            "volume_down", "mute", "fullscreen", "refresh",
            "forward", "backward", "escape", "enter", "tab"
        ]
        for action in actions:
            with patch("handlers.media_control.pyautogui") as mock_pg:
                result = self.mc.execute(action)
                assert isinstance(result, dict)
                assert "success" in result
                assert "message" in result

    def test_play_pause_calls_space(self):
        with patch("handlers.media_control.pyautogui") as mock_pg:
            self.mc.execute("play_pause")
            mock_pg.press.assert_called_once_with("space")

    def test_fullscreen_calls_f11(self):
        with patch("handlers.media_control.pyautogui") as mock_pg:
            self.mc.execute("fullscreen")
            mock_pg.press.assert_called_once_with("f11")

    def test_refresh_calls_f5(self):
        with patch("handlers.media_control.pyautogui") as mock_pg:
            self.mc.execute("refresh")
            mock_pg.press.assert_called_once_with("f5")

    def test_next_track(self):
        with patch("handlers.media_control.pyautogui") as mock_pg:
            self.mc.execute("next_track")
            mock_pg.press.assert_called_once_with("nexttrack")

    def test_prev_track(self):
        with patch("handlers.media_control.pyautogui") as mock_pg:
            self.mc.execute("prev_track")
            mock_pg.press.assert_called_once_with("prevtrack")

    def test_unknown_action(self):
        result = self.mc.execute("nonexistent_action")
        assert result["success"] is False
        assert "Unknown action" in result["message"]

    def test_action_normalization(self):
        with patch("handlers.media_control.pyautogui") as mock_pg:
            self.mc.execute("play-pause")
            mock_pg.press.assert_called_once_with("space")

    def test_action_normalization_space(self):
        with patch("handlers.media_control.pyautogui") as mock_pg:
            self.mc.execute("next track")
            mock_pg.press.assert_called_once_with("nexttrack")

    def test_forward_calls_right_arrow(self):
        with patch("handlers.media_control.pyautogui") as mock_pg:
            self.mc.execute("forward")
            mock_pg.press.assert_called_once_with("right")

    def test_backward_calls_left_arrow(self):
        with patch("handlers.media_control.pyautogui") as mock_pg:
            self.mc.execute("backward")
            mock_pg.press.assert_called_once_with("left")
