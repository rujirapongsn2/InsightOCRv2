from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

import app.api.v1.endpoints.integrations as integrations_endpoint

from app.api.v1.endpoints.integrations import (
    SOFTNIX_GENAI_BASE_URL,
    TestLLMRequest as LLMTestRequest,
    _call_llm_text,
    _authorize_send_target,
    _integration_api_key,
    _is_llm_integration,
    _llm_base_url_for_integration,
    _normalize_llm_base_url,
    _normalize_softnix_config,
    _verify_native_tool_calling,
)
from app.models.integration import IntegrationStatus, IntegrationType
from app.schemas.integration import IntegrationCreate
from app.services.llm_provider_capabilities import integration_supports_tool_calling, integration_tool_calling_fingerprint
from app.utils.secret_store import decrypt_secret


def test_softnix_genai_is_an_llm_integration():
    integration = SimpleNamespace(type=IntegrationType.SOFTNIX_GENAI)

    assert _is_llm_integration(integration)


def test_softnix_genai_type_is_accepted_by_schema():
    integration = IntegrationCreate(
        name="Softnix GenAI",
        type="softnix_genai",
        config={
            "apiKey": "test-key",
            "baseUrl": "https://genai.softnix.ai/external/openai",
            "model": "gpt-5.5",
        },
    )

    assert integration.type == "softnix_genai"


def test_chat_completions_endpoint_forces_chat_mode():
    base_url, mode = _normalize_llm_base_url(
        "https://genai.softnix.ai/external/openai/chat/completions"
    )

    assert base_url == "https://genai.softnix.ai/external/openai"
    assert mode == "chat"


def test_softnix_uses_chat_completions_without_trying_responses(monkeypatch):
    calls = []

    class FakeClient:
        class Responses:
            def create(self, **_kwargs):
                raise AssertionError("Softnix GenAI must not call Responses API")

        class Chat:
            class Completions:
                def create(self, **kwargs):
                    calls.append(kwargs)
                    return SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
                    )

            completions = Completions()

        responses = Responses()
        chat = Chat()

    monkeypatch.setattr(integrations_endpoint, "_build_openai_client", lambda *_args: FakeClient())

    output, mode = _call_llm_text(
        api_key="test-key",
        base_url=SOFTNIX_GENAI_BASE_URL,
        model="gpt-5.5",
        input_text="Hello",
        request_mode="chat",
    )

    assert output == "ok"
    assert mode == "chat"
    assert calls[0]["model"] == "gpt-5.5"


def test_native_tool_calling_probe_requires_a_tool_call(monkeypatch):
    class FakeClient:
        class Chat:
            class Completions:
                def create(self, **_kwargs):
                    message = SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(name="connection_check"))])
                    return SimpleNamespace(choices=[SimpleNamespace(message=message)])

            completions = Completions()

        chat = Chat()

    monkeypatch.setattr(integrations_endpoint, "_build_openai_client", lambda *_args: FakeClient())

    _verify_native_tool_calling(
        api_key="test-key",
        base_url=SOFTNIX_GENAI_BASE_URL,
        model="gpt-5.5",
    )


def test_native_tool_calling_probe_rejects_text_only_provider(monkeypatch):
    class FakeClient:
        class Chat:
            class Completions:
                def create(self, **_kwargs):
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[]))])

            completions = Completions()

        chat = Chat()

    monkeypatch.setattr(integrations_endpoint, "_build_openai_client", lambda *_args: FakeClient())

    with pytest.raises(ValueError, match="native tool call"):
        _verify_native_tool_calling(
            api_key="test-key",
            base_url=SOFTNIX_GENAI_BASE_URL,
            model="gpt-5.5",
        )


def test_native_tool_calling_probe_rejects_the_wrong_tool(monkeypatch):
    class FakeClient:
        class Chat:
            class Completions:
                def create(self, **_kwargs):
                    call = SimpleNamespace(function=SimpleNamespace(name="unexpected_tool"))
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])

            completions = Completions()

        chat = Chat()

    monkeypatch.setattr(integrations_endpoint, "_build_openai_client", lambda *_args: FakeClient())

    with pytest.raises(ValueError, match="native tool call"):
        _verify_native_tool_calling("test-key", SOFTNIX_GENAI_BASE_URL, "gpt-5.5")


def test_tool_calling_verification_expires_when_provider_config_changes():
    config = {"baseUrl": "https://provider.example/v1", "model": "model-a", "apiKey": "key-a"}
    fingerprint = integration_tool_calling_fingerprint("llm", config)
    integration = SimpleNamespace(type="llm", config={
        **config,
        "agentToolsVerification": {"fingerprint": fingerprint, "verifiedAt": "2026-09-04T00:00:00+00:00"},
    })

    assert integration_supports_tool_calling(integration)
    integration.config["model"] = "model-b"
    assert not integration_supports_tool_calling(integration)


@pytest.mark.asyncio
async def test_agent_tools_endpoint_requires_a_saved_integration():
    request = LLMTestRequest(apiKey="ignored", baseUrl="http://127.0.0.1:1", model="test")
    user = SimpleNamespace(role="manager", is_superuser=False)

    with pytest.raises(HTTPException, match="Save the integration"):
        await integrations_endpoint.test_agent_tools(request, db=None, current_user=user)


def test_softnix_endpoint_is_configurable_with_default():
    config = _normalize_softnix_config(
        "softnix_genai",
        {"apiKey": "test-key", "model": "gpt-5.5", "baseUrl": "https://genai.example.com/openai"},
    )

    assert config["baseUrl"] == "https://genai.example.com/openai"


def test_softnix_endpoint_must_be_http_url():
    with pytest.raises(HTTPException, match=r"valid HTTP\(S\) URL"):
        _normalize_softnix_config(
            "softnix_genai",
            {"apiKey": "test-key", "model": "gpt-5.5", "baseUrl": "javascript:alert(1)"},
        )


def test_softnix_api_key_is_encrypted_at_rest():
    config = _normalize_softnix_config(
        "softnix_genai",
        {"apiKey": "test-key", "model": "gpt-5.5"},
    )

    assert "apiKey" not in config
    assert decrypt_secret(config["apiKeyEncrypted"]) == "test-key"
    assert _integration_api_key(SimpleNamespace(config=config)) == "test-key"


def test_softnix_config_requires_credentials():
    with pytest.raises(HTTPException, match="API Key is required"):
        _normalize_softnix_config("softnix_genai", {"model": "gpt-5.5"})


def test_softnix_integration_uses_configured_endpoint():
    integration = SimpleNamespace(
        type=IntegrationType.SOFTNIX_GENAI,
        config={"baseUrl": "https://genai.example.com/openai"},
    )

    assert _llm_base_url_for_integration(integration) == "https://genai.example.com/openai"


def test_non_llm_integration_requires_owner_or_elevated_role():
    integration = SimpleNamespace(
        type=IntegrationType.API,
        status=IntegrationStatus.ACTIVE,
        user_id=uuid4(),
    )
    user = SimpleNamespace(id=uuid4(), is_superuser=False, role="user")

    with pytest.raises(HTTPException) as error:
        _authorize_send_target(SimpleNamespace(), user, integration, None)

    assert error.value.status_code == 403


def test_shared_llm_integration_can_be_used_by_job_user():
    integration = SimpleNamespace(
        type=IntegrationType.SOFTNIX_GENAI,
        status=IntegrationStatus.ACTIVE,
        user_id=uuid4(),
    )
    user = SimpleNamespace(id=uuid4(), is_superuser=False, role="user")

    _authorize_send_target(SimpleNamespace(), user, integration, None)


@pytest.mark.asyncio
async def test_test_llm_uses_saved_key_when_frontend_sends_masked_value(monkeypatch):
    integration_id = uuid4()
    integration = SimpleNamespace(
        id=integration_id,
        type=IntegrationType.SOFTNIX_GENAI,
        status=IntegrationStatus.ACTIVE,
        user_id=uuid4(),
        config=_normalize_softnix_config(
            "softnix_genai",
            {"apiKey": "saved-key", "model": "gpt-5.5"},
        ),
    )
    user = SimpleNamespace(id=uuid4(), is_superuser=False, role="user")
    monkeypatch.setattr(
        integrations_endpoint.crud_integration,
        "get",
        lambda **_kwargs: integration,
    )
    monkeypatch.setattr(
        integrations_endpoint,
        "_call_llm_text",
        lambda **_kwargs: ("ok", "chat"),
    )

    result = await integrations_endpoint.test_llm(
        LLMTestRequest(integrationId=integration_id, model="gpt-5.5"),
        db=SimpleNamespace(),
        current_user=user,
    )

    assert result.output == "Success via chat: ok"
