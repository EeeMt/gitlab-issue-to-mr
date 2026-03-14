"""Helpers for encrypting persisted sensitive configuration values."""

from __future__ import annotations

import base64
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class ConfigEncryptionError(RuntimeError):
    """Raised when encrypted config cannot be processed safely."""


def _get_fernet() -> Fernet:
    settings = get_settings()
    raw_key = settings.config_encryption_key or settings.session_secret
    if not raw_key or raw_key == "change-me-in-production":
        raise ConfigEncryptionError(
            "CONFIG_ENCRYPTION_KEY or a non-default SESSION_SECRET is required for encrypted config storage"
        )

    derived_key = base64.urlsafe_b64encode(sha256(raw_key.encode("utf-8")).digest())
    return Fernet(derived_key)


def encrypt_config_secret(value: str) -> str:
    """Encrypt a secret value before persisting it."""
    if not value:
        raise ConfigEncryptionError("Secret config value cannot be empty")
    return _get_fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_config_secret(value: str) -> str:
    """Decrypt a secret value loaded from persisted config storage."""
    try:
        return _get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ConfigEncryptionError("Unable to decrypt persisted secret config value") from exc
