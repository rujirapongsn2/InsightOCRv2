from types import SimpleNamespace

import app.api.v1.endpoints.ai_settings as ai_settings_endpoint
import app.api.v1.endpoints.integrations as integrations_endpoint
from app.models.integration import IntegrationType
from app.services.llm_provider_capabilities import integration_supports_tool_calling


def test_saving_provider_automatically_records_supported_agent_tools(monkeypatch):
    setting = SimpleNamespace(
        is_active=True,
        provider_type="openai_compatible",
        api_url="https://provider.example/v1",
        api_key="test-key",
        supports_tool_calling=False,
        agent_tools_checked_at=None,
        agent_tools_verification_error=None,
    )
    monkeypatch.setattr(ai_settings_endpoint, "_verify_native_tool_calling", lambda _setting: None)

    ai_settings_endpoint._automatically_verify_agent_tools(setting)

    assert setting.supports_tool_calling is True
    assert setting.agent_tools_checked_at is not None
    assert setting.agent_tools_verification_error is None


def test_saving_text_only_provider_keeps_llm_available_with_a_reason(monkeypatch):
    setting = SimpleNamespace(
        is_active=True,
        provider_type="openai_compatible",
        api_url="https://provider.example/v1",
        api_key="test-key",
        supports_tool_calling=True,
        agent_tools_checked_at=None,
        agent_tools_verification_error=None,
    )
    monkeypatch.setattr(
        ai_settings_endpoint,
        "_verify_native_tool_calling",
        lambda _setting: (_ for _ in ()).throw(ValueError("Provider did not return a native tool call")),
    )

    ai_settings_endpoint._automatically_verify_agent_tools(setting)

    assert setting.supports_tool_calling is False
    assert setting.agent_tools_verification_error == "Provider did not return a native tool call"


def test_saving_llm_integration_automatically_records_agent_capability(monkeypatch):
    integration = SimpleNamespace(
        type=IntegrationType.SOFTNIX_GENAI,
        config={
            "apiKey": "test-key",
            "baseUrl": "https://genai.example/openai",
            "model": "test-model",
        },
    )
    monkeypatch.setattr(integrations_endpoint, "_verify_native_tool_calling", lambda **_kwargs: None)

    integrations_endpoint._automatically_verify_agent_tools(integration)

    verification = integration.config["agentToolsVerification"]
    assert verification["verifiedAt"] == verification["checkedAt"]
    assert integration_supports_tool_calling(integration) is True


def test_saving_text_only_llm_integration_records_failure_without_raising(monkeypatch):
    integration = SimpleNamespace(
        type=IntegrationType.LLM,
        config={"apiKey": "test-key", "baseUrl": "https://provider.example/v1", "model": "test-model"},
    )
    monkeypatch.setattr(
        integrations_endpoint,
        "_verify_native_tool_calling",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("Native tools are unsupported")),
    )

    integrations_endpoint._automatically_verify_agent_tools(integration)

    verification = integration.config["agentToolsVerification"]
    assert verification["error"] == "Native tools are unsupported"
    assert integration_supports_tool_calling(integration) is False
