"""Small application secret store backed by the deployment SECRET_KEY."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class SecretStoreError(ValueError):
    """Raised when an application secret cannot be decrypted."""


def _fernet() -> Fernet:
    digest = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    if not value:
        raise SecretStoreError("Cannot encrypt an empty secret")
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise SecretStoreError("Invalid encrypted secret") from exc
