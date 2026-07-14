import os
from pathlib import Path


DESTRUCTIVE_TOOLS = {"delete", "move", "copy", "create_file"}


class SafetyChecker:
    def __init__(self):
        self.enabled = True

    async def check(self, tool_name: str, args: dict, ask_callback=None) -> dict | None:
        if not self.enabled or tool_name not in DESTRUCTIVE_TOOLS:
            return None

        if tool_name == "delete":
            path = args.get("path", "")
            if not path:
                return None
            display = Path(path).name or path
            confirmed = await self._ask(
                ask_callback,
                f"Delete '{display}'? This cannot be undone.",
                ["Yes, delete it", "No, cancel"],
            )
            if not confirmed:
                return {"success": False, "message": "Delete cancelled by user"}
            return None

        if tool_name == "move":
            source = args.get("source", "")
            dest = args.get("destination", "")
            src_name = Path(source).name if source else source
            confirmed = await self._ask(
                ask_callback,
                f"Move '{src_name}' to '{dest}'? The original will be removed.",
                ["Yes, move it", "No, cancel"],
            )
            if not confirmed:
                return {"success": False, "message": "Move cancelled by user"}
            return None

        if tool_name == "copy":
            source = args.get("source", "")
            dest = args.get("destination", "")
            src_name = Path(source).name if source else source
            dest_path = Path(dest)
            if dest_path.exists():
                confirmed = await self._ask(
                    ask_callback,
                    f"'{dest_path.name}' already exists at destination. Overwrite?",
                    ["Yes, overwrite", "No, cancel"],
                )
                if not confirmed:
                    return {"success": False, "message": "Copy cancelled by user"}
            return None

        if tool_name == "create_file":
            path = args.get("path", "")
            if not path:
                return None
            if os.path.exists(path):
                display = Path(path).name or path
                confirmed = await self._ask(
                    ask_callback,
                    f"'{display}' already exists. Overwrite?",
                    ["Yes, overwrite", "No, cancel"],
                )
                if not confirmed:
                    return {"success": False, "message": "Create file cancelled by user"}
            return None

        return None

    async def _ask(self, ask_callback, question: str, options: list[str]) -> bool:
        if not ask_callback:
            return True
        try:
            result = await ask_callback(question, options)
            if isinstance(result, dict):
                answer = result.get("text", "")
            else:
                answer = str(result)
            return answer.lower().startswith("yes")
        except Exception:
            return False
