from types import SimpleNamespace

import pytest

from app.services import ai_suggestion_service
from app.services.ai_suggestion_service import AISuggestionService, _normalize_openai_base_url


def test_normalize_openai_base_url_accepts_base_or_full_endpoint():
    assert _normalize_openai_base_url("https://example.test/v1/") == "https://example.test/v1"
    assert _normalize_openai_base_url("https://example.test/v1/chat/completions") == "https://example.test/v1"


@pytest.mark.asyncio
async def test_openai_compatible_provider_uses_chat_completions(monkeypatch):
    calls = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"fields":[{"name":"invoice_number","type":"text","description":"Invoice number"}]}'
                        )
                    )
                ]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(ai_suggestion_service, "AsyncOpenAI", FakeClient)
    service = AISuggestionService(None)
    provider = SimpleNamespace(
        display_name="Neontron",
        provider_type="openai_compatible",
        api_url="https://openrouter.ai/api/v1",
        api_key="test-key",
        model="test-model",
    )
    monkeypatch.setattr(service, "_get_ai_settings", lambda provider_name=None: provider)

    result = await service.suggest_fields_from_ocr("Invoice No: INV-1", "invoice")

    assert result.suggested_fields[0].name == "invoice_number"
    assert calls["client"]["base_url"] == "https://openrouter.ai/api/v1"
    assert calls["model"] == "test-model"
    assert calls["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_openai_compatible_empty_response_is_actionable(monkeypatch):
    class FakeCompletions:
        async def create(self, **kwargs):
            return SimpleNamespace(choices=[])

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(ai_suggestion_service, "AsyncOpenAI", FakeClient)
    service = AISuggestionService(None)
    provider = SimpleNamespace(
        display_name="Neontron",
        provider_type="openai_compatible",
        api_url="https://openrouter.ai/api/v1",
        api_key="test-key",
        model="test-model",
    )
    monkeypatch.setattr(service, "_get_ai_settings", lambda provider_name=None: provider)

    with pytest.raises(ValueError, match="empty response"):
        await service.suggest_fields_from_ocr("Invoice No: INV-1", "invoice")
