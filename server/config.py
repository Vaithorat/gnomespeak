import base64
import contextlib
import json
import msvcrt
import os
import secrets
import tempfile
import time
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_APPDATA_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "VoiceTalk"


class ConfigError(RuntimeError):
    pass


class ConfigUnlockError(ConfigError):
    pass


class Config:
    def __init__(self, config_path="config.json"):
        raw_path = Path(config_path)
        if raw_path.is_absolute():
            self.config_path = raw_path.resolve()
        else:
            _APPDATA_DIR.mkdir(parents=True, exist_ok=True)
            self.config_path = (_APPDATA_DIR / raw_path).resolve()
        self._master_path = self.config_path.parent / ".master"
        self._master_backup_path = self.config_path.parent / ".master.bak"
        self._lock_path = self.config_path.parent / ".config.lock"
        self.data = self._load_or_create()
        self._fernet = None

    @contextlib.contextmanager
    def _locked_files(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._lock_path, "a+b") as lock_file:
            lock_file.seek(0)
            deadline = time.time() + 10
            while True:
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.time() >= deadline:
                        raise ConfigError("Timed out waiting for the configuration lock.")
                    time.sleep(0.1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)

    def _derive_key(self, master_password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=600000,
        )
        return base64.urlsafe_b64encode(kdf.derive(master_password.encode()))

    def _load_or_create(self):
        if self.config_path.exists():
            with open(self.config_path) as f:
                return json.load(f)
        return {
            "host": "0.0.0.0",
            "port": 8765,
            "encrypted_data": None,
            "salt": None,
        }

    def _get_or_create_master_password(self) -> str:
        if self._master_path.exists():
            return self._master_path.read_text().strip()
        if self.data.get("encrypted_data"):
            raise ConfigUnlockError(self.recovery_instructions())
        pw = secrets.token_urlsafe(24)
        self._write_master_password(pw, backup_existing=False)
        return pw

    def auto_unlock(self):
        pw = self._get_or_create_master_password()
        try:
            self.unlock(pw)
        except ValueError as exc:
            raise ConfigUnlockError(self.recovery_instructions()) from exc

    def unlock(self, master_password: str):
        salt = (
            base64.urlsafe_b64decode(self.data["salt"])
            if self.data.get("salt")
            else os.urandom(16)
        )
        if not self.data.get("salt"):
            self.data["salt"] = base64.urlsafe_b64encode(salt).decode()
        key = self._derive_key(master_password, salt)
        self._fernet = Fernet(key)
        if self.data.get("encrypted_data"):
            try:
                self._fernet.decrypt(self.data["encrypted_data"].encode())
            except Exception:
                raise ValueError(
                    "Wrong master password. Cannot decrypt configuration."
                )

    def has_master_backup(self) -> bool:
        return self._master_backup_path.exists()

    def recovery_instructions(self) -> str:
        return (
            "Unable to unlock the saved configuration.\n"
            f"Config: {self.config_path}\n"
            f"Master key: {self._master_path}\n"
            f"Backup key: {self._master_backup_path}\n"
            "Use the GUI recovery options to retry, restore the backup key, or reset the encrypted configuration. "
            "For CLI use, restore .master from .master.bak if available, or delete the encrypted configuration only if you accept losing saved secrets."
        )

    def restore_master_backup(self):
        if not self._master_backup_path.exists():
            raise ConfigError("No master-key backup is available.")
        with self._locked_files():
            backup_text = self._master_backup_path.read_text()
            self._write_master_password(backup_text.strip(), backup_existing=False)

    def reset_encrypted_config(self):
        with self._locked_files():
            self.data["encrypted_data"] = None
            self.data["salt"] = None
            self.save(locked=True)
            self._fernet = None
            self._write_master_password(secrets.token_urlsafe(24), backup_existing=True)

    def _write_master_password(self, password: str, backup_existing: bool):
        self._master_path.parent.mkdir(parents=True, exist_ok=True)
        if backup_existing and self._master_path.exists():
            self._master_backup_path.write_text(self._master_path.read_text())
        fd, tmp = tempfile.mkstemp(dir=str(self._master_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(password)
            os.replace(tmp, str(self._master_path))
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _ensure_unlocked(self):
        if self._fernet is None:
            raise RuntimeError(
                "Config not unlocked. Call unlock(master_password) first."
            )

    def get_secret(self, key: str):
        self._ensure_unlocked()
        if not self.data.get("encrypted_data"):
            return None
        decrypted = self._fernet.decrypt(
            self.data["encrypted_data"].encode()
        )
        secrets = json.loads(decrypted)
        return secrets.get(key)

    def set_secret(self, key: str, value: str):
        self._ensure_unlocked()
        current = {}
        if self.data.get("encrypted_data"):
            decrypted = self._fernet.decrypt(
                self.data["encrypted_data"].encode()
            )
            current = json.loads(decrypted)
        current[key] = value
        encrypted = self._fernet.encrypt(
            json.dumps(current).encode()
        ).decode()
        self.data["encrypted_data"] = encrypted

    def save(self, locked: bool = False):
        if not locked:
            with self._locked_files():
                self.save(locked=True)
            return
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.config_path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, str(self.config_path))
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    @property
    def host(self):
        return self.data.get("host", "0.0.0.0")

    @property
    def port(self):
        return self.data.get("port", 8765)
