from datetime import datetime, timezone

from jose import jwt

from app.core import security
from app.core.config import settings


def test_refresh_token_is_distinct_and_long_lived():
    token = security.create_refresh_token("user-123")
    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[security.ALGORITHM])

    assert claims["sub"] == "user-123"
    assert claims["type"] == "refresh"
    assert claims["exp"] > datetime.now(timezone.utc).timestamp() + (29 * 24 * 60 * 60)


def test_access_token_cannot_be_used_as_refresh_token():
    token = security.create_access_token("user-123")
    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[security.ALGORITHM])

    assert claims.get("type") is None
