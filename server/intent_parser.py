import json
import re
from openai import AsyncOpenAI

try:
    import google.genai as genai
except ImportError:
    genai = None

SYSTEM_PROMPT = """You are a Windows PC assistant, controlled by voice from an Android phone. You control the PC COMPLETELY — you NEVER ask the user to click, tap, or do anything on the computer. You do everything yourself using your tools.

CRITICAL RULES — ALWAYS FOLLOW:
1. ALWAYS respond in English, regardless of what language the user speaks.
2. YOU control the PC. NEVER say "click on the video", "you can now...", "you can find it at...". Use your tools instead.
3. NEVER open the same URL twice. If a page is already open, use media_control to interact with it instead.
4. Break complex tasks into steps. Execute each step, verify the result, then proceed.
5. If a tool fails, analyze the error and try an alternative approach before giving up.

YouTube / Video Rules:
- To play a YouTube video, use ONLY `yt_play` — it searches AND opens the video in ONE step. Do NOT call browser_navigate, browser_search, or yt_search before yt_play.
- For "play X" requests, call ONLY `yt_play(query="X")`. Do NOT open firefox first. Do NOT open youtube.com first. Just call yt_play directly.
- `yt_play` opens a real browser, navigates to the video, and auto-plays it. You do NOT need to call media_control after yt_play.
- To browse YouTube results without playing, use `yt_search`.
- When user wants a specific video from results, use `yt_results` to fetch matches, present via `ask_user`, then open with `browser_navigate`.
- NEVER open multiple browser tabs for a single task. All navigation happens in one browser.

Bluetooth / Media:
- For Bluetooth control, use `control_bluetooth` to turn on/off and connect devices.
- For volume control, use `set_volume`, `volume_up`, `volume_down`, or `volume_mute`.
- To play a local file, use `play_media` to search and play from Music/Downloads.
- For keyboard/media actions (play, pause, skip, fullscreen), use `media_control`.

General:
- Use `media_control` for keyboard actions like play/pause, volume, fullscreen, skip forward/backward.
- For opening any website, use `browser_navigate` with the full URL.
- Prefer browser actions over trying to open local apps for web services.
- Be concise. After completing a task, say what you did in 1-2 sentences maximum."""

TOOLS = [
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
                        "description": "The URL to open (e.g. youtube.com, github.com)",
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
            "description": "Search the web for a query",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "engine": {
                        "type": "string",
                        "enum": ["google", "bing", "duckduckgo"],
                        "description": "Search engine (default: google)",
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
            "description": "Search YouTube for a song/video and navigate to the first result with autoplay",
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
            "description": "Open YouTube search results page for browsing (does not autoplay)",
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
            "description": "Fetch top YouTube search results with titles and URLs — use this when the user wants to pick a specific video from search results, so you can present the options via ask_user",
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
            "name": "open_app",
            "description": "Launch an application on the PC",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Application name (e.g. notepad, spotify, chrome)",
                    }
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "navigate",
            "description": "Open a file or folder in Windows Explorer",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File or folder path",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List contents of a directory",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path (default: current directory)",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email via configured SMTP",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {
                        "type": "string",
                        "description": "Email subject line",
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body text",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new file with optional content",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {
                        "type": "string",
                        "description": "Optional file content",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_folder",
            "description": "Create a new folder",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Folder path"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete",
            "description": "Delete a file or folder",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to delete"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy",
            "description": "Copy a file or folder to a destination",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Source path to copy from",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Destination path",
                    },
                },
                "required": ["source", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move",
            "description": "Move a file or folder to a destination",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Source path to move from",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Destination path",
                    },
                },
                "required": ["source", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_bluetooth",
            "description": "Control Bluetooth on the PC: turn on/off, scan, or connect to a device",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["on", "off", "status", "scan", "connect", "disconnect"],
                        "description": "Bluetooth action to perform",
                    },
                    "device": {
                        "type": "string",
                        "description": "Device name (required for connect/disconnect)",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_info",
            "description": "Get information about the PC: OS, Bluetooth hardware, audio devices, etc.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_media",
            "description": "Play a song or media file from local files on the PC",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Song name or filename to search and play locally",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "volume_up",
            "description": "Increase the PC volume",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "volume_down",
            "description": "Decrease the PC volume",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "volume_mute",
            "description": "Toggle mute on the PC",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_volume",
            "description": "Set PC volume to a specific level",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "number",
                        "description": "Volume level 0-100",
                    }
                },
                "required": ["level"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a question when you need more information or clarification",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to ask the user",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of options for the user to choose from",
                    },
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "media_control",
            "description": "Control media playback and browser via keyboard shortcuts. Use play_pause to start/resume a paused video (e.g. YouTube). Use fullscreen for fullscreen mode. IMPORTANT: After opening a YouTube video with yt_play, ALWAYS call this with action='play_pause' to ensure it starts playing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "play_pause",
                            "next_track",
                            "prev_track",
                            "volume_up",
                            "volume_down",
                            "mute",
                            "fullscreen",
                            "refresh",
                            "forward",
                            "backward",
                            "escape",
                            "enter",
                            "tab",
                        ],
                        "description": "Keyboard action to perform. play_pause = Space key (starts/pauses video).",
                    }
                },
                "required": ["action"],
            },
        },
    },
]


OPENGODE_BASE_URL = "https://opencode.ai/zen/go/v1"
OPENGODE_MODEL = "deepseek-v4-flash"
GEMINI_MODEL = "gemini-2.0-flash"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "google/gemini-2.0-flash-lite-preview-02-05:free"


MAX_SESSIONS = 50
MAX_SESSION_MESSAGES = 100


class IntentParser:
    def __init__(self, config):
        self.config = config
        self.default_client = None
        self.default_provider = None
        self.sessions: dict[str, list[dict]] = {}
        self._init_default()

    def _init_default(self):
        for provider, key_name in [
            ("openai", "openai_api_key"),
            ("opencode", "opencode_api_key"),
            ("gemini", "gemini_api_key"),
            ("openrouter", "openrouter_api_key"),
        ]:
            api_key = self.config.get_secret(key_name)
            if api_key:
                self.default_provider = provider
                self._build_client(provider, api_key)
                return

    def _build_client(self, provider: str, api_key: str):
        if provider == "openai":
            self.default_client = AsyncOpenAI(api_key=api_key)
        elif provider == "opencode":
            self.default_client = AsyncOpenAI(
                api_key=api_key, base_url=OPENGODE_BASE_URL
            )
        elif provider == "gemini":
            self.default_client = genai.Client(api_key=api_key)
        elif provider == "openrouter":
            self.default_client = AsyncOpenAI(
                api_key=api_key, base_url=OPENROUTER_BASE_URL
            )

    def _make_client(self, provider: str, api_key: str):
        if provider == "openai":
            return ("openai", AsyncOpenAI(api_key=api_key))
        elif provider == "opencode":
            return ("openai", AsyncOpenAI(api_key=api_key, base_url=OPENGODE_BASE_URL))
        elif provider == "gemini":
            return ("gemini", genai.Client(api_key=api_key))
        elif provider == "openrouter":
            return ("openai", AsyncOpenAI(api_key=api_key, base_url=OPENROUTER_BASE_URL))
        return None, None

    async def parse(self, text: str, executor=None, ask_callback=None, api_key=None, provider=None, session_id=None) -> dict:
        actual_provider = provider or self.default_provider
        if not actual_provider:
            command = self._parse_with_rules(text)
            return await executor.execute(command)

        actual_client = self.default_client
        client_type = actual_provider

        if api_key and provider:
            result = self._make_client(provider, api_key)
            if result:
                client_type, actual_client = result

        if actual_client:
            try:
                if client_type == "gemini":
                    return await self._parse_with_gemini(text, executor, actual_client, ask_callback, session_id)
                else:
                    return await self._parse_with_agent(text, executor, ask_callback, actual_client, actual_provider, session_id)
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Agent error: {str(e)}",
                }

        command = self._parse_with_rules(text)
        return await executor.execute(command)

    async def _parse_with_gemini(self, text: str, executor, client, ask_callback=None, session_id=None) -> dict:
        if genai is None:
            return {"success": False, "message": "Gemini not available. Install google-genai."}

        gemini_tools = []
        for t in TOOLS:
            fn = t["function"]
            props = fn["parameters"].get("properties", {})
            required = fn["parameters"].get("required", [])
            schema_props = {}
            for pname, pdef in props.items():
                sp = {"type": pdef.get("type", "string")}
                if "description" in pdef:
                    sp["description"] = pdef["description"]
                if "enum" in pdef:
                    sp["enum"] = pdef["enum"]
                schema_props[pname] = sp
            gemini_tools.append(genai.types.Tool(
                function_declarations=[genai.types.FunctionDeclaration(
                    name=fn["name"],
                    description=fn["description"],
                    parameters=genai.types.Schema(
                        type="OBJECT",
                        properties=schema_props,
                        required=required,
                    ),
                )]
            ))

        if session_id and session_id in self.sessions:
            history = self.sessions[session_id]
            contents = [{"role": "user", "parts": [{"text": SYSTEM_PROMPT}]}]
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow all rules including English-only responses, full PC control, and single-tab browser execution."}]})
            for msg in history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "system":
                    continue
                elif role in ("assistant", "tool"):
                    contents.append({"role": "model", "parts": [{"text": content}]})
                elif role == "user":
                    contents.append({"role": "user", "parts": [{"text": content}]})
            contents.append({"role": "user", "parts": [{"text": text}]})
            full_contents = contents
        else:
            full_contents = [
                {"role": "user", "parts": [{"text": f"{SYSTEM_PROMPT}\n\nUser said: {text}"}]},
            ]

        for iteration in range(5):
            try:
                response = await client.aio.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=full_contents,
                    config=genai.types.GenerateContentConfig(
                        tools=gemini_tools,
                        temperature=0.1,
                    ),
                )
            except Exception as e:
                return {"success": False, "message": f"Gemini error: {str(e)}"}

            if not response.candidates:
                return {"success": False, "message": "Gemini returned no response"}

            candidate = response.candidates[0]
            if candidate.content is None:
                return {"success": False, "message": "Gemini returned empty content"}

            parts = candidate.content.parts
            if not parts:
                return {"success": False, "message": "Gemini returned no parts"}

            has_function_call = False
            text_response = ""

            for part in parts:
                if hasattr(part, "function_call") and part.function_call:
                    has_function_call = True
                    fc = part.function_call
                    name = fc.name
                    args = dict(fc.args) if fc.args else {}

                    if name == "ask_user" and ask_callback:
                        result = await ask_callback(
                            args.get("question", ""),
                            args.get("options", []),
                        )
                    elif executor:
                        result = await executor.execute_tool(name, args)
                    else:
                        result = {"success": False, "message": "No executor available"}

                    full_contents.append({"role": "model", "parts": [{"function_call": fc}]})
                    full_contents.append({"role": "user", "parts": [{"function_response": genai.types.FunctionResponse(
                        name=name,
                        response=result,
                    )}]})

                    if session_id:
                        if session_id not in self.sessions:
                            self.sessions[session_id] = []
                        self.sessions[session_id].append({"role": "user", "content": text})
                        self.sessions[session_id].append({"role": "assistant", "content": f"Called {name}({args}) → {result.get('message', '')}"})
                        self._store_session(session_id, self.sessions[session_id])
                else:
                    text_response += part.text or ""

            if not has_function_call:
                if session_id:
                    if session_id not in self.sessions:
                        self.sessions[session_id] = []
                    self.sessions[session_id].append({"role": "user", "content": text})
                    self.sessions[session_id].append({"role": "assistant", "content": text_response or "Done."})
                    self._store_session(session_id, self.sessions[session_id])
                return {"success": True, "message": text_response or "Done."}

        return {"success": False, "message": "Gemini reached maximum iterations."}

    async def _parse_with_agent(
        self, text: str, executor, ask_callback, client, provider="openai", session_id=None
    ) -> dict:
        model = "gpt-3.5-turbo"
        if provider == "opencode":
            model = OPENGODE_MODEL
        elif provider == "openrouter":
            model = OPENROUTER_MODEL

        if session_id and session_id in self.sessions:
            messages = list(self.sessions[session_id])
            messages.append({"role": "user", "content": text})
        else:
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ]

        for _ in range(10):
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1024,
            )

            msg = response.choices[0].message

            if msg.tool_calls:
                messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]})

                for tool_call in msg.tool_calls:
                    name = tool_call.function.name
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    if name == "ask_user" and ask_callback:
                        result = await ask_callback(
                            args.get("question", ""),
                            args.get("options", []),
                        )
                    elif executor:
                        result = await executor.execute_tool(name, args)
                    else:
                        result = {"success": False, "message": "No executor available"}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    })
            else:
                if session_id:
                    self._store_session(session_id, messages)
                    self.sessions[session_id].append({
                        "role": "assistant", "content": msg.content or "Done.",
                    })
                return {
                    "success": True,
                    "message": msg.content or "Done.",
                }

        if session_id:
            self._store_session(session_id, messages)
        return {"success": False, "message": "Agent reached maximum iterations."}

    def _store_session(self, session_id: str, messages: list[dict]):
        self.sessions[session_id] = list(messages[-MAX_SESSION_MESSAGES:])
        if len(self.sessions) > MAX_SESSIONS:
            oldest = list(self.sessions.keys())[0]
            del self.sessions[oldest]

    def _parse_with_rules(self, text: str) -> dict:
        text_lower = text.lower().strip()

        for prefix in ["open ", "launch ", "start ", "run "]:
            if text_lower.startswith(prefix):
                rest = text[len(prefix) :].strip()
                if self._looks_like_url(rest):
                    return {
                        "action": "browser_navigate",
                        "params": {"url": rest},
                    }
                return {
                    "action": "open_app",
                    "params": {"name": rest},
                }

        m = re.match(r"^(?:go to|navigate to)\s+(.+)$", text_lower)
        if m:
            dest = m.group(1).strip()
            if self._looks_like_url(dest):
                return {"action": "browser_navigate", "params": {"url": dest}}
            return {"action": "navigate", "params": {"path": dest}}

        m = re.match(
            r"^(?:play|start)\s+(.+?)(?:\s+(?:on|from)\s+youtube)?$", text_lower
        )
        if m:
            return {
                "action": "yt_play",
                "params": {"query": m.group(1).strip()},
            }

        m = re.match(
            r"^(?:search\s+(?:for\s+)?)?(.+?)\s+on\s+youtube$", text_lower
        )
        if m:
            return {
                "action": "yt_play",
                "params": {"query": m.group(1).strip()},
            }

        m = re.match(
            r"^search\s+(?:for\s+)?(.+?)(?:\s+(?:on|using)\s+(google|bing|duckduckgo))?$",
            text_lower,
        )
        if m:
            return {
                "action": "browser_search",
                "params": {
                    "query": m.group(1).strip(),
                    "engine": m.group(2) or "google",
                },
            }

        for pattern in [
            r"^(?:list|show|what'?s in)\s+(.+)$",
            r"^(?:list|show|what'?s in)$",
        ]:
            m = re.match(pattern, text_lower)
            if m:
                path = m.group(1) if m.lastindex else "."
                return {"action": "list_dir", "params": {"path": path}}

        for prefix in ["open folder ", "open file "]:
            if text_lower.startswith(prefix):
                return {
                    "action": "navigate",
                    "params": {"path": text[len(prefix) :].strip()},
                }

        m = re.match(
            r"^(?:send\s+)?(?:an?\s+)?email\s+to\s+(.+?)(?:\s+with\s+subject\s+(.+?)(?:\s+and\s+(?:body\s+)?(.+))?)?$",
            text_lower,
        )
        if m:
            return {
                "action": "send_email",
                "params": {
                    "to": m.group(1),
                    "subject": m.group(2) or "No Subject",
                    "body": m.group(3) or "",
                },
            }

        m = re.match(
            r"^(?:create|make|new)\s+file\s+(.+?)(?:\s+with\s+content\s+(.+))?$",
            text_lower,
        )
        if m:
            return {
                "action": "create_file",
                "params": {"path": m.group(1), "content": m.group(2) or ""},
            }

        m = re.match(
            r"^(?:create|make|new)\s+(?:folder|directory)\s+(.+)$", text_lower
        )
        if m:
            return {"action": "create_folder", "params": {"path": m.group(1)}}

        m = re.match(r"^(?:delete|remove)\s+(.+)$", text_lower)
        if m:
            return {"action": "delete", "params": {"path": m.group(1)}}

        m = re.match(r"^(?:copy)\s+(.+?)\s+to\s+(.+)$", text_lower)
        if m:
            return {
                "action": "copy",
                "params": {"source": m.group(1), "destination": m.group(2)},
            }

        m = re.match(r"^(?:move)\s+(.+?)\s+to\s+(.+)$", text_lower)
        if m:
            return {
                "action": "move",
                "params": {"source": m.group(1), "destination": m.group(2)},
            }

        return {"action": "open_app", "params": {"name": text}}

    def _looks_like_url(self, text: str) -> bool:
        text = text.lower().strip()
        known_sites = {
            "youtube", "youtube.com", "google", "google.com",
            "github", "github.com", "gmail", "gmail.com",
            "facebook", "facebook.com", "twitter", "twitter.com",
            "x.com", "reddit", "reddit.com", "instagram",
            "instagram.com", "linkedin", "linkedin.com",
            "amazon", "amazon.com", "netflix", "netflix.com",
            "stackoverflow", "stackoverflow.com",
            "wikipedia", "wikipedia.org", "wiki",
        }
        if text.rstrip(". ") in known_sites:
            return True
        if re.search(r'\.[a-z]{2,}(?:\.[a-z]{2,})?$', text):
            return True
        return False
