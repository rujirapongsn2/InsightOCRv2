from app.services.cloud_oauth import (
    CloudOAuthError,
    _state_token,
    consume_state,
    decrypt_refresh_token,
    encrypt_refresh_token,
    parse_state,
)


def test_refresh_token_round_trip_is_encrypted():
    token = "refresh-token-for-test"
    encrypted = encrypt_refresh_token(token)

    assert encrypted != token
    assert decrypt_refresh_token(encrypted) == token


def test_oauth_state_is_bound_to_provider(monkeypatch):
    class FakeRedis:
        def __init__(self):
            self.values = {}

        def setex(self, key, _ttl, value):
            self.values[key] = value

        def getdel(self, key):
            return self.values.pop(key, None)

    fake = FakeRedis()
    monkeypatch.setattr("app.db.redis.get_redis_client", lambda: fake)
    state = _state_token("google", "user-123")

    assert parse_state(state, "google") == "user-123"
    assert consume_state(state, "google") == "user-123"

    try:
        consume_state(state, "google")
    except CloudOAuthError:
        pass
    else:
        raise AssertionError("OAuth state must be single-use")

    try:
        parse_state(state, "microsoft")
    except CloudOAuthError:
        pass
    else:
        raise AssertionError("OAuth state must not be reusable for another provider")


def test_invalid_refresh_token_is_rejected():
    try:
        decrypt_refresh_token("not-a-fernet-token")
    except CloudOAuthError:
        pass
    else:
        raise AssertionError("Invalid encrypted refresh token must be rejected")
