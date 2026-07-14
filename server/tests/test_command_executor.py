import pytest
import asyncio
import os
import tempfile
import shutil
from unittest.mock import patch, MagicMock, AsyncMock
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestCommandExecutorNonDestructive:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_executor(self):
        from unittest.mock import MagicMock
        mock_config = MagicMock()
        mock_config.get_secret.return_value = None
        from command_executor import CommandExecutor
        return CommandExecutor(mock_config)

    def test_executor_initializes(self):
        executor = self._make_executor()
        assert executor.file_ops is not None
        assert executor.app_launcher is not None
        assert executor.browser is not None
        assert executor.bluetooth is not None
        assert executor.media_player is not None
        assert executor.media_control is not None
        assert executor.safety is not None
        assert executor.env_model is not None

    @pytest.mark.asyncio
    async def test_list_dir(self):
        executor = self._make_executor()
        result = await executor.execute_tool("list_dir", {"path": "."})
        assert result["success"] is True
        assert "Contents of" in result["message"]

    @pytest.mark.asyncio
    async def test_list_dir_nonexistent(self):
        executor = self._make_executor()
        result = await executor.execute_tool("list_dir", {"path": "C:\\nonexistent_12345"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_navigate(self):
        executor = self._make_executor()
        with patch("handlers.file_ops.os.startfile"):
            result = await executor.execute_tool("navigate", {"path": self.tmpdir})
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_file(self):
        executor = self._make_executor()
        test_file = os.path.join(self.tmpdir, "test.txt")
        result = await executor.execute_tool("create_file", {"path": test_file, "content": "hello"})
        assert result["success"] is True
        assert os.path.exists(test_file)

    @pytest.mark.asyncio
    async def test_create_folder(self):
        executor = self._make_executor()
        test_dir = os.path.join(self.tmpdir, "new_dir")
        result = await executor.execute_tool("create_folder", {"path": test_dir})
        assert result["success"] is True
        assert os.path.isdir(test_dir)

    @pytest.mark.asyncio
    async def test_get_system_info(self):
        executor = self._make_executor()
        result = await executor.execute_tool("get_system_info", {})
        assert result["success"] is True
        assert "info" in result
        assert "os" in result["info"]

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        executor = self._make_executor()
        result = await executor.execute_tool("nonexistent_tool", {})
        assert result["success"] is False
        assert "Unknown tool" in result["message"]

    @pytest.mark.asyncio
    async def test_media_control_play_pause(self):
        executor = self._make_executor()
        with patch.object(executor.media_control, 'execute', return_value={"success": True, "message": "ok"}):
            result = await executor.execute_tool("media_control", {"action": "play_pause"})
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_volume_set(self):
        executor = self._make_executor()
        with patch.object(executor.media_player, 'set_volume', return_value={"success": True, "message": "ok"}):
            result = await executor.execute_tool("set_volume", {"level": 75})
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_volume_set_invalid_level(self):
        executor = self._make_executor()
        with patch.object(executor.media_player, 'set_volume', return_value={"success": True, "message": "ok"}) as mock:
            result = await executor.execute_tool("set_volume", {"level": "not_a_number"})
            mock.assert_called_once_with(50)

    @pytest.mark.asyncio
    async def test_bluetooth_status(self):
        executor = self._make_executor()
        with patch.object(executor.bluetooth, 'status', return_value={"success": True, "message": "ok"}):
            result = await executor.execute_tool("control_bluetooth", {"action": "status"})
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_safety_blocks_delete(self):
        executor = self._make_executor()
        async def deny_ask(q, opts):
            return {"success": True, "text": "No, cancel"}

        with patch.object(executor.file_ops, 'delete') as mock_delete:
            result = await executor.execute_tool("delete", {"path": "test.txt"}, ask_callback=deny_ask)
            assert result["success"] is False
            assert "cancelled" in result["message"].lower()
            mock_delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_safety_allows_list_dir(self):
        executor = self._make_executor()
        result = await executor.execute_tool("list_dir", {"path": "."}, ask_callback=None)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_dict(self):
        executor = self._make_executor()
        result = await executor.execute({"action": "get_system_info", "params": {}})
        assert result["success"] is True
