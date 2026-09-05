"""Capability records for workflow LLM integrations.

An Agent tool-call verification is valid only for the exact endpoint, model,
and credential configuration that was tested. The fingerprint intentionally
contains a one-way digest of those values, never the values themselves.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def integration_tool_calling_fingerprint(
    integration_type: Any,
    config: Mapping[str, Any] | None,
) -> str:
    values = dict(config or {})
    type_value = integration_type.value if hasattr(integration_type, "value") else str(integration_type)
    payload = {
        "type": type_value,
        "base_url": str(values.get("baseUrl") or "").strip().rstrip("/"),
        "model": str(values.get("model") or "").strip(),
        "credential": str(values.get("apiKeyEncrypted") or values.get("apiKey") or ""),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def integration_supports_tool_calling(integration: Any) -> bool:
    """Return true only for a server-issued verification of current config."""
    config = getattr(integration, "config", None) or {}
    verification = config.get("agentToolsVerification") or {}
    fingerprint = verification.get("fingerprint") if isinstance(verification, dict) else None
    if not fingerprint:
        return False
    return fingerprint == integration_tool_calling_fingerprint(
        getattr(integration, "type", ""),
        config,
    )
