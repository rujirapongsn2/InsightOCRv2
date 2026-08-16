import os

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret")

from app.models.integration import Integration, IntegrationStatus, IntegrationType
from app.services import workflow_engine
from app.services.workflow_engine import NodeExecutionError, _exec_api


class _Query:
    def __init__(self, integration):
        self.integration = integration

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.integration


class _Session:
    def __init__(self, integration):
        self.integration = integration

    def query(self, *args, **kwargs):
        return _Query(self.integration)


class _Response:
    status_code = 201
    text = ""
    headers = {"Content-Type": "application/json"}
    encoding = "utf-8"
    closed = False

    def json(self):
        return {"accepted": True, "reference": "EXT-42"}

    def iter_content(self, chunk_size=65536):
        yield b'{"accepted":true,"reference":"EXT-42"}'

    def close(self):
        self.closed = True


def _api_integration(integration_status=IntegrationStatus.ACTIVE, **config):
    return Integration(
        name="Accounting API",
        type=IntegrationType.API,
        status=integration_status,
        config={
            "method": "POST",
            "endpoint": "https://api.example.com/invoices",
            "authHeader": "Authorization: Bearer saved-token",
            "headersJson": '{"X-Source": "InsightDOC"}',
            **config,
        },
    )


def test_api_node_sends_upstream_payload_with_saved_custom_api_credentials(monkeypatch):
    integration = _api_integration()
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        return _Response()

    monkeypatch.setattr(workflow_engine, "_request_custom_api", fake_request)

    result = _exec_api(
        _Session(integration),
        {"integration_id": "ignored-by-fake-session", "body": {"invoice_no": "INV-1"}, "timeout_seconds": 20},
        {"_owner_user_id": None},
        lambda message: None,
    )

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.example.com/invoices"
    assert captured["json"] == {"invoice_no": "INV-1"}
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer saved-token",
        "X-Source": "InsightDOC",
    }
    assert captured["timeout"] == 20
    assert captured["allow_redirects"] is False
    assert result["integration_name"] == "Accounting API"
    assert result["body"] == {"accepted": True, "reference": "EXT-42"}


def test_api_node_uses_saved_payload_template_when_body_is_empty(monkeypatch):
    integration = _api_integration(payloadTemplate='{"source":"workflow"}')
    captured = {}
    monkeypatch.setattr(
        workflow_engine,
        "_request_custom_api",
        lambda method, url, **kwargs: captured.update(kwargs) or _Response(),
    )

    _exec_api(
        _Session(integration),
        {"integration_id": "ignored-by-fake-session", "body": ""},
        {"_owner_user_id": None},
        lambda message: None,
    )

    assert captured["json"] == {"source": "workflow"}


def test_api_node_rejects_invalid_saved_headers(monkeypatch):
    integration = _api_integration(headersJson="not-json")
    try:
        _exec_api(
            _Session(integration),
            {"integration_id": "ignored-by-fake-session"},
            {"_owner_user_id": None},
            lambda message: None,
        )
    except NodeExecutionError as exc:
        assert "Headers" in str(exc)
    else:
        raise AssertionError("Expected invalid JSON headers to be rejected")


def test_api_node_rejects_paused_custom_api(monkeypatch):
    integration = _api_integration(integration_status=IntegrationStatus.PAUSED)
    try:
        _exec_api(
            _Session(integration),
            {"integration_id": "ignored-by-fake-session"},
            {"_owner_user_id": None},
            lambda message: None,
        )
    except NodeExecutionError as exc:
        assert "ยังไม่พร้อมใช้งาน" in str(exc)
    else:
        raise AssertionError("Expected paused integration to be rejected")


def test_api_response_is_bounded(monkeypatch):
    class _LargeResponse(_Response):
        headers = {"Content-Length": "1048577"}

        def iter_content(self, chunk_size=65536):
            raise AssertionError("Content-Length should reject before streaming")

    with pytest.raises(NodeExecutionError, match="response exceeds"):
        workflow_engine._read_custom_api_response(_LargeResponse())
