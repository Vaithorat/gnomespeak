import asyncio
import json
import os
import subprocess
import sys
import urllib.parse
import webbrowser
from pathlib import Path

from playwright.async_api import async_playwright
from playwright.__main__ import main as playwright_main


_YT_DLP = [sys.executable, "-m", "yt_dlp"]
_PLAYWRIGHT_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "VoiceTalk" / "ms-playwright"
_LOCALAPPDATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
_BROWSER_PROFILE_ROOT = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "VoiceTalk" / "browser-profiles"
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_PLAYWRIGHT_DIR))


def install_browser_runtime() -> tuple[bool, str]:
    _PLAYWRIGHT_DIR.mkdir(parents=True, exist_ok=True)
    old_argv = list(sys.argv)
    try:
        sys.argv = ["playwright", "install", "chromium"]
        try:
            playwright_main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            if code == 0:
                return True, f"Installed Playwright Chromium into {_PLAYWRIGHT_DIR}"
            return False, "Failed to install Playwright Chromium. Check network access and try again."
        return True, f"Installed Playwright Chromium into {_PLAYWRIGHT_DIR}"
    except Exception:
        return False, "Failed to install Playwright Chromium. Check network access and try again."
    finally:
        sys.argv = old_argv


class BrowserControl:
    def __init__(self):
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._startup_lock = asyncio.Lock()
        self._page_lock = asyncio.Lock()
        self._runtime_install_attempted = False
        self._last_external_url = ""
        self._last_youtube_query = ""

    async def _ensure_browser(self):
        async with self._startup_lock:
            if self._page and not self._page.is_closed():
                return
            if not self._pw:
                self._pw = await async_playwright().start()
            if not self._context:
                self._context = await self._try_launch_browser()
                self._browser = getattr(self._context, "browser", None)
            if not self._page or self._page.is_closed():
                if self._context.pages:
                    self._page = self._context.pages[0]
                else:
                    self._page = await self._context.new_page()

    def _browser_launch_candidates(self) -> list[dict]:
        return [
            {
                "label": "chrome_dedicated",
                "channel": "chrome",
                "user_data_dir": _BROWSER_PROFILE_ROOT / "chrome",
            },
            {
                "label": "edge_dedicated",
                "channel": "msedge",
                "user_data_dir": _BROWSER_PROFILE_ROOT / "edge",
            },
            {
                "label": "chromium_managed",
                "channel": None,
                "user_data_dir": _BROWSER_PROFILE_ROOT / "chromium",
            },
        ]

    async def _launch_persistent_context(self, channel: str | None, user_data_dir: Path):
        user_data_dir.mkdir(parents=True, exist_ok=True)
        launch_kwargs = {
            "user_data_dir": str(user_data_dir),
            "headless": False,
            "args": ["--disable-blink-features=AutomationControlled"],
            "ignore_default_args": ["--enable-automation", "--no-sandbox"],
        }
        if channel:
            launch_kwargs["channel"] = channel
        return await self._pw.chromium.launch_persistent_context(**launch_kwargs)

    async def _open_external_url(self, url: str, message: str) -> dict:
        opened = await asyncio.to_thread(webbrowser.open, url, 0, True)
        if not opened:
            return {"success": False, "message": f"Failed to open {url} in the default browser"}
        self._last_external_url = url
        return {
            "success": True,
            "message": message,
            "url": url,
            "external": True,
        }

    async def _try_launch_browser(self):
        last_error = None
        for candidate in self._browser_launch_candidates():
            try:
                return await self._launch_persistent_context(
                    candidate["channel"],
                    candidate["user_data_dir"],
                )
            except Exception as exc:
                last_error = exc
        if last_error:
            raise last_error
        raise RuntimeError("No browser launch candidates available")

    async def _ensure_browser_ready(self) -> dict | None:
        try:
            await self._ensure_browser()
            return None
        except Exception:
            if self._runtime_install_attempted:
                return {
                    "success": False,
                    "message": "Browser runtime is unavailable. Automatic installation already failed on this run. Open the desktop app and use Install Browser, then try again.",
                }

            self._runtime_install_attempted = True
            success, message = await asyncio.to_thread(install_browser_runtime)
            if not success:
                return {
                    "success": False,
                    "message": message,
                }

            try:
                await self._ensure_browser()
                return None
            except Exception:
                return {
                    "success": False,
                    "message": "Installed Playwright Chromium, but the browser runtime still could not start. Try again from the desktop app after Install Browser completes.",
                }

    async def _goto_locked(self, url: str) -> dict:
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
            title = await self._page.title()
            current_url = self._page.url
            return {
                "success": True,
                "message": f"Opened {title or current_url}",
                "title": title,
                "url": current_url,
            }
        except Exception as e:
            return {"success": False, "message": f"Navigation failed: {e}"}

    async def navigate(self, url: str) -> dict:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        return await self._open_external_url(url, f"Opened {url} in the default browser")

    async def search_web(self, query: str, engine: str = "google") -> dict:
        engine_urls = {
            "google": f"https://www.google.com/search?q={urllib.parse.quote(query)}",
            "bing": f"https://www.bing.com/search?q={urllib.parse.quote(query)}",
            "duckduckgo": f"https://duckduckgo.com/?q={urllib.parse.quote(query)}",
        }
        url = engine_urls.get(engine, engine_urls["google"])
        return await self._open_external_url(url, f"Opened {engine.title()} search for '{query}' in the default browser")

    def _yt_dlp_search(self, query: str, count: int = 1) -> list[dict]:
        try:
            cmd = _YT_DLP + [
                "--flat-playlist",
                "--dump-json",
                "--no-warnings",
                f"ytsearch{count}:{query}",
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                print(f"yt-dlp error: {result.stderr.strip()}")
                return []
            results = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                data = json.loads(line)
                results.append({
                    "id": data.get("id", ""),
                    "title": data.get("title", "Untitled"),
                })
            return results
        except subprocess.TimeoutExpired:
            print("yt-dlp search timed out")
            return []
        except Exception as e:
            print(f"yt-dlp search failed: {e}")
            return []

    async def yt_play_first(self, query: str) -> dict:
        self._last_youtube_query = query.strip()
        results = await asyncio.to_thread(self._yt_dlp_search, query, 1)
        async with self._page_lock:
            runtime_error = await self._ensure_browser_ready()
            if runtime_error:
                return runtime_error
            if results:
                video_id = results[0]["id"]
                title = results[0].get("title", "Unknown")
                watch_url = f"https://www.youtube.com/watch?v={video_id}"
                r = await self._goto_locked(watch_url)
                if r["success"]:
                    autoplay_started = await self._try_click_play_locked()
                    if autoplay_started:
                        r["message"] = f"Playing '{title}' on YouTube"
                    else:
                        r["message"] = f"Opened '{title}' on YouTube, but autoplay was blocked"
                    r["title"] = title
                    r["video_id"] = video_id
                    r["url"] = watch_url
                    r["fallback"] = False
                    r["autoplay_started"] = autoplay_started
                return r
            encoded = urllib.parse.quote(query)
            url = f"https://www.youtube.com/results?search_query={encoded}"
            r = await self._open_external_url(
                url,
                f"Could not find a direct video match. Opened YouTube search results for '{query}' in the default browser",
            )
            if r["success"]:
                r["title"] = None
                r["fallback"] = True
                r["query"] = query
            return r

    async def yt_play_first_result(self) -> dict:
        query = self._last_youtube_query.strip()
        if not query:
            return {
                "success": False,
                "message": "No recent YouTube search is available yet. Search YouTube first, then ask to play the first video.",
            }
        return await self.yt_play_first(query)

    async def _try_click_play_locked(self) -> bool:
        try:
            await self._page.wait_for_selector("video", timeout=5000)
            return bool(await self._page.evaluate("""
                const v = document.querySelector('video');
                if (!v) return false;
                if (v.paused) {
                    try { await v.play(); } catch (e) {}
                }
                return !v.paused;
            """))
        except Exception:
            return False

    async def yt_search(self, query: str) -> dict:
        self._last_youtube_query = query.strip()
        encoded = urllib.parse.quote(query)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        return await self._open_external_url(url, f"Opened YouTube search for '{query}' in the default browser")

    async def yt_results(self, query: str) -> dict:
        results = await asyncio.to_thread(self._yt_dlp_search, query, 10)
        if results:
            lines = [f"{i+1}. {r['title']} — https://www.youtube.com/watch?v={r['id']}" for i, r in enumerate(results)]
            return {"success": True, "message": f"Found {len(results)} results", "results": results, "formatted": "\n".join(lines)}
        return {"success": False, "message": "No results found"}

    async def status(self) -> dict:
        async with self._page_lock:
            if self._page and not self._page.is_closed():
                title = await self._page.title()
                return {"success": True, "message": f"Browser open: {title} — {self._page.url}"}
            if self._last_external_url:
                return {"success": True, "message": f"Default browser last opened: {self._last_external_url}"}
            return {"success": True, "message": "Browser not open yet"}

    async def close(self) -> dict:
        async with self._page_lock:
            try:
                if self._page and not self._page.is_closed():
                    await self._page.close()
                if self._context:
                    await self._context.close()
                if self._browser:
                    await self._browser.close()
                if self._pw:
                    await self._pw.stop()
            except Exception:
                pass
            self._page = None
            self._context = None
            self._browser = None
            self._pw = None
            return {"success": True, "message": "Browser closed"}

    def dump_tools(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "browser_navigate",
                    "description": "Open a website in the browser. All navigation happens in the same browser tab — does NOT open new tabs.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "The URL or website name to open",
                            }
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_search",
                    "description": "Search the web for a query using a search engine (opens in same browser tab)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The search query",
                            },
                            "engine": {
                                "type": "string",
                                "enum": ["google", "bing", "duckduckgo"],
                                "description": "Search engine to use (default: google)",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "yt_play",
                    "description": "Search YouTube and open the first matching video in the SAME browser tab. It attempts autoplay and reports if playback was blocked.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Song name, video title, or search query",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "yt_search",
                    "description": "Open YouTube search results page for browsing (same tab, does not autoplay)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query for YouTube",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "yt_results",
                    "description": "Fetch top YouTube search results with titles and URLs (use when user wants to pick a specific video from results)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query for YouTube",
                            }
                        },
                        "required": ["query"],
                    },
                },
            },
        ]
