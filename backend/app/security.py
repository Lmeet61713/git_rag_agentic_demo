import base64
import hashlib

from cryptography.fernet import Fernet

from backend.app.config import get_settings


def _load_or_create_key() -> bytes:
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    if settings.app_secret_key and settings.app_secret_key != "change-me":
        return base64.urlsafe_b64encode(hashlib.sha256(settings.app_secret_key.encode()).digest())
    key_file = settings.data_dir / ".secret_key"
    if key_file.exists():
        return key_file.read_bytes()
    key = Fernet.generate_key()
    key_file.write_bytes(key)
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
