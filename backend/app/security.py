import base64
import hashlib
import logging

from cryptography.fernet import Fernet

from backend.app.config import get_settings

logger = logging.getLogger(__name__)


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


def _key_candidates() -> list[bytes]:
    settings = get_settings()
    primary = _load_or_create_key()
    candidates = [primary]
    key_file = settings.data_dir / ".secret_key"
    if key_file.exists():
        persisted = key_file.read_bytes()
        if persisted not in candidates:
            candidates.append(persisted)
    return candidates


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    token = value.encode("utf-8")
    for key in _key_candidates():
        try:
            return Fernet(key).decrypt(token).decode("utf-8")
        except Exception as exc:
            logger.debug("Secret decrypt failed with a candidate key: %s", exc)
            continue
    raise ValueError("Unable to decrypt secret with any configured key")
