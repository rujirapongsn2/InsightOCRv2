from types import SimpleNamespace

from app.api.v1.endpoints.agent import _ai_settings_to_config, _build_agent_llm_config


def _setting(provider_type="openai_compatible"):
    return SimpleNamespace(
        name="default-provider",
        api_url="https://provider.example/v1",
        api_key="test-key",
        model="test-model",
        provider_type=provider_type,
        is_active=True,
        is_default=True,
        is_agent_provider=False,
    )


def test_ai_settings_config_preserves_openai_compatible_contract():
    config = _ai_settings_to_config(_setting(), "test")

    assert config == {
        "provider": "openai_compatible",
        "apiKey": "test-key",
        "baseUrl": "https://provider.example/v1",
        "model": "test-model",
        "source": "test",
    }


def test_ai_settings_config_preserves_completion_messages_contract():
    config = _ai_settings_to_config(_setting("completion_messages"), "test")

    assert config == {
        "provider": "completion_messages",
        "apiUrl": "https://provider.example/v1",
        "apiKey": "test-key",
        "model": "test-model",
        "source": "test",
    }


def test_default_provider_fallback_does_not_downgrade_openai_contract():
    setting = _setting()

    class Query:
        def __init__(self, result):
            self.result = result

        def filter(self, *_args):
            return self

        def first(self):
            return self.result

    class Db:
        def __init__(self):
            self.results = [None, setting]

        def query(self, _model):
            return Query(self.results.pop(0))

    conversation = SimpleNamespace(kind="document", integration_id=None)

    config = _build_agent_llm_config(Db(), conversation)

    assert config["provider"] == "openai_compatible"
    assert config["baseUrl"] == setting.api_url
    assert config["source"] == "fallback_ai_settings"
