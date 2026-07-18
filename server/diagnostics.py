import json
import os
import platform
import re
import socket
import sys
import zipfile
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from config import Config
from version import CONFIG_SCHEMA_VERSION, SERVER_VERSION


_APPDATA_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "VoiceTalk"
_LOG_FILE = _APPDATA_DIR / "logs" / "voicetalk-server.log"
_DIAGNOSTICS_DIR = _APPDATA_DIR / "diagnostics"
_ROOT_DIR = Path(__file__).resolve().parent.parent
_CLIENT_BUILD_FILE = _ROOT_DIR / "client" / "android" / "app" / "build.gradle"
_SERVER_REQUIREMENTS = Path(__file__).resolve().parent / "requirements.txt"
_REDACTIONS = [
    (re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)([^\s,]+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(smtp_password\s*[:=]\s*)([^\s,]+)"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,]+)"), r"\1[REDACTED]"),
]


def _sanitize_text(text: str) -> str:
    cleaned = text
    for pattern, replacement in _REDACTIONS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


def _read_log_text() -> str:
    if not _LOG_FILE.exists():
        return ""
    return _sanitize_text(_LOG_FILE.read_text(encoding="utf-8", errors="replace"))


def _parse_android_version() -> dict:
    if not _CLIENT_BUILD_FILE.exists():
        return {"version_name": "unknown", "version_code": "unknown"}
    text = _CLIENT_BUILD_FILE.read_text(encoding="utf-8")
    name_match = re.search(r'versionName\s+"([^"]+)"', text)
    code_match = re.search(r"versionCode\s+(\d+)", text)
    return {
        "version_name": name_match.group(1) if name_match else "unknown",
        "version_code": int(code_match.group(1)) if code_match else "unknown",
    }


def _collect_dependency_versions() -> dict:
    versions = {
        "python": platform.python_version(),
    }
    if _SERVER_REQUIREMENTS.exists():
        for line in _SERVER_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
            package = line.strip()
            if not package or package.startswith("#"):
                continue
            normalized = re.split(r"[<>=]", package, maxsplit=1)[0].strip()
            try:
                versions[normalized] = metadata.version(normalized)
            except metadata.PackageNotFoundError:
                versions[normalized] = "not-installed"
    return versions


def _connectivity_test(config: Config) -> dict:
    host = config.host
    port = config.port
    target_host = "127.0.0.1" if host == "0.0.0.0" else host
    try:
        with socket.create_connection((target_host, port), timeout=2):
            return {
                "success": True,
                "tested_host": target_host,
                "tested_port": port,
                "message": "TCP connection succeeded.",
            }
    except Exception as exc:
        return {
            "success": False,
            "tested_host": target_host,
            "tested_port": port,
            "message": f"TCP connection failed: {exc}",
        }


def create_diagnostics_bundle(config: Config | None = None) -> tuple[bool, str, Path | None]:
    cfg = config or Config()
    _DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    bundle_path = _DIAGNOSTICS_DIR / f"voicetalk-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "server_version": SERVER_VERSION,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "android_client": _parse_android_version(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "paths": {
            "config": str(cfg.config_path),
            "master_key": str(cfg._master_path),
            "master_key_backup": str(cfg._master_backup_path),
            "log_file": str(_LOG_FILE),
        },
        "network": {
            "configured_host": cfg.host,
            "configured_port": cfg.port,
            "connectivity_test": _connectivity_test(cfg),
        },
        "dependency_versions": _collect_dependency_versions(),
    }

    try:
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("summary.json", json.dumps(summary, indent=2))
            log_text = _read_log_text()
            if log_text:
                archive.writestr("voicetalk-server.log", log_text)
        return True, f"Diagnostics bundle created: {bundle_path}", bundle_path
    except Exception as exc:
        return False, f"Failed to create diagnostics bundle: {exc}", None


if __name__ == "__main__":
    ok, message, _ = create_diagnostics_bundle()
    print(message)
    raise SystemExit(0 if ok else 1)
