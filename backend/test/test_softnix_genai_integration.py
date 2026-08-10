from types import SimpleNamespace

from app.api.v1.endpoints.integrations import _is_llm_integration, _normalize_llm_base_url
from app.models.integration import IntegrationType
from app.schemas.integration import IntegrationCreate


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
