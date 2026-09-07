from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.v1.endpoints import ai_settings


def _provider(**overrides):
    values = {
        "id": uuid4(),
        "name": "test-provider",
        "display_name": "Test Provider",
        "api_url": "https://provider.example/v1",
        "api_key": "test-secret",
        "model": "test-model",
        "provider_type": "openai_compatible",
        "is_active": True,
        "is_agent_provider": False,
        "supports_tool_calling": False,
        "agent_tools_checked_at": None,
        "agent_tools_verification_error": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _Db:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_provider_test_runs_core_checks_and_marks_agent_ready(monkeypatch):
    provider = _provider()
    db = _Db()

    async def fake_model_test(_setting):
        return 12

    class FakeSuggestions:
        def __init__(self, _db):
            pass

        async def suggest_fields_from_ocr(self, **_kwargs):
            return SimpleNamespace(suggested_fields=[SimpleNamespace(name="invoice_number")])

    monkeypatch.setattr(ai_settings, "_test_openai_model_response", fake_model_test)
    monkeypatch.setattr(ai_settings, "AISuggestionService", FakeSuggestions)
    monkeypatch.setattr(ai_settings, "_verify_native_tool_calling", lambda _setting: None)

    result = await ai_settings._test_provider(provider, db)

    assert result.success is True
    assert result.agent_ready is True
    assert [step.key for step in result.steps] == [
        "connection", "model_response", "schema_extraction", "tool_calling",
    ]
    assert all(step.status == "passed" for step in result.steps)
    assert provider.supports_tool_calling is True
    assert db.commits == 1


@pytest.mark.asyncio
async def test_provider_test_keeps_llm_success_when_tools_are_unavailable(monkeypatch):
    provider = _provider(is_agent_provider=True)
    db = _Db()

    async def fake_model_test(_setting):
        return 12

    class FakeSuggestions:
        def __init__(self, _db):
            pass

        async def suggest_fields_from_ocr(self, **_kwargs):
            return SimpleNamespace(suggested_fields=[SimpleNamespace(name="invoice_number")])

    def unavailable_tools(_setting):
        raise ValueError("native tools are not supported")

    monkeypatch.setattr(ai_settings, "_test_openai_model_response", fake_model_test)
    monkeypatch.setattr(ai_settings, "AISuggestionService", FakeSuggestions)
    monkeypatch.setattr(ai_settings, "_verify_native_tool_calling", unavailable_tools)

    result = await ai_settings._test_provider(provider, db)

    assert result.success is True
    assert result.agent_ready is False
    assert result.steps[-1].status == "unavailable"
    assert provider.supports_tool_calling is False
    assert provider.is_agent_provider is False
    assert db.commits == 1


@pytest.mark.asyncio
async def test_provider_test_stops_before_network_when_provider_is_inactive():
    result = await ai_settings._test_provider(_provider(is_active=False), _Db())

    assert result.success is False
    assert result.steps[0].key == "connection"
    assert result.steps[0].status == "failed"


@pytest.mark.asyncio
async def test_model_probe_requires_the_expected_live_response(monkeypatch):
    class FakeCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="wrong answer"))])

    class FakeClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(ai_settings, "AsyncOpenAI", FakeClient)

    with pytest.raises(ValueError, match="unexpected health-check"):
        await ai_settings._test_openai_model_response(_provider())


@pytest.mark.asyncio
async def test_model_probe_allows_reasoning_models_enough_output_tokens(monkeypatch):
    request = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            request.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content="\nINSIGHTDOC_PROVIDER_OK"),
            )])

    class FakeClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(ai_settings, "AsyncOpenAI", FakeClient)

    await ai_settings._test_openai_model_response(_provider())

    assert request["max_tokens"] == ai_settings.PROVIDER_HEALTH_CHECK_TOKEN_LIMIT
    assert request["max_tokens"] >= 128


@pytest.mark.asyncio
async def test_model_probe_reports_truncated_health_check(monkeypatch):
    class FakeCompletions:
        async def create(self, **_kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(content="INSIGHTDOC_PROVIDER"),
            )])

    class FakeClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(ai_settings, "AsyncOpenAI", FakeClient)

    with pytest.raises(ValueError, match="truncated"):
        await ai_settings._test_openai_model_response(_provider())


@pytest.mark.asyncio
async def test_provider_test_fails_when_insightdoc_extraction_fails(monkeypatch):
    provider = _provider()

    async def fake_model_test(_setting):
        return 12

    class FailingSuggestions:
        def __init__(self, _db):
            pass

        async def suggest_fields_from_ocr(self, **_kwargs):
            raise ValueError("invalid structured response")

    monkeypatch.setattr(ai_settings, "_test_openai_model_response", fake_model_test)
    monkeypatch.setattr(ai_settings, "AISuggestionService", FailingSuggestions)

    result = await ai_settings._test_provider(provider, _Db())

    assert result.success is False
    assert result.steps[-2].key == "schema_extraction"
    assert result.steps[-2].status == "failed"
    assert result.steps[-1].status == "skipped"
