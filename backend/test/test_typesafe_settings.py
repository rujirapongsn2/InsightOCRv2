"""TypeSafe settings: key persistence rules and the connection-test endpoint."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.api.v1.endpoints import settings as ep
from app.schemas.setting import SettingUpdate
from app.utils.redact import mask_secret

STORED_KEY = "ts-stored-secret-key"


def _setting(**overrides):
    base = dict(id="s1", typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key=STORED_KEY,
                ocr_fallback_api_key=None, api_token=None)
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def save(monkeypatch):
    monkeypatch.setattr(ep, "log_activity", lambda **kw: None)
    monkeypatch.setattr(ep, "get_app_commit_sha", lambda: None)
    monkeypatch.setattr(ep, "_set_fallback_metadata", lambda s: None)
    monkeypatch.setattr(ep, "_setting_response", lambda s: s)

    def run(setting, **payload):
        db = Mock()
        db.query.return_value.first.return_value = setting
        ep.update_settings(db=db, payload=SettingUpdate(**payload), current_user=SimpleNamespace(id="u1"))
        return setting
    return run


@pytest.mark.parametrize("key", ["", None, mask_secret(STORED_KEY)])
def test_blank_or_masked_key_keeps_stored_key(save, key):
    s = save(_setting(), typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key=key)
    assert s.typesafe_api_key == STORED_KEY


def test_omitted_typesafe_fields_keep_stored_config(save):
    s = save(_setting())
    assert (s.typesafe_endpoint, s.typesafe_api_key) == ("https://api.typesafe.ai", STORED_KEY)


def test_new_key_replaces_stored_key(save):
    s = save(_setting(), typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key="ts-new-key")
    assert s.typesafe_api_key == "ts-new-key"


def test_clearing_endpoint_disables_typesafe(save):
    s = save(_setting(), typesafe_endpoint="", typesafe_api_key=mask_secret(STORED_KEY))
    assert (s.typesafe_endpoint, s.typesafe_api_key) == (None, None)


def test_changing_endpoint_drops_old_key_unless_new_key_given(save):
    s = save(_setting(), typesafe_endpoint="https://other-host.example", typesafe_api_key=mask_secret(STORED_KEY))
    assert (s.typesafe_endpoint, s.typesafe_api_key) == ("https://other-host.example", None)
    s = save(_setting(), typesafe_endpoint="https://other-host.example", typesafe_api_key="ts-other-key")
    assert (s.typesafe_endpoint, s.typesafe_api_key) == ("https://other-host.example", "ts-other-key")


def test_trailing_slash_is_not_an_endpoint_change(save):
    s = save(_setting(), typesafe_endpoint="https://api.typesafe.ai/", typesafe_api_key=mask_secret(STORED_KEY))
    assert s.typesafe_api_key == STORED_KEY


def test_new_key_with_blank_endpoint_uses_default_endpoint(save):
    from app.services.typesafe import DEFAULT_TYPESAFE_ENDPOINT
    s = save(_setting(typesafe_endpoint=None, typesafe_api_key=None), typesafe_endpoint="", typesafe_api_key="ts-new-key")
    assert (s.typesafe_endpoint, s.typesafe_api_key) == (DEFAULT_TYPESAFE_ENDPOINT, "ts-new-key")


@pytest.fixture
def probe(monkeypatch):
    calls = []

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "auth": headers["Authorization"]})
        return SimpleNamespace(status_code=200, headers={}, text="")

    monkeypatch.setattr(ep.requests, "post", fake_post)
    monkeypatch.delenv("TYPESAFE_ENDPOINT", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def run(setting, **payload):
        session = Mock()
        session.query.return_value.first.return_value = setting
        monkeypatch.setattr("app.db.session.SessionLocal", lambda: session)
        out = ep.test_typesafe_configuration(payload=ep.TypeSafeTestRequest(**payload),
                                             current_user=SimpleNamespace(id="u1"))
        return out, calls
    return run


def test_stored_key_never_sent_to_caller_supplied_endpoint(probe):
    out, calls = probe(_setting(), endpoint="https://attacker.example", api_key=mask_secret(STORED_KEY))
    assert out["status"] == "failed"
    assert calls == []


def test_masked_key_uses_stored_key_with_stored_endpoint(probe):
    out, calls = probe(_setting(), endpoint="https://api.typesafe.ai/", api_key=mask_secret(STORED_KEY))
    assert out["status"] == "connected"
    assert calls == [{"url": "https://api.typesafe.ai/v1/systemone", "auth": f"Bearer {STORED_KEY}"}]


def test_explicit_new_key_may_target_any_endpoint(probe):
    out, calls = probe(_setting(), endpoint="https://staging.typesafe.ai", api_key="ts-unsaved")
    assert out["status"] == "connected"
    assert calls[0]["url"].startswith("https://staging.typesafe.ai") and calls[0]["auth"] == "Bearer ts-unsaved"


def test_env_configured_typesafe_is_testable(probe, monkeypatch):
    monkeypatch.setenv("TYPESAFE_ENDPOINT", "https://env.typesafe.ai")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-env-key")
    out, calls = probe(_setting(typesafe_endpoint=None, typesafe_api_key=None))
    assert out["status"] == "connected"
    assert calls == [{"url": "https://env.typesafe.ai/v1/systemone", "auth": "Bearer ts-env-key"}]


def test_typesafe_save_leaves_ocr_settings_untouched(monkeypatch):
    monkeypatch.setattr(ep, "log_activity", lambda **kw: None)
    monkeypatch.setattr(ep, "get_app_commit_sha", lambda: None)
    monkeypatch.setattr(ep, "_setting_response", lambda s: s)
    setting = _setting(ocr_endpoint="https://ocr.example", ocr_fallback_enabled=True, verify_ssl=True)
    db = Mock()
    db.query.return_value.first.return_value = setting
    ep.update_typesafe_settings(db=db, payload=ep.TypeSafeConfigUpdate(
        typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key="ts-new-key"), current_user=SimpleNamespace(id="u1"))
    assert setting.typesafe_api_key == "ts-new-key"
    assert (setting.ocr_endpoint, setting.ocr_fallback_enabled, setting.verify_ssl) == ("https://ocr.example", True, True)
    assert setting.typesafe_source == "db"


def test_db_endpoint_without_key_never_borrows_env_key(monkeypatch):
    from app.services.typesafe import TypeSafeConfigurationError, resolve_typesafe_config, typesafe_config_source
    monkeypatch.setenv("TYPESAFE_ENDPOINT", "https://env.typesafe.ai")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts-env-key")
    with pytest.raises(TypeSafeConfigurationError):
        resolve_typesafe_config(_setting(typesafe_api_key=None))
    assert typesafe_config_source(_setting(typesafe_endpoint=None, typesafe_api_key=None)) == "env"
    assert resolve_typesafe_config(_setting()).api_key == STORED_KEY
