"""Field Mapping workflow node tests (P0) — reuse map_fields contract."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import workflow_engine as we


def _doc(doc_id="d1", filename="a.pdf", ocr="Reference: R-9\nTotal: 30"):
    return SimpleNamespace(id=doc_id, filename=filename, ocr_text=ocr,
                           file_path="documents/j/d.pdf", uploaded_at=None)


def _schema(*fields):
    return SimpleNamespace(name="probe", fields=list(fields))


@pytest.fixture
def jev_ready(monkeypatch):
    monkeypatch.setattr(we, "_field_mapping_setting", lambda db: SimpleNamespace(
        mapping_engine="auto", typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key="k"))


def test_field_mapping_node_registered():
    node_type = next(n for n in we.NODE_TYPES if n["type"] == "field_mapping")
    names = [f["name"] for f in node_type["config_fields"]]
    assert "schema_id" in names and "engine" in names
    engines = next(f for f in node_type["config_fields"] if f["name"] == "engine")
    assert set(engines["options"]) == {"auto", "softnix", "jev", "llm", "fixed"}
    assert "field_mapping" in we.EXECUTORS


def test_requires_schema(monkeypatch):
    db = Mock()
    monkeypatch.setattr(we, "_field_mapping_setting", lambda db: None)
    with pytest.raises(we.NodeExecutionError, match="Schema"):
        we._exec_field_mapping(db, {"schema_id": "", "engine": "auto"}, {"_node_id": "n1"}, lambda m: None)


def test_unknown_engine_rejected(monkeypatch):
    db = Mock()
    monkeypatch.setattr(we, "_field_mapping_setting", lambda db: None)
    with pytest.raises(we.NodeExecutionError, match="engine"):
        we._exec_field_mapping(db, {"schema_id": "s", "engine": "gpt5"}, {"_node_id": "n1"}, lambda m: None)


def test_jev_without_typesafe_config_fails_clearly(monkeypatch):
    """engine=jev + TypeSafe not configured -> explicit failure (AC4)."""
    db = Mock()
    monkeypatch.setattr(we, "_field_mapping_setting", lambda db: SimpleNamespace(
        mapping_engine="auto", typesafe_endpoint=None, typesafe_api_key=None))
    # schema + doc setup would matter only after config check; provide minimal
    monkeypatch.setattr(we, "_field_mapping_schema", lambda db, sid: _schema({"name": "id", "type": "text"}))
    monkeypatch.setattr(we, "_field_mapping_documents", lambda db, cfg, ctx, limit: [_doc()])
    with pytest.raises(we.NodeExecutionError, match="TypeSafe"):
        we._exec_field_mapping(db, {"schema_id": "s", "engine": "jev"}, {"_node_id": "n1"}, lambda m: None)


def test_auto_prune_reports_skipped_routes(monkeypatch):
    """engine=auto with all engines unconfigured -> map_fields handles pruning; skipped surfaced in warnings."""
    db = Mock()
    monkeypatch.setattr(we, "_field_mapping_setting", lambda db: SimpleNamespace(
        mapping_engine="auto", typesafe_endpoint=None, typesafe_api_key=None))
    monkeypatch.setattr(we, "_field_mapping_schema", lambda db, sid: _schema({"name": "id", "type": "text"}))
    monkeypatch.setattr(we, "_field_mapping_documents", lambda db, cfg, ctx, limit: [_doc()])
    monkeypatch.setattr("app.services.field_mapping.map_fields", lambda *a, **k: (
        {"id": "R-9"},
        {"status": "failed", "engine": "auto",
         "attempts": [{"provider": "softnix", "status": "skipped", "category": "not_configured"},
                      {"provider": "jev", "status": "skipped", "category": "not_configured"},
                      {"provider": "llm", "status": "skipped", "category": "not_configured"}],
         "fields": {"id": {"status": "failed"}},
         "review_fields": [], "unresolved_fields": ["id"], "missing_fields": []},
    ))
    out = we._exec_field_mapping(db, {"schema_id": "s", "engine": "auto"}, {"_node_id": "n1"}, lambda m: None)
    assert out["count"] == 1
    assert sum("not_configured" in w for w in out["warnings"]) == 3
    assert out["provider"] == []


def test_stored_file_stays_available_during_mapping(monkeypatch, tmp_path):
    """Remote storage yields a temp file deleted on exit — it must exist while map_fields runs."""
    from contextlib import contextmanager
    import os

    db = Mock()
    monkeypatch.setattr(we, "_field_mapping_setting", lambda db: None)
    monkeypatch.setattr(we, "_field_mapping_schema", lambda db, sid: _schema({"name": "id", "type": "text"}))
    monkeypatch.setattr(we, "_field_mapping_documents", lambda db, cfg, ctx, limit: [_doc()])
    tmp_file = tmp_path / "downloaded.pdf"

    class FakeRemoteStorage:
        @contextmanager
        def get_local_path(self, path):
            tmp_file.write_bytes(b"%PDF")
            try:
                yield str(tmp_file)
            finally:
                os.remove(tmp_file)

    monkeypatch.setattr("app.services.storage.get_storage_service", lambda: FakeRemoteStorage())
    seen = {}

    def fake_map_fields(text, schema, db_, file_path, engine=None, field_names=None):
        seen["path"] = file_path
        seen["exists"] = os.path.exists(file_path)
        return ({"id": "R-9"}, {"status": "completed", "engine": "auto",
                                "attempts": [{"provider": "softnix", "status": "completed"}],
                                "fields": {}, "review_fields": [], "unresolved_fields": [], "missing_fields": []})

    monkeypatch.setattr("app.services.field_mapping.map_fields", fake_map_fields)
    out = we._exec_field_mapping(db, {"schema_id": "s", "engine": "auto"}, {"_node_id": "n1"}, lambda m: None)
    assert seen == {"path": str(tmp_file), "exists": True}
    assert not tmp_file.exists()
    assert out["provider"] == ["softnix"]


def test_success_outputs_values_and_review_fields(monkeypatch):
    db = Mock()
    monkeypatch.setattr(we, "_field_mapping_setting", lambda db: SimpleNamespace(
        mapping_engine="auto", typesafe_endpoint="https://api.typesafe.ai", typesafe_api_key="k"))
    monkeypatch.setattr(we, "_field_mapping_schema", lambda db, sid: _schema(
        {"name": "id", "type": "text"}, {"name": "total", "type": "currency"}))
    monkeypatch.setattr(we, "_field_mapping_documents", lambda db, cfg, ctx, limit: [_doc()])

    def fake_map_fields(text, schema, db_, file_path, engine=None, field_names=None):
        assert engine == "jev"
        return ({"id": "R-9"},
                {"status": "partial", "engine": "jev",
                 "attempts": [{"provider": "jev:jev-1.13.0", "status": "completed"}],
                 "fields": {"id": {"status": "source_matched", "provider": "jev:jev-1.13.0"},
                            "total": {"status": "needs_review", "jev_candidate": {"value": "30", "confidence": 0.5}}},
                 "review_fields": ["total"], "unresolved_fields": [], "missing_fields": ["total"],
                 "skipped_routes": []})

    monkeypatch.setattr("app.services.field_mapping.map_fields", fake_map_fields)
    out = we._exec_field_mapping(db, {"schema_id": "s", "engine": "jev"}, {"_node_id": "n1"}, lambda m: None)
    assert out["values"] == {"id": "R-9"}
    assert out["review_fields"] == ["total"]
    assert out["provider"] == ["jev:jev-1.13.0"]
    assert out["documents"][0]["fields"]["total"]["jev_candidate"]["value"] == "30"


def test_no_upstream_documents_fails(monkeypatch):
    db = Mock()
    monkeypatch.setattr(we, "_field_mapping_setting", lambda db: SimpleNamespace(
        mapping_engine="auto", typesafe_endpoint="e", typesafe_api_key="k"))
    monkeypatch.setattr(we, "_field_mapping_schema", lambda db, sid: _schema({"name": "id", "type": "text"}))
    monkeypatch.setattr(we, "_field_mapping_documents", lambda db, cfg, ctx, limit: [])
    with pytest.raises(we.NodeExecutionError, match="OCR"):
        we._exec_field_mapping(db, {"schema_id": "s", "engine": "auto"}, {"_node_id": "n1"}, lambda m: None)
