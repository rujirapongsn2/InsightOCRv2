import pytest
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from jose import jwt

from app.api import deps


def test_mcp_only_token_cannot_authenticate_a_general_rest_endpoint(monkeypatch):
    def reject_jwt(*_args, **_kwargs):
        raise jwt.JWTError()

    monkeypatch.setattr(deps.jwt, "decode", reject_jwt)
    monkeypatch.setattr(deps, "_get_api_access_token", lambda *_args: type("Token", (), {"mcp_access_only": True})())

    with pytest.raises(HTTPException) as exc_info:
        deps.get_current_user(db=object(), token="mcp-only-token")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "This token is restricted to the MCP endpoint"


def test_last_used_timestamp_is_throttled():
    now = datetime.now(timezone.utc)
    assert deps._should_update_last_used(None, now) is True
    assert deps._should_update_last_used(now - timedelta(seconds=10), now) is False
    assert deps._should_update_last_used(now - timedelta(minutes=6), now) is True
