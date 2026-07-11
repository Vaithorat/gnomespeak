import json
import os
from pathlib import Path
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64


DEFAULT_MASTER_PASSWORD = "voicetalk"


class Config:
    def __init__(self, config_path="config.json"):
        self.config_path = Path(config_path)
        self.data = self._load_or_create()
        self._fernet = None

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

    def auto_unlock(self):
        self.unlock(DEFAULT_MASTER_PASSWORD)

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

    def save(self):
        with open(self.config_path, "w") as f:
            json.dump(self.data, f, indent=2)

    @property
    def host(self):
        return self.data.get("host", "0.0.0.0")

    @property
    def port(self):
        return self.data.get("port", 8765)
