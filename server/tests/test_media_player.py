import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handlers.media_player import MediaPlayer


class TestMediaPlayer:
    def test_set_volume_com_uses_endpoint_volume(self):
        endpoint = MagicMock()

        with patch.object(MediaPlayer, "_get_endpoint_volume", return_value=endpoint):
            result = MediaPlayer._set_volume_com(100)

        endpoint.SetMasterVolumeLevelScalar.assert_called_once_with(1.0, None)
        assert result == {"success": True, "message": "Volume set to 100%"}

    def test_set_volume_clamps_level(self):
        player = MediaPlayer()

        with patch.object(player, "_set_volume_com", return_value={"success": True, "message": "ok"}) as mock_set:
            result = player.set_volume(150)

        mock_set.assert_called_once_with(100)
        assert result["success"] is True

    def test_set_volume_returns_error_when_endpoint_access_fails(self):
        with patch.object(MediaPlayer, "_get_endpoint_volume", side_effect=AttributeError("missing endpoint")):
            result = MediaPlayer._set_volume_com(100)

        assert result["success"] is False
        assert "missing endpoint" in result["message"]
