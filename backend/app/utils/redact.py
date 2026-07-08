"""Recursive masking of secret values in dicts/lists.

Used for (1) workflow node-run history, where resolved configs may embed
API keys / Authorization headers, and (2) API responses that echo stored
credentials back to the client. Masked values keep the last 4 characters
so users can recognise which credential is set; `is_masked` lets update
endpoints detect an unchanged masked value and preserve the original.
"""
from typing import Any

MASK_PREFIX = "****"

SENSITIVE_KEYS = {
    "apikey",
    "api_key",
    "api_token",
    "apitoken",
    "token",
    "secret",
    "password",
    "authorization",
    "authheader",
    "auth_header",
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",  # Google service-account key
    "webhook_secret",
    "x-api-key",
}


def _is_sensitive_key(key: Any) -> bool:
    return isinstance(key, str) and key.replace("-", "_").lower().replace("_", "") in {
        k.replace("-", "_").replace("_", "") for k in SENSITIVE_KEYS
    }


def mask_secret(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return MASK_PREFIX if value else value
    if value.startswith(MASK_PREFIX):
        return value
    return MASK_PREFIX + value[-4:] if len(value) > 8 else MASK_PREFIX


def is_masked(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(MASK_PREFIX)


def redact_secrets(obj: Any) -> Any:
    """Return a deep copy of obj with values under sensitive keys masked."""
    if isinstance(obj, dict):
        return {
            k: mask_secret(v) if _is_sensitive_key(k) and isinstance(v, (str, int)) else redact_secrets(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact_secrets(item) for item in obj]
    return obj


def restore_masked_secrets(new: Any, existing: Any) -> Any:
    """Merge helper for updates: wherever `new` carries a masked value under a
    sensitive key, substitute the corresponding value from `existing`."""
    if isinstance(new, dict):
        existing = existing if isinstance(existing, dict) else {}
        return {
            k: (
                existing.get(k)
                if _is_sensitive_key(k) and is_masked(v) and k in existing
                else restore_masked_secrets(v, existing.get(k))
            )
            for k, v in new.items()
        }
    if isinstance(new, list):
        return [restore_masked_secrets(item, None) for item in new]
    return new
