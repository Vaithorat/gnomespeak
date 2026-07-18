import pytest
import asyncio
from unittest.mock import AsyncMock, patch
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from safety import SafetyChecker, DESTRUCTIVE_TOOLS


class TestSafetyChecker:
    def setup_method(self):
        self.checker = SafetyChecker()

    def test_destructive_tools_list(self):
        assert "delete" in DESTRUCTIVE_TOOLS
        assert "move" in DESTRUCTIVE_TOOLS
        assert "copy" in DESTRUCTIVE_TOOLS
        assert "create_file" in DESTRUCTIVE_TOOLS

    @pytest.mark.asyncio
    async def test_non_destructive_tools_pass_through(self):
        result = await self.checker.check("list_dir", {"path": "."})
        assert result is None

    @pytest.mark.asyncio
    async def test_non_destructive_tools_pass_through_2(self):
        result = await self.checker.check("open_app", {"name": "notepad"})
        assert result is None

    @pytest.mark.asyncio
    async def test_non_destructive_tools_pass_through_3(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "Yes, open it"}

        result = await self.checker.check("browser_navigate", {"url": "google.com"}, mock_ask)
        assert result is None

    @pytest.mark.asyncio
    async def test_browser_navigate_cancelled(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "No, cancel"}

        result = await self.checker.check("browser_navigate", {"url": "google.com"}, mock_ask)
        assert result is not None
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_delete_confirmed(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "Yes, delete it"}

        result = await self.checker.check("delete", {"path": "/tmp/test.txt"}, mock_ask)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_cancelled(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "No, cancel"}

        result = await self.checker.check("delete", {"path": "/tmp/test.txt"}, mock_ask)
        assert result is not None
        assert result["success"] is False
        assert "cancelled" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_no_callback_defaults_to_deny(self):
        result = await self.checker.check("delete", {"path": "/tmp/test.txt"}, None)
        assert result is not None
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_delete_empty_path_passes_through(self):
        result = await self.checker.check("delete", {"path": ""})
        assert result is None

    @pytest.mark.asyncio
    async def test_move_confirmed(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "Yes, move it"}

        result = await self.checker.check("move", {"source": "/tmp/a.txt", "destination": "/tmp/b.txt"}, mock_ask)
        assert result is None

    @pytest.mark.asyncio
    async def test_move_cancelled(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "No, cancel"}

        result = await self.checker.check("move", {"source": "/tmp/a.txt", "destination": "/tmp/b.txt"}, mock_ask)
        assert result is not None
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_move_destination_exists_cancelled(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "No, cancel"}

        with patch("safety.Path.exists", return_value=True):
            result = await self.checker.check("move", {"source": "/tmp/a.txt", "destination": "/tmp/b.txt"}, mock_ask)
            assert result is not None
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_copy_destination_exists_confirmed(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "Yes, overwrite"}

        with patch("safety.os.path.exists", return_value=True):
            result = await self.checker.check("copy", {"source": "/tmp/a.txt", "destination": "/tmp/b.txt"}, mock_ask)
            assert result is None

    @pytest.mark.asyncio
    async def test_copy_destination_exists_cancelled(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "No, cancel"}

        with patch("safety.os.path.exists", return_value=True):
            result = await self.checker.check("copy", {"source": "/tmp/a.txt", "destination": "/tmp/b.txt"}, mock_ask)
            assert result is not None
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_copy_destination_not_exists_passes_through(self):
        with patch("safety.os.path.exists", return_value=False):
            result = await self.checker.check("copy", {"source": "/tmp/a.txt", "destination": "/tmp/b.txt"})
            assert result is None

    @pytest.mark.asyncio
    async def test_create_file_exists_confirmed(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "Yes, overwrite"}

        with patch("safety.os.path.exists", return_value=True):
            result = await self.checker.check("create_file", {"path": "/tmp/test.txt"}, mock_ask)
            assert result is None

    @pytest.mark.asyncio
    async def test_create_file_exists_cancelled(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "No, cancel"}

        with patch("safety.os.path.exists", return_value=True):
            result = await self.checker.check("create_file", {"path": "/tmp/test.txt"}, mock_ask)
            assert result is not None
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_create_file_outside_allowlist_no_callback_denies(self):
        with patch("safety.os.path.exists", return_value=False):
            result = await self.checker.check("create_file", {"path": "/tmp/new.txt"})
            assert result is not None
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_create_file_empty_path_passes_through(self):
        result = await self.checker.check("create_file", {"path": ""})
        assert result is None

    @pytest.mark.asyncio
    async def test_disabled_checker_passes_all(self):
        self.checker.enabled = False
        result = await self.checker.check("delete", {"path": "/tmp/test.txt"})
        assert result is None

    @pytest.mark.asyncio
    async def test_open_app_resolved_target_blocked(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "No, cancel"}

        result = await self.checker.check(
            "open_app",
            {"name": "terminal", "_resolved_path": r"C:\Windows\System32\cmd.exe"},
            mock_ask,
        )
        assert result is not None
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_play_media_cancelled(self):
        async def mock_ask(q, opts):
            return {"success": True, "text": "No, cancel"}

        result = await self.checker.check("play_media", {"query": "song"}, mock_ask)
        assert result is not None
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_exception_in_ask_defaults_to_deny(self):
        async def bad_ask(q, opts):
            raise RuntimeError("WebSocket disconnected")

        result = await self.checker.check("delete", {"path": "/tmp/test.txt"}, bad_ask)
        assert result is not None
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_ask_returns_string_confirmed(self):
        async def mock_ask(q, opts):
            return "yes"

        result = await self.checker.check("delete", {"path": "/tmp/test.txt"}, mock_ask)
        assert result is None

    @pytest.mark.asyncio
    async def test_ask_returns_string_cancelled(self):
        async def mock_ask(q, opts):
            return "no"

        result = await self.checker.check("delete", {"path": "/tmp/test.txt"}, mock_ask)
        assert result is not None
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_move_ask_has_correct_options(self):
        captured_opts = []

        async def mock_ask(q, opts):
            captured_opts.extend(opts)
            return {"success": True, "text": "Yes, move it"}

        await self.checker.check("move", {"source": "/tmp/a.txt", "destination": "/tmp/b.txt"}, mock_ask)
        assert "Yes, move it" in captured_opts
        assert "No, cancel" in captured_opts

    @pytest.mark.asyncio
    async def test_delete_ask_mentions_cannot_be_undone(self):
        captured_q = []

        async def mock_ask(q, opts):
            captured_q.append(q)
            return {"success": True, "text": "Yes, delete it"}

        await self.checker.check("delete", {"path": "/tmp/test.txt"}, mock_ask)
        assert len(captured_q) == 1
        assert "cannot be undone" in captured_q[0].lower()
