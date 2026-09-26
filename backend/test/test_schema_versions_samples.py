"""Schema versions and the stored test set, on an in-memory database."""
import asyncio
import json
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers

import importlib
import pkgutil

import app.models

# Register every model so relationship("User") etc. can configure. (Importing
# app.main would run migrations against the configured database.)
for _module in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_module.name}")

from app.models.schema import DocumentSchema, SchemaSample, SchemaVersion
from app.services import schema_versions


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    tables = [DocumentSchema.__table__, SchemaVersion.__table__, SchemaSample.__table__]
    DocumentSchema.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_schema(db, fields):
    schema = DocumentSchema(id=uuid4(), name="Invoice", document_type="invoice", fields=fields)
    db.add(schema)
    db.flush()
    return schema


def test_versions_are_created_only_when_fields_change(db):
    schema = make_schema(db, [{"name": "invoice_no", "type": "text"}])
    first = schema_versions.ensure_current_version(db, schema, note="Created")
    again = schema_versions.ensure_current_version(db, schema)
    assert (first.version, again.id, schema.current_version) == (1, first.id, 1)

    schema.fields = [{"name": "invoice_no", "type": "text"}, {"name": "total", "type": "currency"}]
    second = schema_versions.ensure_current_version(db, schema, note="Edited")
    assert (second.version, schema.current_version) == (2, 2)
    assert [f["name"] for f in db.get(SchemaVersion, first.id).fields] == ["invoice_no"]


def test_document_records_the_version_used(db):
    schema = make_schema(db, [{"name": "invoice_no", "type": "text"}])
    document = SimpleNamespace(id="d1", schema_version_id=None)
    schema_versions.record_document_version(db, document, schema)
    assert document.schema_version_id == schema_versions.latest_version(db, schema.id).id


def test_version_failure_never_blocks_mapping():
    document = SimpleNamespace(id="d1", schema_version_id=None)
    schema_versions.record_document_version(None, document, SimpleNamespace(id="s", fields=[]))
    assert document.schema_version_id is None


class FakeStorage:
    def __init__(self):
        self.files, self.deleted = {}, []

    def upload_file(self, file_obj, destination_path, content_type=None):
        self.files[destination_path] = file_obj.read()
        return destination_path

    def delete_file(self, path):
        self.deleted.append(path)
        self.files.pop(path, None)


ADMIN = SimpleNamespace(id=uuid4(), role="admin", is_superuser=True)


def upload(name, data=b"%PDF-1.4 sample"):
    return UploadFile(file=BytesIO(data), filename=name, headers=Headers({"content-type": "application/pdf"}))


@pytest.fixture
def queued(monkeypatch):
    """Automatic test runs requested by endpoints (never sent to the real broker)."""
    calls = []
    monkeypatch.setattr("app.tasks.schema_studio_tasks.queue_auto_test",
                        lambda schema_id, version, trigger: calls.append((str(schema_id), version, trigger)) or True)
    return calls


@pytest.fixture
def storage(monkeypatch, queued):
    fake = FakeStorage()
    monkeypatch.setattr("app.services.storage.get_storage_service", lambda: fake)
    monkeypatch.setattr("app.api.v1.endpoints.schemas.log_activity", lambda **kwargs: None)
    return fake


def test_samples_need_consent_and_keep_cached_text_and_confirmed_values(db, storage, monkeypatch, queued):
    from app.api.v1.endpoints import schemas as ep
    from app.services import schema_studio

    schema = make_schema(db, [{"name": "invoice_no", "type": "text"}, {"name": "total", "type": "currency"}])
    db.commit()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ep.store_schema_samples(db=db, schema_id=str(schema.id), files=[upload("a.pdf")],
                                            expected="[]", session_id=None, consent=False, current_user=ADMIN))
    assert exc.value.status_code == 422 and not storage.files

    monkeypatch.setattr(schema_studio, "load_samples",
                        lambda user_id, session_id: [{"filename": "a.pdf", "text": "Invoice No: INV-1"}])
    out = asyncio.run(ep.store_schema_samples(
        db=db, schema_id=str(schema.id), files=[upload("a.pdf")],
        expected=json.dumps([{"invoice_no": "INV-1", "unknown": "x"}]), session_id="a" * 32, consent=True,
        current_user=ADMIN))
    row = db.query(SchemaSample).one()
    assert row.text == "Invoice No: INV-1"
    assert row.expected == {"invoice_no": "INV-1"}
    assert row.storage_path.startswith(f"schema-samples/{schema.id}/") and row.storage_path in storage.files
    assert row.expires_at is not None
    assert out[0]["confirmed_fields"] == ["invoice_no"]
    assert queued == [(str(schema.id), schema.current_version, "samples_added")]


def test_deleting_a_sample_removes_its_file(db, storage):
    from app.api.v1.endpoints import schemas as ep

    schema = make_schema(db, [{"name": "invoice_no", "type": "text"}])
    row = SchemaSample(id=uuid4(), schema_id=schema.id, filename="a.pdf", storage_path="schema-samples/x/a.pdf",
                       text="t", expected={})
    db.add(row)
    db.commit()
    ep.delete_schema_sample(db=db, schema_id=str(schema.id), sample_id=str(row.id), current_user=ADMIN)
    assert storage.deleted == ["schema-samples/x/a.pdf"] and db.query(SchemaSample).count() == 0


def test_purge_removes_only_expired_samples(db, storage, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from app.tasks import maintenance_tasks

    schema = make_schema(db, [])
    now = datetime.now(timezone.utc)
    db.add_all([
        SchemaSample(id=uuid4(), schema_id=schema.id, filename="old.pdf", storage_path="p/old", text="t",
                     expected={}, expires_at=now - timedelta(days=1)),
        SchemaSample(id=uuid4(), schema_id=schema.id, filename="new.pdf", storage_path="p/new", text="t",
                     expected={}, expires_at=now + timedelta(days=10)),
    ])
    db.commit()
    monkeypatch.setattr(maintenance_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    maintenance_tasks.purge_expired_schema_samples.run()
    assert storage.deleted == ["p/old"]
    assert [row.filename for row in db.query(SchemaSample).all()] == ["new.pdf"]


def test_confirmed_values_can_be_replaced_for_known_fields_only(db, storage):
    from app.api.v1.endpoints import schemas as ep

    schema = make_schema(db, [{"name": "invoice_no", "type": "text"}])
    row = SchemaSample(id=uuid4(), schema_id=schema.id, filename="a.pdf", storage_path="p/a", text="t",
                       expected={"invoice_no": "old"})
    db.add(row)
    db.commit()
    out = ep.update_schema_sample_expected(db=db, schema_id=str(schema.id), sample_id=str(row.id),
                                           payload=ep.SampleExpectedUpdate(expected={"invoice_no": "INV-1", "x": 1}),
                                           current_user=ADMIN)
    assert db.get(SchemaSample, row.id).expected == {"invoice_no": "INV-1"}
    assert out["confirmed_fields"] == ["invoice_no"]


def test_stale_job_copy_records_the_matching_version_without_moving_current(db):
    schema = make_schema(db, [{"name": "invoice_no", "type": "text"}])
    v1 = schema_versions.ensure_current_version(db, schema)
    job_copy = SimpleNamespace(id=schema.id, fields=[{"name": "invoice_no", "type": "text"}], current_version=1)

    schema.fields = [{"name": "invoice_no", "type": "text"}, {"name": "total", "type": "currency"}]
    schema_versions.ensure_current_version(db, schema, note="Edited while the job ran")
    db.commit()

    document = SimpleNamespace(id="d1", schema_version_id=None)
    schema_versions.record_document_version(db, document, job_copy)
    assert document.schema_version_id == v1.id
    assert db.query(SchemaVersion).filter(SchemaVersion.schema_id == schema.id).count() == 2
    assert db.get(DocumentSchema, schema.id).current_version == 2


def test_test_set_results_keep_the_version_that_was_tested(db, monkeypatch):
    from app.tasks import schema_studio_tasks as tasks

    schema = make_schema(db, [{"name": "invoice_no", "type": "text"}])
    row = SchemaSample(id=uuid4(), schema_id=schema.id, filename="a.pdf", storage_path="p/a", text="t", expected={})
    db.add(row)
    schema.current_version = 5
    db.commit()
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    schema_versions.ensure_current_version(db, schema)
    tasks._save_last_runs(str(schema.id), [{"sample_id": row.id, "report": {"engine": "llm"},
                                            "comparison": {"checked": 1, "matched": 1,
                                                           "fields": {"invoice_no": {"match": True}}}}], 1,
                          None, "schema_change")
    assert db.get(SchemaSample, row.id).last_run["schema_version"] == 1
    run = schema_versions.latest_version(db, schema.id).test_runs[-1]
    assert (run["engine"], run["trigger"], run["fields"]) == ("llm", "schema_change",
                                                               {"invoice_no": {"checked": 1, "matched": 1}})


def test_applying_review_suggestions_creates_a_version_and_retests(db, storage, queued):
    from app.api.v1.endpoints import schemas as ep

    schema = make_schema(db, [{"name": "po_number", "type": "text", "required": True}])
    schema_versions.ensure_current_version(db, schema)
    db.commit()
    payload = ep.SchemaImprovementApply(changes=[
        {"field": "po_number", "kind": "add_labels", "labels": ["PO No"]},
        {"field": "po_number", "kind": "make_optional"},
    ])
    out = ep.apply_schema_improvements(db=db, schema_id=str(schema.id), payload=payload, current_user=ADMIN)
    field = out.fields[0]
    assert field["validation_rules"]["source_labels"] == ["PO No"] and field["required"] is False
    assert out.current_version == 2
    assert queued == [(str(schema.id), 2, "review_suggestions")]
    with pytest.raises(HTTPException) as exc:
        ep.apply_schema_improvements(db=db, schema_id=str(schema.id), current_user=ADMIN,
                                     payload=ep.SchemaImprovementApply(changes=[{"field": "gone", "kind": "make_optional"}]))
    assert exc.value.status_code == 422


class FakeRedis:
    def __init__(self, store):
        self.store = store

    def set(self, key, value, ex=None):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)

    def close(self):
        pass


@pytest.mark.parametrize("expected_version,marker_token,runs", [(1, "t1", 1), (0, "t1", 0), (1, "newer", 0)])
def test_automatic_test_runs_only_on_the_version_it_was_queued_for(db, monkeypatch, expected_version, marker_token, runs):
    import redis
    from app.tasks import schema_studio_tasks as tasks

    schema = make_schema(db, [{"name": "invoice_no", "type": "text"}, {"name": "box", "type": "text",
                                                                        "locator": {"page": 1}}])
    schema_versions.ensure_current_version(db, schema)
    db.add_all([
        SchemaSample(id=uuid4(), schema_id=schema.id, filename="a.pdf", storage_path="p/a", text="t",
                     expected={"invoice_no": "INV-1"}),
        SchemaSample(id=uuid4(), schema_id=schema.id, filename="b.pdf", storage_path="p/b", text="t",
                     expected={"removed_field": "x"}),
    ])
    db.commit()
    store = {tasks.auto_test_key(schema.id): json.dumps({"version": expected_version, "token": marker_token})}
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: FakeRedis(store))
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    calls = []
    monkeypatch.setattr(tasks, "run_schema_samples_task", lambda *args: calls.append(args))

    tasks.auto_test_schema_task.run(str(schema.id), "schema_change", expected_version, "t1")

    assert len(calls) == runs
    if runs:
        _user, _run, samples, fields, engine, schema_id, version, trigger = calls[0]
        assert [sample["filename"] for sample in samples] == ["a.pdf"]  # b.pdf has no current confirmations
        assert [field["name"] for field in fields] == ["invoice_no"]  # fixed-position fields need the page image
        assert (engine, version, trigger) == (None, 1, "schema_change")
    # A newer request keeps its marker, so the Versions tab keeps showing it as running.
    assert bool(store) == (marker_token == "newer")


def test_a_burst_of_requests_runs_once(db, monkeypatch):
    import redis
    from app.tasks import schema_studio_tasks as tasks

    store, queued_tasks = {}, []
    monkeypatch.setattr(redis, "from_url", lambda *args, **kwargs: FakeRedis(store))
    monkeypatch.setattr(tasks.auto_test_schema_task, "apply_async", lambda args, **kwargs: queued_tasks.append(args))
    schema_id = uuid4()
    for trigger in ("samples_added", "samples_added", "engine_change"):
        assert tasks.queue_auto_test(schema_id, 1, trigger)
    calls = []
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(tasks, "run_schema_samples_task", lambda *args: calls.append(args))
    make_schema(db, [{"name": "invoice_no", "type": "text"}]).id = schema_id
    db.add(SchemaSample(id=uuid4(), schema_id=schema_id, filename="a.pdf", storage_path="p/a", text="t",
                        expected={"invoice_no": "INV-1"}))
    db.commit()
    for args in queued_tasks:
        tasks.auto_test_schema_task.run(*args)
    assert len(calls) == 1 and calls[0][-1] == "engine_change"
    assert store == {}


@pytest.mark.parametrize("extracted,detail", [(ValueError("no pages"), "Could not read"), ("", "No text could be read")])
def test_unreadable_samples_are_rejected_with_a_clear_message(db, storage, monkeypatch, extracted, detail):
    from app.api.v1.endpoints import schemas as ep

    def fake_extract(path):
        if isinstance(extracted, Exception):
            raise extracted
        return SimpleNamespace(markdown=extracted)

    monkeypatch.setattr(ep, "_extract_schema_sample_in_worker", fake_extract)
    schema = make_schema(db, [{"name": "invoice_no", "type": "text"}])
    db.commit()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ep.store_schema_samples(db=db, schema_id=str(schema.id), files=[upload("scan.pdf")],
                                            expected="[]", session_id=None, consent=True, current_user=ADMIN))
    assert exc.value.status_code == 422 and detail in exc.value.detail and "scan.pdf" in exc.value.detail
    assert db.query(SchemaSample).count() == 0 and not storage.files


def test_sample_list_separates_outdated_confirmations(db, storage):
    from app.api.v1.endpoints import schemas as ep

    schema = make_schema(db, [{"name": "invoice_number", "type": "text"}])
    db.add(SchemaSample(id=uuid4(), schema_id=schema.id, filename="a.pdf", storage_path="p/a", text="t",
                        expected={"invoice_no": "INV-1", "invoice_number": "INV-1"}))
    db.commit()
    sample = ep.list_schema_samples(db=db, schema_id=str(schema.id), current_user=ADMIN)["samples"][0]
    assert sample["confirmed_fields"] == ["invoice_number"] and sample["outdated_fields"] == ["invoice_no"]
