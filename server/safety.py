import os
from pathlib import Path
from handlers.file_ops import _safe_path


DESTRUCTIVE_TOOLS = {"delete", "move", "copy", "create_file"}
SENSITIVE_TOOLS = {"open_app", "send_email", "browser_navigate", "play_media"}
_EXECUTABLE_EXTS = {".exe", ".bat", ".cmd", ".lnk", ".url", ".mshta", ".ps1", ".vbs", ".js"}


class SafetyChecker:
    def __init__(self):
        self.enabled = True

    async def check(self, tool_name: str, args: dict, ask_callback=None) -> dict | None:
        if not self.enabled:
            return None

        if tool_name == "delete":
            path = args.get("path", "")
            if not path:
                return None
            resolved = Path(path).expanduser().resolve()
            confirmed = await self._ask(
                ask_callback,
                f"Delete '{resolved}'? This cannot be undone.",
                ["Yes, delete it", "No, cancel"],
            )
            if not confirmed:
                return {"success": False, "message": "Delete cancelled by user"}
            return None

        if tool_name == "move":
            source = args.get("source", "")
            dest = args.get("destination", "")
            src_resolved = Path(source).expanduser().resolve() if source else source
            dst_resolved = Path(dest).expanduser().resolve() if dest else dest
            if dest and Path(dest).expanduser().resolve().exists():
                confirmed = await self._ask(
                    ask_callback,
                    f"'{dst_resolved}' already exists at destination. Overwrite it by moving '{src_resolved}'?",
                    ["Yes, overwrite it", "No, cancel"],
                )
                if not confirmed:
                    return {"success": False, "message": "Move cancelled by user"}
            confirmed = await self._ask(
                ask_callback,
                f"Move '{src_resolved}' to '{dst_resolved}'? The original will be removed.",
                ["Yes, move it", "No, cancel"],
            )
            if not confirmed:
                return {"success": False, "message": "Move cancelled by user"}
            return None

        if tool_name == "copy":
            source = args.get("source", "")
            dest = args.get("destination", "")
            src_resolved = Path(source).expanduser().resolve() if source else source
            dst_resolved = Path(dest).expanduser().resolve() if dest else dest
            if Path(dest).expanduser().resolve().exists():
                confirmed = await self._ask(
                    ask_callback,
                    f"'{dst_resolved}' already exists at destination. Overwrite?",
                    ["Yes, overwrite", "No, cancel"],
                )
                if not confirmed:
                    return {"success": False, "message": "Copy cancelled by user"}
            return None

        if tool_name == "create_file":
            path = args.get("path", "")
            if not path:
                return None
            resolved = Path(path).expanduser().resolve()
            safe = _safe_path(path)
            if safe is None:
                confirmed = await self._ask(
                    ask_callback,
                    f"Create file outside allowed directories: '{resolved}'?",
                    ["Yes, create it", "No, cancel"],
                )
                if not confirmed:
                    return {"success": False, "message": "Create file cancelled by user"}
                return None
            if os.path.exists(resolved):
                confirmed = await self._ask(
                    ask_callback,
                    f"'{resolved}' already exists. Overwrite?",
                    ["Yes, overwrite", "No, cancel"],
                )
                if not confirmed:
                    return {"success": False, "message": "Create file cancelled by user"}
            return None

        if tool_name == "navigate":
            path = args.get("path", "")
            if path:
                ext = Path(path).suffix.lower()
                if ext in _EXECUTABLE_EXTS:
                    resolved = Path(path).expanduser().resolve()
                    confirmed = await self._ask(
                        ask_callback,
                        f"Run executable '{resolved}'?",
                        ["Yes, run it", "No, cancel"],
                    )
                    if not confirmed:
                        return {"success": False, "message": "Execution cancelled by user"}
            return None

        if tool_name == "open_app":
            name = args.get("name", "").strip().lower()
            resolved_path = str(args.get("_resolved_path", "")).strip().lower()
            resolved_name = Path(resolved_path).name if resolved_path else ""
            dangerous = {"cmd", "command prompt", "powershell", "pwsh", "regedit", "taskmgr"}
            dangerous_targets = {"cmd.exe", "powershell.exe", "pwsh.exe", "regedit.exe", "taskmgr.exe"}
            if name in dangerous or resolved_name in dangerous_targets:
                confirmed = await self._ask(
                    ask_callback,
                    f"Open system tool '{resolved_path or name}'?",
                    ["Yes, open it", "No, cancel"],
                )
                if not confirmed:
                    return {"success": False, "message": "Cancelled by user"}
            return None

        if tool_name == "browser_navigate":
            url = args.get("url", "").strip()
            confirmed = await self._ask(
                ask_callback,
                f"Open website '{url}'?",
                ["Yes, open it", "No, cancel"],
            )
            if not confirmed:
                return {"success": False, "message": "Navigation cancelled by user"}
            return None

        if tool_name == "play_media":
            query = args.get("query", "").strip()
            confirmed = await self._ask(
                ask_callback,
                f"Play media matching '{query}'?",
                ["Yes, play it", "No, cancel"],
            )
            if not confirmed:
                return {"success": False, "message": "Media playback cancelled by user"}
            return None

        if tool_name == "send_email":
            confirmed = await self._ask(
                ask_callback,
                f"Send email to '{args.get('to', '')}' with subject '{args.get('subject', '')}'?",
                ["Yes, send it", "No, cancel"],
            )
            if not confirmed:
                return {"success": False, "message": "Email cancelled by user"}
            return None

        return None

    async def _ask(self, ask_callback, question: str, options: list[str]) -> bool:
        if not ask_callback:
            return False
        try:
            result = await ask_callback(question, options)
            if isinstance(result, dict):
                answer = result.get("text", "")
            else:
                answer = str(result)
            return answer.lower().startswith("yes")
        except Exception:
            return False
