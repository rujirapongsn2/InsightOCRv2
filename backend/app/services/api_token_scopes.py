"""Scope definitions shared by Personal API Tokens and the MCP endpoint."""

from __future__ import annotations

from typing import Any


MCP_READ_SCOPE = "mcp:read"
MCP_JOB_WRITE_SCOPE = "mcp:jobs:write"
MCP_DOCUMENT_UPLOAD_SCOPE = "mcp:documents:upload"
MCP_DOCUMENT_PROCESS_SCOPE = "mcp:documents:process"
MCP_DOCUMENT_REVIEW_SCOPE = "mcp:documents:review"

API_TOKEN_SCOPES = {
    MCP_READ_SCOPE,
    MCP_JOB_WRITE_SCOPE,
    MCP_DOCUMENT_UPLOAD_SCOPE,
    MCP_DOCUMENT_PROCESS_SCOPE,
    MCP_DOCUMENT_REVIEW_SCOPE,
}
DEFAULT_API_TOKEN_SCOPES = [MCP_READ_SCOPE]


def normalize_api_token_scopes(value: Any) -> list[str]:
    """Validate scopes and provide safe read-only compatibility for old tokens."""
    if value is None:
        return list(DEFAULT_API_TOKEN_SCOPES)
    if not isinstance(value, list) or any(not isinstance(scope, str) for scope in value):
        raise ValueError("Token scopes must be a list of scope names")
    normalized = sorted({scope.strip() for scope in value if scope.strip()})
    unknown = sorted(set(normalized) - API_TOKEN_SCOPES)
    if unknown:
        raise ValueError(f"Unsupported token scope(s): {', '.join(unknown)}")
    if MCP_READ_SCOPE not in normalized:
        normalized.insert(0, MCP_READ_SCOPE)
    return normalized
