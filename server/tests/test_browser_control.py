import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestBrowserControl:
    @pytest.mark.asyncio
    async def test_try_launch_browser_prefers_dedicated_profile(self):
        from handlers.browser_control import BrowserControl

        browser = BrowserControl()
        browser._pw = MagicMock()

        first_context = MagicMock(pages=[])
        second_context = MagicMock(pages=[])

        with patch.object(
            browser,
            "_browser_launch_candidates",
            return_value=[
                {"channel": "chrome", "user_data_dir": Path("C:/voicetalk-chrome")},
                {"channel": "msedge", "user_data_dir": Path("C:/voicetalk-edge")},
            ],
        ):
            with patch.object(
                browser,
                "_launch_persistent_context",
                new=AsyncMock(side_effect=[first_context, second_context]),
            ) as mock_launch:
                result = await browser._try_launch_browser()

        assert result is first_context
        mock_launch.assert_awaited_once_with("chrome", Path("C:/voicetalk-chrome"))

    @pytest.mark.asyncio
    async def test_search_web_uses_default_browser(self):
        from handlers.browser_control import BrowserControl

        browser = BrowserControl()

        with patch.object(
            browser,
            "_open_external_url",
            new=AsyncMock(return_value={"success": True, "message": "ok"}),
        ) as mock_open:
            result = await browser.search_web("python tutorials", "google")

        assert result["success"] is True
        mock_open.assert_awaited_once_with(
            "https://www.google.com/search?q=python%20tutorials",
            "Opened Google search for 'python tutorials' in the default browser",
        )

    @pytest.mark.asyncio
    async def test_yt_search_uses_default_browser(self):
        from handlers.browser_control import BrowserControl

        browser = BrowserControl()

        with patch.object(
            browser,
            "_open_external_url",
            new=AsyncMock(return_value={"success": True, "message": "ok"}),
        ) as mock_open:
            result = await browser.yt_search("cbr 1000 rr fire blade")

        assert result["success"] is True
        mock_open.assert_awaited_once_with(
            "https://www.youtube.com/results?search_query=cbr%201000%20rr%20fire%20blade",
            "Opened YouTube search for 'cbr 1000 rr fire blade' in the default browser",
        )

    @pytest.mark.asyncio
    async def test_try_launch_browser_falls_back_to_next_candidate(self):
        from handlers.browser_control import BrowserControl

        browser = BrowserControl()
        browser._pw = MagicMock()

        context = MagicMock(pages=[])

        with patch.object(
            browser,
            "_browser_launch_candidates",
            return_value=[
                {"channel": "chrome", "user_data_dir": Path("C:/chrome-profile")},
                {"channel": None, "user_data_dir": Path("C:/managed-profile")},
            ],
        ):
            with patch.object(
                browser,
                "_launch_persistent_context",
                new=AsyncMock(side_effect=[RuntimeError("locked profile"), context]),
            ) as mock_launch:
                result = await browser._try_launch_browser()

        assert result is context
        assert mock_launch.await_count == 2

    @pytest.mark.asyncio
    async def test_yt_play_auto_installs_runtime_and_retries(self):
        from handlers.browser_control import BrowserControl

        browser = BrowserControl()

        with patch.object(
            browser,
            "_yt_dlp_search",
            return_value=[{"id": "abc123", "title": "Test Video"}],
        ):
            with patch.object(
                browser,
                "_ensure_browser",
                new=AsyncMock(side_effect=[RuntimeError("missing runtime"), None]),
            ) as mock_ensure:
                with patch(
                    "handlers.browser_control.install_browser_runtime",
                    return_value=(True, "Installed Playwright Chromium"),
                ) as mock_install:
                    with patch.object(
                        browser,
                        "_goto_locked",
                        new=AsyncMock(return_value={"success": True, "message": "ok"}),
                    ) as mock_goto:
                        with patch.object(
                            browser,
                            "_try_click_play_locked",
                            new=AsyncMock(return_value=True),
                        ):
                            result = await browser.yt_play_first("shut novel")

        assert result["success"] is True
        mock_install.assert_called_once_with()
        assert mock_ensure.await_count == 2
        mock_goto.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_yt_play_returns_install_failure_message(self):
        from handlers.browser_control import BrowserControl

        browser = BrowserControl()

        with patch.object(browser, "_yt_dlp_search", return_value=[{"id": "abc123", "title": "Test Video"}]):
            with patch.object(
                browser,
                "_ensure_browser",
                new=AsyncMock(side_effect=RuntimeError("missing runtime")),
            ):
                with patch(
                    "handlers.browser_control.install_browser_runtime",
                    return_value=(False, "Failed to install Playwright Chromium. Check network access and try again."),
                ):
                    result = await browser.yt_play_first("shut novel")

        assert result == {
            "success": False,
            "message": "Failed to install Playwright Chromium. Check network access and try again.",
        }

    @pytest.mark.asyncio
    async def test_yt_play_falls_back_to_default_browser_search_when_no_results(self):
        from handlers.browser_control import BrowserControl

        browser = BrowserControl()

        with patch.object(browser, "_yt_dlp_search", return_value=[]):
            with patch.object(
                browser,
                "_ensure_browser_ready",
                new=AsyncMock(return_value=None),
            ):
                with patch.object(
                    browser,
                    "_open_external_url",
                    new=AsyncMock(return_value={"success": True, "message": "ok", "url": "https://www.youtube.com/results?search_query=the%20office"}),
                ) as mock_open:
                    result = await browser.yt_play_first("the office")

        assert result["success"] is True
        assert result["fallback"] is True
        mock_open.assert_awaited_once_with(
            "https://www.youtube.com/results?search_query=the%20office",
            "Could not find a direct video match. Opened YouTube search results for 'the office' in the default browser",
        )

    @pytest.mark.asyncio
    async def test_launch_persistent_context_ignores_no_sandbox_default_arg(self):
        from handlers.browser_control import BrowserControl

        browser = BrowserControl()
        browser._pw = MagicMock()
        browser._pw.chromium.launch_persistent_context = AsyncMock(return_value=MagicMock())

        await browser._launch_persistent_context("chrome", Path("C:/voicetalk-chrome"))

        launch_call = browser._pw.chromium.launch_persistent_context.await_args
        assert launch_call is not None
        launch_kwargs = launch_call.kwargs
        assert launch_kwargs["ignore_default_args"] == ["--enable-automation", "--no-sandbox"]
