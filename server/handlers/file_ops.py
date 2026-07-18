import os
import shutil
from pathlib import Path

ALLOWED_ROOTS = [
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Music",
    Path.home() / "Videos",
]


def _safe_path(p: str) -> Path | None:
    try:
        resolved = Path(p).expanduser().resolve()
    except (OSError, ValueError):
        return None
    if resolved.as_posix().startswith(("\\\\.\\", "\\\\?\\")):
        return None
    for root in ALLOWED_ROOTS:
        try:
            resolved.relative_to(root.resolve())
            return resolved
        except ValueError:
            continue
    return None


class FileOps:
    def navigate(self, path: str) -> dict:
        resolved = _safe_path(path)
        if resolved is None:
            return {"success": False, "message": "Path outside allowed directories"}
        if resolved.exists():
            os.startfile(resolved)
            return {"success": True, "message": f"Opened {resolved}"}
        return {"success": False, "message": f"Path not found: {resolved}"}

    def list_dir(self, path: str = ".") -> dict:
        resolved = _safe_path(path)
        if resolved is None:
            return {"success": False, "message": "Path outside allowed directories"}
        if not resolved.exists():
            return {"success": False, "message": f"Path not found: {resolved}"}
        if not resolved.is_dir():
            return {"success": False, "message": f"Not a directory: {resolved}"}
        items = []
        for p in resolved.iterdir():
            suffix = "/" if p.is_dir() else ""
            items.append(f"{p.name}{suffix}")
        return {
            "success": True,
            "message": f"Contents of {resolved}:\n" + "\n".join(items[:500]),
        }

    def create_file(self, path: str, content: str = "") -> dict:
        resolved = _safe_path(path)
        if resolved is None:
            return {"success": False, "message": "Path outside allowed directories"}
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content)
        return {"success": True, "message": f"Created file: {resolved}"}

    def create_folder(self, path: str) -> dict:
        resolved = _safe_path(path)
        if resolved is None:
            return {"success": False, "message": "Path outside allowed directories"}
        resolved.mkdir(parents=True, exist_ok=True)
        return {"success": True, "message": f"Created folder: {resolved}"}

    def delete(self, path: str) -> dict:
        resolved = _safe_path(path)
        if resolved is None:
            return {"success": False, "message": "Path outside allowed directories"}
        if not resolved.exists():
            return {"success": False, "message": f"Path not found: {resolved}"}
        if resolved.is_dir():
            shutil.rmtree(resolved)
        else:
            resolved.unlink()
        return {"success": True, "message": f"Deleted: {resolved}"}

    def copy(self, source: str, destination: str) -> dict:
        src = _safe_path(source)
        dst = _safe_path(destination)
        if src is None:
            return {"success": False, "message": "Source path outside allowed directories"}
        if dst is None:
            return {"success": False, "message": "Destination path outside allowed directories"}
        if not src.exists():
            return {"success": False, "message": f"Source not found: {src}"}
        if src.is_dir():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)
        return {"success": True, "message": f"Copied {src} to {dst}"}

    def move(self, source: str, destination: str) -> dict:
        src = _safe_path(source)
        dst = _safe_path(destination)
        if src is None:
            return {"success": False, "message": "Source path outside allowed directories"}
        if dst is None:
            return {"success": False, "message": "Destination path outside allowed directories"}
        if not src.exists():
            return {"success": False, "message": f"Source not found: {src}"}
        shutil.move(str(src), str(dst))
        return {"success": True, "message": f"Moved {src} to {dst}"}
