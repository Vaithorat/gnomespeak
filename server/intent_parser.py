import json
import re
from openai import AsyncOpenAI

SYSTEM_PROMPT = """You are a Windows PC assistant, controlled by voice from an Android phone. Your job is to understand what the user wants and accomplish it using the available tools.

Rules:
- Use tools to accomplish tasks. You can chain multiple tool calls.
- If the user's request is ambiguous, use the `ask_user` tool to clarify.
- After completing a task, summarize what you did.
- Be concise and natural in your responses.
- For opening websites, use `browser_navigate` with the full URL.
- For playing songs/videos, use `yt_play` to search YouTube.
- For Bluetooth control, use `control_bluetooth` to turn on/off and connect devices.
- For volume control, use `set_volume`, `volume_up`, `volume_down`, or `volume_mute`.
- To play a local file, use `play_media` to search and play from Music/Downloads.
- Prefer browser actions over trying to open local apps for web services."""

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
]


class IntentParser:
    def __init__(self, config):
        self.config = config
        self.client = None
        self._init_client()

    def _init_client(self):
        api_key = self.config.get_secret("openai_api_key")
        if api_key:
            self.client = AsyncOpenAI(api_key=api_key)

    async def parse(self, text: str, executor=None, ask_callback=None) -> dict:
        if self.client:
            try:
                return await self._parse_with_agent(text, executor, ask_callback)
            except Exception as e:
                return {
                    "success": False,
                    "message": f"Agent error: {str(e)}",
                }
        command = self._parse_with_rules(text)
        return executor.execute(command)

    async def _parse_with_agent(
        self, text: str, executor, ask_callback
    ) -> dict:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]

        for _ in range(10):
            response = await self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=500,
            )

            msg = response.choices[0].message

            if msg.tool_calls:
                messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ]})

                for tool_call in msg.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)

                    if name == "ask_user" and ask_callback:
                        result = await ask_callback(
                            args.get("question", ""),
                            args.get("options", []),
                        )
                    elif executor:
                        result = executor.execute_tool(name, args)
                    else:
                        result = {"success": False, "message": "No executor available"}

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result),
                    })
            else:
                return {
                    "success": True,
                    "message": msg.content or "Done.",
                }

        return {"success": False, "message": "Agent reached maximum iterations."}

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
