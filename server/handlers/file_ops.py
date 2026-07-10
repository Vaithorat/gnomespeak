import os
import shutil
from pathlib import Path


class FileOps:
    def navigate(self, path: str) -> dict:
        path = Path(path).expanduser().resolve()
        if path.exists():
            os.startfile(path)
            return {"success": True, "message": f"Opened {path}"}
        return {"success": False, "message": f"Path not found: {path}"}

    def list_dir(self, path: str = ".") -> dict:
        path = Path(path).expanduser().resolve()
        if not path.exists():
            return {"success": False, "message": f"Path not found: {path}"}
        if not path.is_dir():
            return {"success": False, "message": f"Not a directory: {path}"}
        items = []
        for p in path.iterdir():
            suffix = "/" if p.is_dir() else ""
            items.append(f"{p.name}{suffix}")
        return {
            "success": True,
            "message": f"Contents of {path}:\n" + "\n".join(items),
        }

    def create_file(self, path: str, content: str = "") -> dict:
        path = Path(path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return {"success": True, "message": f"Created file: {path}"}

    def create_folder(self, path: str) -> dict:
        path = Path(path).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        return {"success": True, "message": f"Created folder: {path}"}

    def delete(self, path: str) -> dict:
        path = Path(path).expanduser().resolve()
        if not path.exists():
            return {"success": False, "message": f"Path not found: {path}"}
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return {"success": True, "message": f"Deleted: {path}"}

    def copy(self, source: str, destination: str) -> dict:
        source = Path(source).expanduser().resolve()
        dest = Path(destination).expanduser().resolve()
        if not source.exists():
            return {"success": False, "message": f"Source not found: {source}"}
        if source.is_dir():
            shutil.copytree(source, dest)
        else:
            shutil.copy2(source, dest)
        return {"success": True, "message": f"Copied {source} to {dest}"}

    def move(self, source: str, destination: str) -> dict:
        source = Path(source).expanduser().resolve()
        dest = Path(destination).expanduser().resolve()
        if not source.exists():
            return {"success": False, "message": f"Source not found: {source}"}
        shutil.move(str(source), str(dest))
        return {"success": True, "message": f"Moved {source} to {dest}"}
