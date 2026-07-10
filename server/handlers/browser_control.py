import urllib.parse
import webbrowser


class BrowserControl:
    def navigate(self, url: str) -> dict:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
            return {"success": True, "message": f"Opened {url} in browser"}
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to open browser: {str(e)}",
            }

    def search_web(self, query: str, engine: str = "google") -> dict:
        engine_urls = {
            "google": f"https://www.google.com/search?q={urllib.parse.quote(query)}",
            "bing": f"https://www.bing.com/search?q={urllib.parse.quote(query)}",
            "duckduckgo": f"https://duckduckgo.com/?q={urllib.parse.quote(query)}",
        }
        url = engine_urls.get(engine, engine_urls["google"])
        return self.navigate(url)

    def yt_play_first(self, query: str) -> dict:
        encoded = urllib.parse.quote(query)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        r = self.navigate(url)
        if r["success"]:
            r["message"] = f"Opened YouTube search results for '{query}'"
        return r

    def status(self) -> dict:
        return {
            "success": True,
            "message": "Browser actions open URLs in the default browser",
        }

    def close(self) -> dict:
        return {"success": False, "message": "Cannot close browser via URL-based control"}

    def dump_tools(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "browser_navigate",
                    "description": "Open a website in the default browser",
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
                    "description": "Search the web for a query using a search engine",
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
                    "description": "Search YouTube and open the results page for a song or video",
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
        ]
