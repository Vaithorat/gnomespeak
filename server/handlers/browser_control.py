import json
import subprocess
import sys
import urllib.parse

from playwright.async_api import async_playwright


_YT_DLP = [sys.executable, "-m", "yt_dlp"]


class BrowserControl:
    def __init__(self):
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    async def _ensure_browser(self):
        if self._page and not self._page.is_closed():
            return
        if not self._pw:
            self._pw = await async_playwright().start()
        if not self._browser:
            self._browser = await self._pw.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
        if not self._context:
            self._context = await self._browser.new_context()
        if not self._page or self._page.is_closed():
            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = await self._context.new_page()

    async def _goto(self, url: str) -> dict:
        await self._ensure_browser()
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
        return await self._goto(url)

    async def search_web(self, query: str, engine: str = "google") -> dict:
        engine_urls = {
            "google": f"https://www.google.com/search?q={urllib.parse.quote(query)}",
            "bing": f"https://www.bing.com/search?q={urllib.parse.quote(query)}",
            "duckduckgo": f"https://duckduckgo.com/?q={urllib.parse.quote(query)}",
        }
        url = engine_urls.get(engine, engine_urls["google"])
        return await self._goto(url)

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
        results = self._yt_dlp_search(query, count=1)
        if results:
            video_id = results[0]["id"]
            title = results[0].get("title", "Unknown")
            watch_url = f"https://www.youtube.com/watch?v={video_id}"
            r = await self._goto(watch_url)
            if r["success"]:
                await self._try_click_play()
                r["message"] = f"Playing '{title}' on YouTube"
                r["title"] = title
                r["video_id"] = video_id
                r["url"] = watch_url
                r["fallback"] = False
            return r
        encoded = urllib.parse.quote(query)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        r = await self._goto(url)
        if r["success"]:
            r["message"] = f"Could not find video. Opened search results for '{query}'"
            r["title"] = None
            r["fallback"] = True
            r["query"] = query
        return r

    async def _try_click_play(self):
        try:
            await self._page.wait_for_selector("video", timeout=5000)
            await self._page.evaluate("""
                const v = document.querySelector('video');
                if (v && v.paused) { v.play(); }
            """)
        except Exception:
            pass

    async def yt_search(self, query: str) -> dict:
        encoded = urllib.parse.quote(query)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        return await self._goto(url)

    async def yt_results(self, query: str) -> dict:
        results = self._yt_dlp_search(query, count=10)
        if results:
            lines = [f"{i+1}. {r['title']} — https://www.youtube.com/watch?v={r['id']}" for i, r in enumerate(results)]
            return {"success": True, "message": f"Found {len(results)} results", "results": results, "formatted": "\n".join(lines)}
        return {"success": False, "message": "No results found"}

    async def status(self) -> dict:
        if self._page and not self._page.is_closed():
            title = await self._page.title()
            return {"success": True, "message": f"Browser open: {title} — {self._page.url}"}
        return {"success": True, "message": "Browser not open yet"}

    async def close(self) -> dict:
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
                    "description": "Search YouTube and play the first matching video. Opens in the SAME browser tab, finds the video, navigates to it, and auto-plays it. This is the ONLY tool you need for 'play X on YouTube' requests.",
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
