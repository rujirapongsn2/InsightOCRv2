from types import SimpleNamespace
import hashlib
import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.tasks import document_tasks
from app.services import field_mapping
from app.api.v1.endpoints import documents

FIELDS = [{"name": "id", "type": "text"}, {"name": "total", "type": "number"}]


def document():
    return SimpleNamespace(id="doc", task_id="token", status="queued", schema_id="schema",
        file_path="file.pdf", ocr_text="original text", ocr_pages=[], extracted_data={"id": "old", "total": 10},
        reviewed_data={"id": "confirmed"}, review_decision="confirmed",
        extraction_metadata={"mapping_retry": {"prior_status": "reviewed"}}, processing_error=None)


def worker_db(monkeypatch, doc):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [doc, SimpleNamespace(id="schema", fields=FIELDS)]
    db.query.return_value.filter.return_value.update.return_value = 1
    factory = MagicMock()
    factory.return_value.__enter__.return_value = db
    monkeypatch.setattr(document_tasks, "SessionLocal", factory)
    storage = MagicMock()
    storage.get_local_path.return_value.__enter__.return_value = "file.pdf"
    monkeypatch.setattr(document_tasks, "get_storage_service", lambda: storage)
    return db


def test_retry_preserves_reviewed_data_and_unresolved_previous_values(monkeypatch):
    doc = document()
    worker_db(monkeypatch, doc)
    monkeypatch.setattr(field_mapping, "map_fields", lambda *a, **kw: (
        {"id": "new"}, {"fields": {"id": {"status": "source_matched"}}, "unresolved_fields": ["total"],
                        "source_hash": hashlib.sha256(doc.ocr_text.encode()).hexdigest(),
                        "schema_hash": hashlib.sha256(json.dumps(FIELDS, sort_keys=True).encode()).hexdigest()}))
    document_tasks.remap_document_task.run("doc", "token", "auto")
    assert doc.reviewed_data == {"id": "confirmed"}
    assert doc.review_decision == "confirmed"
    assert doc.ocr_text == "original text"
    assert doc.extracted_data == {"id": "new", "total": 10}
    assert doc.status == "reviewed"


def test_retry_failure_keeps_previous_mapping(monkeypatch):
    doc = document()
    worker_db(monkeypatch, doc)
    def fail(*a, **kw):
        raise TimeoutError("sensitive provider details")
    monkeypatch.setattr(field_mapping, "map_fields", fail)
    document_tasks.remap_document_task.run("doc", "token", "auto")
    assert doc.extracted_data == {"id": "old", "total": 10}
    assert doc.status == "reviewed"
    assert doc.extraction_metadata["mapping_retry"] == {"status": "failed", "category": "TimeoutError"}


def test_duplicate_delivery_does_not_start_mapping(monkeypatch):
    doc = document()
    db = worker_db(monkeypatch, doc)
    db.query.return_value.filter.return_value.update.return_value = 0
    mapper = MagicMock()
    monkeypatch.setattr(field_mapping, "map_fields", mapper)
    document_tasks.remap_document_task.run("doc", "token", "auto")
    mapper.assert_not_called()


def test_changed_source_rejects_stale_proposal(monkeypatch):
    doc = document()
    worker_db(monkeypatch, doc)
    monkeypatch.setattr(field_mapping, "map_fields", lambda *a, **kw: (
        {"id": "new"}, {"fields": {}, "unresolved_fields": [], "source_hash": "stale"}))
    document_tasks.remap_document_task.run("doc", "token", "auto")
    assert doc.extracted_data["id"] == "old"
    assert doc.extraction_metadata["mapping_retry"]["status"] == "failed"


def test_retry_endpoint_checks_document_access_before_dispatch(monkeypatch):
    doc = document()
    db = MagicMock()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = doc
    def deny(*a):
        raise HTTPException(403, "Not enough permissions")
    monkeypatch.setattr(documents, "ensure_document_access", deny)
    with pytest.raises(HTTPException) as exc:
        documents.retry_mapping("doc", documents.MappingRetryRequest(), db, object())
    assert exc.value.status_code == 403
    db.commit.assert_not_called()


def test_retry_endpoint_rejects_concurrent_processing(monkeypatch):
    doc = document()
    db = MagicMock()
    db.query.return_value.filter.return_value.with_for_update.return_value.first.return_value = doc
    monkeypatch.setattr(documents, "ensure_document_access", lambda *a: None)
    with pytest.raises(HTTPException) as exc:
        documents.retry_mapping("doc", documents.MappingRetryRequest(), db, object())
    assert exc.value.status_code == 409
