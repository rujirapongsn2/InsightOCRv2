"""'Test saved providers' skips engines nobody configured instead of reporting them as failed."""
import json
from types import SimpleNamespace

from app.tasks import document_tasks


class FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, key, value, ex=None):
        self.store[key] = value

    def close(self):
        pass


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def query(self, _model):
        return SimpleNamespace(first=lambda: SimpleNamespace())


def test_unconfigured_engines_are_skipped(monkeypatch):
    import app.services.field_mapping as fm

    redis = FakeRedis()
    monkeypatch.setattr(document_tasks.redis_lib, "from_url", lambda url: redis)
    monkeypatch.setattr(document_tasks, "SessionLocal", FakeSession)
    monkeypatch.setattr(fm, "softnix_structure_configured", lambda setting: True)
    monkeypatch.setattr(fm, "typesafe_is_configured", lambda setting: False)
    monkeypatch.setattr(fm, "llm_mapping_configured", lambda db, setting: False)
    called = []

    def fake_map_fields(text, schema, db, engine=None):
        called.append(engine)
        return {"reference": "MAP-42"}, {"attempts": [], "elapsed_seconds": 1,
                                         "fields": {"total": {"status": "failed", "reason": "No value"}}}

    monkeypatch.setattr(fm, "map_fields", fake_map_fields)
    document_tasks.test_mapping_providers_task.run("u", "r")

    result = json.loads(redis.store["mapping_test:u:r"])
    assert called == ["softnix"]
    assert [(c["engine"], c["passed"], c.get("skipped")) for c in result["checks"]] == [
        ("softnix", False, None), ("jev", None, True), ("llm", None, True)]
    assert result["checks"][0]["problems"] == [{"field": "total", "value": None, "status": "failed", "reason": "No value"}]
