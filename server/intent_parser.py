import asyncio
import json
import logging
import re
import uuid
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
- `yt_play` opens a real browser, navigates to the video, and attempts autoplay. If it reports autoplay was blocked, use `media_control` with `play_pause`.
- To browse YouTube results without playing, use `yt_search`.
- When user wants a specific video from results, use `yt_results` to fetch matches, present via `ask_user`, then open with `browser_navigate`.
- NEVER open multiple browser tabs for a single task. All navigation happens in one browser.

Bluetooth / Media:
- For Bluetooth control, use `control_bluetooth` for radio status/on/off and device scans only. Do not promise connect/disconnect support.
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
            "description": "Search YouTube for a song/video, open the first result, and report whether autoplay actually started or was blocked",
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
            "description": "Control Bluetooth on the PC: check status, turn the radio on/off when supported, or scan for devices",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["on", "off", "status", "scan"],
                        "description": "Bluetooth action to perform",
                    },
                    "device": {
                        "type": "string",
                        "description": "Reserved for future Bluetooth device targeting",
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
            "description": "Get information about the PC: OS details and current Bluetooth status message.",
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
            "description": "Control media playback and browser via keyboard shortcuts. Use play_pause to start/resume a paused video (e.g. YouTube) when playback is blocked or paused. Use fullscreen for fullscreen mode.",
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
OPENGODE_MODEL = "deepseek-v4-flash-free"
GEMINI_MODEL = "gemini-2.0-flash"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "nvidia/nemotron-nano-9b-v2:free"


MAX_SESSIONS = 50
MAX_SESSION_MESSAGES = 30
MAX_TOOL_RESULT_CHARS = 500

SENTENCE_ENDINGS = re.compile(r'[.!?]\s|\n')
MAX_CHUNK_CHARS = 500


class IntentParser:
    def __init__(self, config, env_model=None):
        self.config = config
        self.default_client = None
        self.default_provider = None
        self.sessions: dict[str, list[dict]] = {}
        self._sessions_lock = asyncio.Lock()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._session_counter = 0
        self.env_model = env_model
        self._init_default()

    def new_session_id(self) -> str:
        self._session_counter += 1
        return f"s_{uuid.uuid4().hex[:8]}_{self._session_counter}"

    async def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        async with self._sessions_lock:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[session_id] = lock
            return lock

    async def _load_session_messages(self, session_id: str | None, system_prompt: str, text: str) -> list[dict]:
        if not session_id:
            return [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ]
        lock = await self._get_session_lock(session_id)
        async with lock:
            history = list(self.sessions.get(session_id, []))
        if history:
            history.append({"role": "user", "content": text})
            return history
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]

    async def _load_gemini_contents(self, session_id: str | None, system_prompt: str, text: str) -> list[dict]:
        if not session_id:
            return [
                {"role": "user", "parts": [{"text": f"{system_prompt}\n\nUser said: {text}"}]},
            ]
        lock = await self._get_session_lock(session_id)
        async with lock:
            history = list(self.sessions.get(session_id, []))
        if not history:
            return [
                {"role": "user", "parts": [{"text": f"{system_prompt}\n\nUser said: {text}"}]},
            ]
        contents = [{"role": "user", "parts": [{"text": system_prompt}]}]
        contents.append({"role": "model", "parts": [{"text": "Understood. I will follow all rules including English-only responses, full PC control, and single-tab browser execution."}]})
        for msg in history:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                continue
            if role in ("assistant", "tool"):
                contents.append({"role": "model", "parts": [{"text": content}]})
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": content}]})
        contents.append({"role": "user", "parts": [{"text": text}]})
        return contents

    async def _append_session_entries(self, session_id: str | None, *entries: dict):
        if not session_id:
            return
        lock = await self._get_session_lock(session_id)
        async with lock:
            history = list(self.sessions.get(session_id, []))
            history.extend(entries)
            await self._store_session_locked(session_id, history)

    async def _store_session(self, session_id: str | None, messages: list[dict]):
        if not session_id:
            return
        lock = await self._get_session_lock(session_id)
        async with lock:
            await self._store_session_locked(session_id, messages)

    async def _store_session_locked(self, session_id: str, messages: list[dict]):
        async with self._sessions_lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
            self.sessions[session_id] = list(messages[-MAX_SESSION_MESSAGES:])
            if len(self.sessions) > MAX_SESSIONS:
                oldest = next(iter(self.sessions))
                if oldest == session_id and len(self.sessions) > 1:
                    oldest = next(key for key in self.sessions if key != session_id)
                del self.sessions[oldest]
                self._session_locks.pop(oldest, None)

    def _init_default(self):
        configured = self.config.data.get("default_provider")
        if configured:
            key_name = f"{configured}_api_key"
            api_key = self.config.get_secret(key_name)
            if api_key:
                self.default_provider = configured
                self._build_client(configured, api_key)
                return
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

    @staticmethod
    def _provider_error_message(error: Exception) -> str:
        text = str(error)
        if "ResourceExhausted" in text or "request limit reached" in text:
            return "AI provider is rate-limited right now. Retry in a moment or switch providers."
        return "AI provider error"

    @staticmethod
    def _parse_volume_level(value: str) -> int | None:
        value = value.strip().lower()
        named_levels = {
            "full": 100,
            "max": 100,
            "maximum": 100,
            "highest": 100,
            "half": 50,
            "medium": 50,
            "zero": 0,
            "min": 0,
            "minimum": 0,
            "lowest": 0,
        }
        if value in named_levels:
            return named_levels[value]
        m = re.fullmatch(r"(100|[1-9]?\d)\s*%?", value)
        if m:
            return int(m.group(1))
        return None

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

    def _get_system_prompt_with_env(self) -> str:
        prompt = SYSTEM_PROMPT
        if self.env_model:
            env_ctx = self.env_model.build_context_prompt()
            if env_ctx and env_ctx != "## Current Environment":
                prompt += "\n\n" + env_ctx
        return prompt

    def _match_deterministic_command(self, text: str) -> dict | None:
        text_lower = text.lower().strip()
        matchers = [
            self._match_volume_command,
            self._match_bluetooth_command,
            self._match_open_path_command,
            self._match_browser_command,
            self._match_navigation_command,
            self._match_youtube_command,
            self._match_search_command,
            self._match_list_command,
            self._match_email_command,
            self._match_create_file_command,
            self._match_create_folder_command,
            self._match_delete_command,
            self._match_copy_command,
            self._match_move_command,
            self._match_app_command,
        ]
        for matcher in matchers:
            command = matcher(text, text_lower)
            if command:
                return command
        return None

    def _normalize_command_text(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text.strip())
        normalized = re.sub(
            r"^(?:now\s+)?(?:i\s+want\s+you\s+to|want\s+you\s+to|what\s+you\s+to|can\s+you|could\s+you|would\s+you|please)\s+",
            "",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(r"\bopen\s+of\s+(youtube|google|bing|duckduckgo)\b", r"open \1", normalized, flags=re.IGNORECASE)
        return normalized.strip(" ,.")

    def _split_command_sequence(self, text: str) -> list[str]:
        normalized = self._normalize_command_text(text)
        parts = [part.strip(" ,.") for part in re.split(r"\s*(?:,\s*)?(?:and then|then)\s+", normalized, flags=re.IGNORECASE) if part.strip(" ,.")]
        return parts or [normalized]

    def _resolve_deterministic_sequence(self, text: str, alternatives: list[str] | None = None) -> list[dict] | None:
        candidates = [self._normalize_command_text(text)]
        if alternatives:
            seen = {candidates[0].lower()}
            for alternative in alternatives:
                normalized = self._normalize_command_text(alternative)
                if not normalized:
                    continue
                key = normalized.lower()
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(normalized)

        for candidate in candidates:
            parts = self._split_command_sequence(candidate)
            if len(parts) <= 1:
                continue
            commands = []
            for part in parts:
                command = self._match_deterministic_command(part)
                if not command:
                    commands = []
                    break
                commands.append(command)
            if commands:
                return commands
        return None

    def _resolve_deterministic_command(self, text: str, alternatives: list[str] | None = None) -> dict | None:
        normalized = self._normalize_command_text(text)
        command = self._match_deterministic_command(normalized)
        if command:
            return command

        if not alternatives:
            return None

        seen = {normalized.lower()}
        for alternative in alternatives:
            normalized_alternative = self._normalize_command_text(alternative)
            if not normalized_alternative:
                continue
            key = normalized_alternative.lower()
            if key in seen:
                continue
            seen.add(key)
            command = self._match_deterministic_command(normalized_alternative)
            if command:
                return command
        return None

    async def _execute_deterministic_sequence(self, executor, commands: list[dict]) -> dict:
        results = []
        for index, command in enumerate(commands, start=1):
            result = await executor.execute(command)
            if not result.get("success"):
                message = result.get("message", "Command failed")
                if len(commands) > 1:
                    message = f"Step {index} failed: {message}"
                return {"success": False, "message": message}
            results.append(result)

        if not results:
            return {"success": False, "message": "No deterministic commands were executed."}
        if len(results) == 1:
            return results[0]

        messages = [result.get("message", "Done.") for result in results if result.get("message")]
        return {"success": True, "message": " Then ".join(messages) or "Done."}

    async def parse(self, text: str, executor=None, ask_callback=None, api_key=None, provider=None, session_id=None, alternatives=None) -> dict:
        deterministic_sequence = self._resolve_deterministic_sequence(text, alternatives)
        if deterministic_sequence:
            return await self._execute_deterministic_sequence(executor, deterministic_sequence)

        deterministic_command = self._resolve_deterministic_command(text, alternatives)
        if deterministic_command:
            return await executor.execute(deterministic_command)

        command = self._parse_with_rules(text)

        actual_provider = provider or self.default_provider
        if not actual_provider:
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
                logging.exception("Agent error in parse")
                return {
                    "success": False,
                    "message": self._provider_error_message(e),
                }

        return await executor.execute(command)

    async def parse_stream(self, text: str, executor=None, ask_callback=None, api_key=None, provider=None, session_id=None, alternatives=None):
        deterministic_sequence = self._resolve_deterministic_sequence(text, alternatives)
        if deterministic_sequence:
            result = await self._execute_deterministic_sequence(executor, deterministic_sequence)
            yield {"type": "final", "result": result}
            return

        deterministic_command = self._resolve_deterministic_command(text, alternatives)
        if deterministic_command:
            result = await executor.execute(deterministic_command)
            yield {"type": "final", "result": result}
            return

        command = self._parse_with_rules(text)

        actual_provider = provider or self.default_provider
        if not actual_provider:
            result = await executor.execute(command)
            yield {"type": "final", "result": result}
            return

        actual_client = self.default_client
        client_type = actual_provider

        if api_key and provider:
            result = self._make_client(provider, api_key)
            if result:
                client_type, actual_client = result

        if actual_client:
            try:
                if client_type == "gemini":
                    async for chunk in self._parse_with_gemini_stream(text, executor, actual_client, ask_callback, session_id):
                        yield chunk
                else:
                    async for chunk in self._parse_with_agent_stream(text, executor, ask_callback, actual_client, actual_provider, session_id):
                        yield chunk
                return
            except Exception as e:
                logging.exception("Agent error in parse_stream")
                yield {"type": "final", "result": {"success": False, "message": self._provider_error_message(e)}}
                return

        result = await executor.execute(command)
        yield {"type": "final", "result": result}

    async def _parse_with_agent_stream(
        self, text: str, executor, ask_callback, client, provider="openai", session_id=None
    ):
        model = self.config.data.get("default_model", "gpt-4o-mini")
        if provider == "opencode":
            model = OPENGODE_MODEL
        elif provider == "openrouter":
            model = OPENROUTER_MODEL

        system_prompt = self._get_system_prompt_with_env()
        full_response = ""

        messages = await self._load_session_messages(session_id, system_prompt, text)

        full_response = ""
        for _ in range(10):
            try:
                response = await asyncio.wait_for(client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=1024,
                    stream=True,
                    stream_options={"include_usage": True},
                ), timeout=30)
            except asyncio.TimeoutError:
                yield {"type": "final", "result": {"success": False, "message": "AI provider timed out"}}
                return

            text_buffer = ""
            tool_calls_data = []
            finish_reason = None
            usage = None

            async for chunk in response:
                if hasattr(chunk, "usage") and chunk.usage:
                    usage = chunk.usage

                if not chunk.choices:
                    continue

                choice = chunk.choices[0]
                delta = choice.delta
                finish_reason = choice.finish_reason

                if delta and delta.content:
                    text_buffer += delta.content
                    full_response += delta.content
                    while True:
                        split_pos = -1
                        for ending_match in SENTENCE_ENDINGS.finditer(text_buffer):
                            pos = ending_match.end()
                            if pos <= MAX_CHUNK_CHARS:
                                split_pos = pos
                                break
                        if split_pos > 0:
                            yield {"type": "chunk", "content": text_buffer[:split_pos]}
                            text_buffer = text_buffer[split_pos:]
                        elif len(text_buffer) >= MAX_CHUNK_CHARS:
                            space_pos = text_buffer.rfind(" ", 0, MAX_CHUNK_CHARS)
                            if space_pos > 0:
                                yield {"type": "chunk", "content": text_buffer[:space_pos + 1]}
                                text_buffer = text_buffer[space_pos + 1:]
                            else:
                                yield {"type": "chunk", "content": text_buffer[:MAX_CHUNK_CHARS]}
                                text_buffer = text_buffer[MAX_CHUNK_CHARS:]
                        else:
                            break

                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        while len(tool_calls_data) <= idx:
                            tool_calls_data.append({"id": "", "name": "", "arguments": ""})
                        if tc_delta.id:
                            tool_calls_data[idx]["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                tool_calls_data[idx]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                tool_calls_data[idx]["arguments"] += tc_delta.function.arguments

            if text_buffer:
                yield {"type": "chunk", "content": text_buffer}

            if finish_reason == "stop":
                if session_id:
                    await self._store_session(session_id, messages)
                yield {"type": "final", "result": {"success": True, "message": full_response or "Done."}}
                return

            if finish_reason in ("length", "content_filter") and not tool_calls_data:
                if session_id:
                    await self._store_session(session_id, messages)
                reason = "response truncated (length limit)" if finish_reason == "length" else "content filtered"
                yield {"type": "final", "result": {"success": bool(full_response), "message": full_response or f"AI provider {reason}"}}
                return

            if tool_calls_data:
                messages.append({"role": "assistant", "content": None, "tool_calls": [
                    {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in tool_calls_data if tc["name"]
                ]})

                for tc in tool_calls_data:
                    if not tc["name"]:
                        continue
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}

                    if tc["name"] == "ask_user" and ask_callback:
                        result = await ask_callback(
                            args.get("question", ""),
                            args.get("options", []),
                        )
                    elif executor:
                        result = await executor.execute_tool(tc["name"], args, ask_callback)
                    else:
                        result = {"success": False, "message": "No executor available"}

                    yield {"type": "tool_result", "tool": tc["name"], "result": result}

                    result_json = json.dumps(result)
                    if len(result_json) > MAX_TOOL_RESULT_CHARS:
                        result_json = result_json[:MAX_TOOL_RESULT_CHARS] + "...(truncated)"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_json,
                    })

                tool_calls_data = []
                continue

            break

        if session_id:
            await self._store_session(session_id, messages)
        yield {"type": "final", "result": {"success": False, "message": "Agent reached maximum iterations."}}

    async def _parse_with_gemini_stream(self, text: str, executor, client, ask_callback=None, session_id=None):
        if genai is None:
            yield {"type": "final", "result": {"success": False, "message": "Gemini not available. Install google-genai."}}
            return

        system_prompt = self._get_system_prompt_with_env()

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

        full_contents = await self._load_gemini_contents(session_id, system_prompt, text)

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
                logging.exception("Gemini error in parse_stream")
                yield {"type": "final", "result": {"success": False, "message": "AI provider error"}}
                return

            if not response.candidates:
                yield {"type": "final", "result": {"success": False, "message": "Gemini returned no response"}}
                return

            candidate = response.candidates[0]
            if candidate.content is None:
                yield {"type": "final", "result": {"success": False, "message": "Gemini returned empty content"}}
                return

            parts = candidate.content.parts
            if not parts:
                yield {"type": "final", "result": {"success": False, "message": "Gemini returned no parts"}}
                return

            has_function_call = False
            text_buffer = ""

            for part in parts:
                if hasattr(part, "function_call") and part.function_call:
                    has_function_call = True
                    fc = part.function_call
                    name = fc.name
                    args = dict(fc.args) if fc.args else {}

                    if text_buffer:
                        yield {"type": "chunk", "content": text_buffer}
                        text_buffer = ""

                    if name == "ask_user" and ask_callback:
                        result = await ask_callback(
                            args.get("question", ""),
                            args.get("options", []),
                        )
                    elif executor:
                        result = await executor.execute_tool(name, args, ask_callback)
                    else:
                        result = {"success": False, "message": "No executor available"}

                    yield {"type": "tool_result", "tool": name, "result": result}

                    full_contents.append({"role": "model", "parts": [{"function_call": fc}]})
                    full_contents.append({"role": "user", "parts": [{"function_response": genai.types.FunctionResponse(
                        name=name,
                        response=result,
                    )}]})
                else:
                    text_buffer += part.text or ""

            if session_id and has_function_call:
                await self._append_session_entries(
                    session_id,
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": f"Called tool → {text_buffer[:200]}"},
                )

            if text_buffer:
                words = text_buffer.split(" ")
                chunk = ""
                for word in words:
                    test = chunk + word + " "
                    if len(test) >= MAX_CHUNK_CHARS:
                        if chunk:
                            yield {"type": "chunk", "content": chunk}
                        chunk = word + " "
                    else:
                        chunk = test
                if chunk:
                    yield {"type": "chunk", "content": chunk}

            if not has_function_call:
                if session_id:
                    await self._append_session_entries(
                        session_id,
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": text_buffer or "Done."},
                    )
                yield {"type": "final", "result": {"success": True, "message": text_buffer or "Done."}}
                return

        yield {"type": "final", "result": {"success": False, "message": "Gemini reached maximum iterations."}}

    async def _parse_with_gemini(self, text: str, executor, client, ask_callback=None, session_id=None) -> dict:
        if genai is None:
            return {"success": False, "message": "Gemini not available. Install google-genai."}

        system_prompt = self._get_system_prompt_with_env()

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

        full_contents = await self._load_gemini_contents(session_id, system_prompt, text)

        for iteration in range(5):
            try:
                response = await asyncio.wait_for(client.aio.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=full_contents,
                    config=genai.types.GenerateContentConfig(
                        tools=gemini_tools,
                        temperature=0.1,
                    ),
                ), timeout=30)
            except asyncio.TimeoutError:
                return {"success": False, "message": "AI provider timed out"}
            except Exception as e:
                logging.exception("Gemini error in parse")
                return {"success": False, "message": "AI provider error"}

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
                        result = await executor.execute_tool(name, args, ask_callback)
                    else:
                        result = {"success": False, "message": "No executor available"}

                    full_contents.append({"role": "model", "parts": [{"function_call": fc}]})
                    full_contents.append({"role": "user", "parts": [{"function_response": genai.types.FunctionResponse(
                        name=name,
                        response=result,
                    )}]})

                    if session_id:
                        await self._append_session_entries(
                            session_id,
                            {"role": "user", "content": text},
                            {"role": "assistant", "content": f"Called {name}({args}) → {result.get('message', '')}"},
                        )
                else:
                    text_response += part.text or ""

            if not has_function_call:
                if session_id:
                    await self._append_session_entries(
                        session_id,
                        {"role": "user", "content": text},
                        {"role": "assistant", "content": text_response or "Done."},
                    )
                return {"success": True, "message": text_response or "Done."}

        return {"success": False, "message": "Gemini reached maximum iterations."}

    async def _parse_with_agent(
        self, text: str, executor, ask_callback, client, provider="openai", session_id=None
    ) -> dict:
        model = self.config.data.get("default_model", "gpt-4o-mini")
        if provider == "opencode":
            model = OPENGODE_MODEL
        elif provider == "openrouter":
            model = OPENROUTER_MODEL

        system_prompt = self._get_system_prompt_with_env()

        messages = await self._load_session_messages(session_id, system_prompt, text)

        for _ in range(10):
            try:
                response = await asyncio.wait_for(client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.1,
                    max_tokens=1024,
                ), timeout=30)
            except asyncio.TimeoutError:
                return {"success": False, "message": "AI provider timed out"}

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
                        result = await executor.execute_tool(name, args, ask_callback)
                    else:
                        result = {"success": False, "message": "No executor available"}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result)[:MAX_TOOL_RESULT_CHARS],
                    })
            else:
                if session_id:
                    messages.append({
                        "role": "assistant", "content": msg.content or "Done.",
                    })
                    await self._store_session(session_id, messages)
                return {
                    "success": True,
                    "message": msg.content or "Done.",
                }

        if session_id:
            await self._store_session(session_id, messages)
        return {"success": False, "message": "Agent reached maximum iterations."}

    def _match_volume_command(self, text: str, text_lower: str) -> dict | None:
        for pattern in [
            r"^(?:set|turn|change|lower|raise|increase|decrease)\s+(?:the\s+)?volume\s+to\s+(.+)$",
            r"^(?:volume)\s+to\s+(.+)$",
            r"^(?:set)\s+volume\s+(.+)$",
        ]:
            m = re.match(pattern, text_lower)
            if m:
                level = self._parse_volume_level(m.group(1))
                if level is not None:
                    return {"action": "set_volume", "params": {"level": level}}

        if re.match(r"^(?:mute|mute volume|mute the volume|turn volume off|turn the volume off)$", text_lower):
            return {"action": "volume_mute", "params": {}}

        if re.match(r"^(?:volume up|turn (?:the )?volume up|increase (?:the )?volume|make it louder|raise (?:the )?volume)$", text_lower):
            return {"action": "volume_up", "params": {}}

        if re.match(r"^(?:volume down|turn (?:the )?volume down|decrease (?:the )?volume|make it quieter|lower (?:the )?volume)$", text_lower):
            return {"action": "volume_down", "params": {}}
        return None

    def _match_bluetooth_command(self, text: str, text_lower: str) -> dict | None:
        for pattern, action in [
            (r"^(?:turn|switch|enable)\s+bluetooth\s+on$", "on"),
            (r"^(?:turn|switch|disable)\s+bluetooth\s+off$", "off"),
            (r"^(?:bluetooth\s+status|check\s+bluetooth|is\s+bluetooth\s+on)$", "status"),
            (r"^(?:scan\s+bluetooth|scan\s+for\s+bluetooth\s+devices)$", "scan"),
        ]:
            if re.match(pattern, text_lower):
                return {"action": "control_bluetooth", "params": {"action": action}}
        return None

    def _match_open_path_command(self, text: str, text_lower: str) -> dict | None:
        for prefix in ["open folder ", "open file "]:
            if text_lower.startswith(prefix):
                return {
                    "action": "navigate",
                    "params": {"path": text[len(prefix):].strip()},
                }
        return None

    def _match_browser_command(self, text: str, text_lower: str) -> dict | None:
        candidates = [text_lower]
        stripped = re.sub(r"^open\s+(?:the\s+)?browser\s+", "", text_lower, count=1)
        if stripped != text_lower:
            candidates.append(stripped)

        for candidate in candidates:
            if re.match(
                r"^play\s+(?:the\s+)?first\s+(?:video|result|one)(?:\b.*)?$",
                candidate,
            ):
                return {"action": "yt_play_first_result", "params": {}}

            if re.match(
                r"^go\s+to\s+youtube\s+and\s+play\s+(?:the\s+)?first\s+(?:video|result|one)(?:\b.*)?$",
                candidate,
            ):
                return {"action": "yt_play_first_result", "params": {}}

            m = re.match(
                r"^go\s+to\s+youtube\s+and\s+search\s+(?:for\s+)?(.+)$",
                candidate,
            )
            if m:
                return {"action": "yt_search", "params": {"query": m.group(1).strip()}}

            m = re.match(
                r"^open(?:\s+of)?\s+youtube\s+and\s+search\s+(?:for\s+)?(.+?)\s+and\s+play\s+(?:the\s+)?first\s+video(?:\s+that\s+comes(?:\s+up)?)?$",
                candidate,
            )
            if m:
                return {"action": "yt_play", "params": {"query": m.group(1).strip()}}

            m = re.match(
                r"^open(?:\s+of)?\s+youtube\s+and\s+search\s+(?:for\s+)?(.+)$",
                candidate,
            )
            if m:
                return {"action": "yt_search", "params": {"query": m.group(1).strip()}}

            m = re.match(
                r"^open(?:\s+of)?\s+youtube\s+and\s+play\s+(.+)$",
                candidate,
            )
            if m:
                return {"action": "yt_play", "params": {"query": m.group(1).strip()}}

            m = re.match(
                r"^open\s+(google|bing|duckduckgo)\s+and\s+search\s+(?:for\s+)?(.+)$",
                candidate,
            )
            if m:
                return {
                    "action": "browser_search",
                    "params": {"engine": m.group(1), "query": m.group(2).strip()},
                }

            m = re.match(
                r"^open\s+(?:the\s+)?browser\s+and\s+play\s+(.+?)(?:\s+(?:on|from)\s+youtube)?$",
                candidate,
            )
            if m:
                return {"action": "yt_play", "params": {"query": m.group(1).strip()}}

            m = re.match(
                r"^open\s+(?:the\s+)?browser\s+and\s+search\s+(?:for\s+)?(.+?)(?:\s+(?:on|using)\s+(google|bing|duckduckgo))?$",
                candidate,
            )
            if m:
                return {
                    "action": "browser_search",
                    "params": {"query": m.group(1).strip(), "engine": m.group(2) or "google"},
                }

            m = re.match(r"^open\s+(?:the\s+)?browser\s+and\s+go\s+to\s+(.+)$", candidate)
            if m:
                dest = m.group(1).strip()
                if self._looks_like_url(dest):
                    return {"action": "browser_navigate", "params": {"url": dest}}
        return None

    def _match_navigation_command(self, text: str, text_lower: str) -> dict | None:
        m = re.match(r"^(?:go to|navigate to)\s+(.+)$", text_lower)
        if not m:
            return None
        dest = m.group(1).strip()
        if self._looks_like_url(dest):
            return {"action": "browser_navigate", "params": {"url": dest}}
        return {"action": "navigate", "params": {"path": dest}}

    def _match_youtube_command(self, text: str, text_lower: str) -> dict | None:
        m = re.match(r"^play\s+(.+?)(?:\s+(?:on|from)\s+youtube)?$", text_lower)
        if m:
            return {"action": "yt_play", "params": {"query": m.group(1).strip()}}

        m = re.match(r"^start\s+(.+?)\s+(?:on|from)\s+youtube$", text_lower)
        if m:
            return {"action": "yt_play", "params": {"query": m.group(1).strip()}}

        m = re.match(r"^(?:search\s+(?:for\s+)?)?(.+?)\s+on\s+youtube$", text_lower)
        if m:
            return {"action": "yt_play", "params": {"query": m.group(1).strip()}}
        return None

    def _match_search_command(self, text: str, text_lower: str) -> dict | None:
        m = re.match(
            r"^search\s+(?:for\s+)?(.+?)(?:\s+(?:on|using)\s+(google|bing|duckduckgo))?$",
            text_lower,
        )
        if not m:
            return None
        return {
            "action": "browser_search",
            "params": {"query": m.group(1).strip(), "engine": m.group(2) or "google"},
        }

    def _match_list_command(self, text: str, text_lower: str) -> dict | None:
        for pattern in [
            r"^(?:list|show|what'?s in)\s+(.+)$",
            r"^(?:list|show|what'?s in)$",
        ]:
            m = re.match(pattern, text_lower)
            if m:
                path = m.group(1) if m.lastindex else "."
                return {"action": "list_dir", "params": {"path": path}}
        return None

    def _match_email_command(self, text: str, text_lower: str) -> dict | None:
        m = re.match(
            r"^(?:send\s+)?(?:an?\s+)?email\s+to\s+(.+?)(?:\s+with\s+subject\s+(.+?)(?:\s+and\s+(?:body\s+)?(.+))?)?$",
            text_lower,
        )
        if not m:
            return None
        return {
            "action": "send_email",
            "params": {"to": m.group(1), "subject": m.group(2) or "No Subject", "body": m.group(3) or ""},
        }

    def _match_create_file_command(self, text: str, text_lower: str) -> dict | None:
        m = re.match(r"^(?:create|make|new)\s+file\s+(.+?)(?:\s+with\s+content\s+(.+))?$", text_lower)
        if not m:
            return None
        return {
            "action": "create_file",
            "params": {"path": m.group(1), "content": m.group(2) or ""},
        }

    def _match_create_folder_command(self, text: str, text_lower: str) -> dict | None:
        m = re.match(r"^(?:create|make|new)\s+(?:folder|directory)\s+(.+)$", text_lower)
        if not m:
            return None
        return {"action": "create_folder", "params": {"path": m.group(1)}}

    def _match_delete_command(self, text: str, text_lower: str) -> dict | None:
        m = re.match(r"^(?:delete|remove)\s+(.+)$", text_lower)
        if not m:
            return None
        return {"action": "delete", "params": {"path": m.group(1)}}

    def _match_copy_command(self, text: str, text_lower: str) -> dict | None:
        m = re.match(r"^(?:copy)\s+(.+?)\s+to\s+(.+)$", text_lower)
        if not m:
            return None
        return {"action": "copy", "params": {"source": m.group(1), "destination": m.group(2)}}

    def _match_move_command(self, text: str, text_lower: str) -> dict | None:
        m = re.match(r"^(?:move)\s+(.+?)\s+to\s+(.+)$", text_lower)
        if not m:
            return None
        return {"action": "move", "params": {"source": m.group(1), "destination": m.group(2)}}

    def _match_app_command(self, text: str, text_lower: str) -> dict | None:
        for prefix in ["open ", "launch ", "start ", "run "]:
            if text_lower.startswith(prefix):
                rest = text[len(prefix):].strip()
                if self._looks_like_url(rest):
                    return {"action": "browser_navigate", "params": {"url": rest}}
                return {"action": "open_app", "params": {"name": rest}}
        return None

    def _parse_with_rules(self, text: str) -> dict:
        command = self._match_deterministic_command(text)
        if command:
            return command
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
