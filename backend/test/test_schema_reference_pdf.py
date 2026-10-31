"""Reference PDF HTTP contract with SQLite and isolated fake storage."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
import importlib
import pkgutil
from types import SimpleNamespace
from urllib.parse import quote
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader, PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models

for _module in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_module.name}")

from app.api import deps
from app.api.v1.endpoints import schemas as ep
from app.models.document import Document
from app.models.activity_log import ActivityLog
from app.models.job import Job
from app.models.schema import DocumentSchema, SchemaSample, SchemaVersion, SchemaReferenceDeletion, SchemaReferenceUpload


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(type_, compiler, **kwargs):
    return "JSON"


class FakeStorage:
    def __init__(self, directory):
        self.directory = directory
        self.files = {}
        self.content_types = {}
        self.deleted = []
        self.fail_delete = False
        self.fail_upload = False

    def upload_file(self, source, path, content_type=None):
        self.files[path] = source.read()
        self.content_types[path] = content_type
        if self.fail_upload:
            raise RuntimeError("storage upload failed")
        return path

    def delete_file(self, path):
        self.deleted.append(path)
        if self.fail_delete:
            raise RuntimeError("storage deletion failed")
        self.files.pop(path, None)

    def exists(self, path):
        return path in self.files

    @contextmanager
    def get_local_path(self, path):
        local = self.directory / "readback.pdf"
        local.write_bytes(self.files[path])
        yield str(local)


@pytest.fixture
def case(monkeypatch, tmp_path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    DocumentSchema.metadata.create_all(engine, tables=[
        DocumentSchema.__table__, SchemaVersion.__table__, SchemaSample.__table__,
        Document.__table__, Job.__table__,
        ActivityLog.__table__,
        SchemaReferenceDeletion.__table__,
        SchemaReferenceUpload.__table__,
    ])
    db = sessionmaker(bind=engine)()
    schema = DocumentSchema(id=uuid4(), name="Existing fixed schema", document_type="invoice", fields=[{
        "name": "number", "type": "text", "locator": {
            "type": "bbox", "page": 1, "x": 1, "y": 1, "width": 10, "height": 10,
        },
    }])
    db.add(schema)
    db.commit()
    schema_id = schema.id
    storage = FakeStorage(tmp_path)
    user = SimpleNamespace(id=uuid4(), role="admin", is_superuser=True, groups=[])
    app = FastAPI()
    app.include_router(ep.router, prefix="/schemas")

    def get_db():
        try:
            yield db
        finally:
            db.rollback()

    app.dependency_overrides[deps.get_db] = get_db
    app.dependency_overrides[deps.get_current_active_user] = lambda: user
    monkeypatch.setattr("app.services.storage.get_storage_service", lambda: storage)
    monkeypatch.setattr(ep, "log_activity", lambda **kwargs: None)

    def unexpected_extraction(*args, **kwargs):
        pytest.fail("Reference PDFs must never trigger extraction or OCR")

    monkeypatch.setattr(ep, "_extract_schema_sample_in_worker", unexpected_extraction)
    monkeypatch.setattr(ep, "extract_schema_sample", unexpected_extraction)
    monkeypatch.setattr(ep, "_queue_auto_test", unexpected_extraction)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(client=client, db=db, storage=storage, schema_id=schema_id,
                              url=f"/schemas/{schema_id}/reference-pdf", user=user)
    db.close()
    engine.dispose()


@pytest.fixture
def scanned_pdf():
    stream = BytesIO()
    Image.new("RGB", (100, 100), "white").save(stream, format="PDF")
    data = stream.getvalue()
    assert not PdfReader(BytesIO(data)).pages[0].extract_text()
    return data


def put(case, data, filename="reference.pdf", consent="true"):
    form = {} if consent is None else {"consent": consent}
    return case.client.put(case.url, data=form, files={"file": (filename, data, "application/pdf")})


@pytest.mark.parametrize("replacing", [False, True])
def test_interrupted_upload_is_reconciled_without_deleting_saved_reference(case, scanned_pdf, monkeypatch, replacing):
    if replacing:
        assert put(case, scanned_pdf, "saved.pdf").status_code == 200
    saved = case.db.get(DocumentSchema, case.schema_id).reference_pdf
    saved_paths = {saved["storage_path"]} if saved else set()
    upload = case.storage.upload_file

    def crash_after_upload(*args, **kwargs):
        upload(*args, **kwargs)
        raise SystemExit("Simulated worker exit after storage accepted the PDF")

    monkeypatch.setattr(case.storage, "upload_file", crash_after_upload)
    from starlette.datastructures import UploadFile
    with pytest.raises(SystemExit):
        ep.put_schema_reference_pdf(str(case.schema_id),
            UploadFile(file=BytesIO(scanned_pdf), filename="interrupted.pdf"), True, case.db, case.user)
    case.db.rollback()
    assert len(case.storage.files) == len(saved_paths) + 1
    assert case.db.get(DocumentSchema, case.schema_id).reference_pdf == saved

    from app.tasks import maintenance_tasks
    future = datetime.now(timezone.utc) + timedelta(hours=2)

    class FutureClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return future

    monkeypatch.setattr(maintenance_tasks, "datetime", FutureClock)
    monkeypatch.setattr(maintenance_tasks, "SessionLocal", lambda: case.db)
    maintenance_tasks.purge_deleted_schema_references()
    assert set(case.storage.files) == saved_paths, "An interrupted upload must remain discoverable for cleanup"
    assert case.db.get(DocumentSchema, case.schema_id).reference_pdf == saved


@pytest.mark.parametrize("consent", [None, "false"])
def test_explicit_consent_is_required(case, scanned_pdf, consent):
    assert put(case, scanned_pdf, consent=consent).status_code == 422
    assert not case.storage.files
    assert case.db.get(DocumentSchema, case.schema_id).reference_pdf is None


def test_scanned_pdf_round_trip_private_metadata_and_unicode_filename(case, scanned_pdf):
    filename = "ใบแจ้งหนี้.pdf"
    response = put(case, scanned_pdf, filename)
    assert response.status_code == 200, response.text
    metadata = response.json()
    assert set(metadata) == {"filename", "size", "uploaded_at"}
    assert metadata["filename"] == filename and metadata["size"] == len(scanned_pdf)
    assert metadata["uploaded_at"].endswith("+00:00")
    read = case.client.get(case.url)
    assert read.status_code == 200 and read.json() == metadata
    assert read.headers["cache-control"] == "private, no-store"
    file = case.client.get(case.url + "/file")
    assert file.status_code == 200 and file.content == scanned_pdf
    assert file.headers["content-type"] == "application/pdf"
    assert file.headers["cache-control"] == "private, no-store"
    assert "filename*=UTF-8''" + quote(filename) in file.headers["content-disposition"]
    assert file.headers["x-content-type-options"] == "nosniff"
    key = case.db.get(DocumentSchema, case.schema_id).reference_pdf["storage_path"]
    assert key.startswith(f"schema-references/{case.schema_id}/") and key.endswith(".pdf")
    assert case.storage.content_types[key] == "application/pdf"
    assert case.db.query(SchemaSample).count() == case.db.query(SchemaVersion).count() == 0
    generic = case.client.get("/schemas/")
    assert generic.status_code == 200
    assert "reference_pdf" not in generic.json()[0]
    assert key not in generic.text


@pytest.mark.parametrize("method,suffix", [("get", ""), ("get", "/file"), ("delete", "")])
def test_absent_reference_returns_404(case, method, suffix):
    assert getattr(case.client, method)(case.url + suffix).status_code == 404


def test_missing_schema_returns_404(case, scanned_pdf):
    case.url = f"/schemas/{uuid4()}/reference-pdf"
    assert put(case, scanned_pdf).status_code == 404
    assert case.client.get(case.url).status_code == 404
    assert case.client.get(case.url + "/file").status_code == 404
    assert case.client.delete(case.url).status_code == 404
    assert not case.storage.files


@pytest.mark.parametrize("role", ["user", "manager"])
def test_nonmanagers_cannot_access_reference(case, scanned_pdf, role):
    assert put(case, scanned_pdf).status_code == 200
    case.user.role, case.user.is_superuser = role, False
    assert put(case, scanned_pdf).status_code == 403
    assert case.client.get(case.url).status_code == 403
    assert case.client.get(case.url + "/file").status_code == 403
    assert case.client.delete(case.url).status_code == 403
    assert len(case.storage.files) == 1


def test_owner_manager_can_attach_to_existing_schema(case, scanned_pdf):
    schema = case.db.get(DocumentSchema, case.schema_id)
    schema.created_by = case.user.id
    case.db.commit()
    case.user.role, case.user.is_superuser = "manager", False
    assert put(case, scanned_pdf).status_code == 200
    assert case.client.get(case.url).status_code == 200
    assert case.client.get(case.url + "/file").content == scanned_pdf
    assert case.client.delete(case.url).status_code == 204


@pytest.mark.parametrize("data,filename,expected", [
    (b"", "empty.pdf", 422),
    (b"not a PDF", "fake.pdf", 422),
    (b"%PDF-1.4\nnot a document", "broken.pdf", 422),
    (b"%PDF-1.4\n", "not-pdf.txt", 415),
])
def test_invalid_files_are_rejected(case, data, filename, expected):
    assert put(case, data, filename).status_code == expected
    assert not case.storage.files


def test_zero_page_and_encrypted_pdfs_are_rejected(case):
    for encrypted in (False, True):
        writer = PdfWriter()
        if encrypted:
            writer.add_blank_page(width=100, height=100)
            writer.encrypt("secret")
        stream = BytesIO()
        writer.write(stream)
        assert put(case, stream.getvalue()).status_code == 422
    assert not case.storage.files


def test_oversize_rejected_before_storage(case, monkeypatch):
    monkeypatch.setattr(ep.settings, "MAX_UPLOAD_SIZE_MB", 1)
    assert put(case, b"%PDF-" + b"x" * (1024 * 1024)).status_code == 413
    assert not case.storage.files


def test_replacement_uses_new_scoped_key_and_cleans_old_after_commit(case, scanned_pdf, monkeypatch):
    assert put(case, scanned_pdf, "first.pdf").status_code == 200
    old = case.db.get(DocumentSchema, case.schema_id).reference_pdf.copy()
    original_commit = case.db.commit
    original_delete = case.storage.delete_file
    committed_path = old["storage_path"]

    def checked_commit():
        nonlocal committed_path
        original_commit()
        committed_path = case.db.get(DocumentSchema, case.schema_id).reference_pdf["storage_path"]

    def checked_delete(path):
        assert path == old["storage_path"]
        assert committed_path != old["storage_path"], "The replacement must be committed before removing the old PDF"
        assert len(case.storage.files) == 2
        original_delete(path)

    monkeypatch.setattr(case.db, "commit", checked_commit)
    monkeypatch.setattr(case.storage, "delete_file", checked_delete)
    response = put(case, scanned_pdf, "../../second.pdf")
    assert response.status_code == 200 and response.json()["filename"] == "second.pdf"
    current = case.db.get(DocumentSchema, case.schema_id).reference_pdf
    assert current["storage_path"] != old["storage_path"]
    assert current["storage_path"].startswith(f"schema-references/{case.schema_id}/")
    assert old["storage_path"] not in case.storage.files
    assert list(case.storage.files) == [current["storage_path"]]


def test_replacement_commit_failure_cleans_new_and_preserves_original(case, scanned_pdf, monkeypatch):
    assert put(case, scanned_pdf, "original.pdf").status_code == 200
    original = case.db.get(DocumentSchema, case.schema_id).reference_pdf.copy()

    def fail_commit():
        raise RuntimeError("database commit failed")

    monkeypatch.setattr(case.db, "commit", fail_commit)
    assert put(case, scanned_pdf, "replacement.pdf").status_code == 500
    assert case.db.get(DocumentSchema, case.schema_id).reference_pdf == original
    assert list(case.storage.files) == [original["storage_path"]]
    assert case.client.get(case.url).json()["filename"] == "original.pdf"
    assert case.client.get(case.url + "/file").content == scanned_pdf
    assert case.db.query(ActivityLog).count() == 1


def test_partial_storage_failure_cleans_new_and_preserves_original(case, scanned_pdf):
    assert put(case, scanned_pdf).status_code == 200
    original = case.db.get(DocumentSchema, case.schema_id).reference_pdf.copy()
    case.storage.fail_upload = True
    assert put(case, scanned_pdf).status_code == 500
    assert case.db.get(DocumentSchema, case.schema_id).reference_pdf == original
    assert list(case.storage.files) == [original["storage_path"]]


def test_invalid_replacement_keeps_original(case, scanned_pdf):
    assert put(case, scanned_pdf).status_code == 200
    original = case.db.get(DocumentSchema, case.schema_id).reference_pdf.copy()
    assert put(case, b"%PDF-corrupt").status_code == 422
    assert case.db.get(DocumentSchema, case.schema_id).reference_pdf == original
    assert list(case.storage.files) == [original["storage_path"]]


def test_cleanup_failure_is_durable_and_retried(case, scanned_pdf, monkeypatch):
    assert put(case, scanned_pdf).status_code == 200
    case.storage.fail_delete = True
    assert put(case, scanned_pdf, "replacement.pdf").status_code == 200
    assert case.client.get(case.url).json()["filename"] == "replacement.pdf"
    assert case.client.delete(case.url).status_code == 204
    assert case.client.get(case.url).status_code == 404
    assert case.db.query(SchemaReferenceDeletion).count() == 2
    assert len(case.storage.files) == 2
    from app.tasks import maintenance_tasks
    monkeypatch.setattr(maintenance_tasks, "SessionLocal", lambda: case.db)
    case.storage.fail_delete = False
    maintenance_tasks.purge_deleted_schema_references()
    assert case.db.query(SchemaReferenceDeletion).count() == 0
    assert not case.storage.files


def test_reference_delete_commit_failure_preserves_original(case, scanned_pdf, monkeypatch):
    assert put(case, scanned_pdf).status_code == 200
    original = case.db.get(DocumentSchema, case.schema_id).reference_pdf.copy()

    def fail_commit():
        raise RuntimeError("database commit failed")

    monkeypatch.setattr(case.db, "commit", fail_commit)
    assert case.client.delete(case.url).status_code == 500
    assert case.db.get(DocumentSchema, case.schema_id).reference_pdf == original
    assert list(case.storage.files) == [original["storage_path"]]
    assert case.db.query(ActivityLog).count() == 1


def test_delete_reference_clears_metadata_and_file(case, scanned_pdf):
    assert put(case, scanned_pdf).status_code == 200
    response = case.client.delete(case.url)
    assert response.status_code == 204 and not response.content
    assert not case.storage.files
    assert case.db.get(DocumentSchema, case.schema_id).reference_pdf is None
    assert case.client.get(case.url + "/file").status_code == 404


def test_schema_deletion_cleans_reference(case, scanned_pdf):
    assert put(case, scanned_pdf).status_code == 200
    response = case.client.delete(f"/schemas/{case.schema_id}")
    assert response.status_code == 200, response.text
    assert not case.storage.files
    assert case.db.get(DocumentSchema, case.schema_id) is None


def test_failed_schema_deletion_preserves_reference(case, scanned_pdf, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    assert put(case, scanned_pdf).status_code == 200
    original = case.db.get(DocumentSchema, case.schema_id).reference_pdf.copy()

    def fail_commit():
        raise IntegrityError("delete", {}, RuntimeError("foreign key constraint"))

    monkeypatch.setattr(case.db, "commit", fail_commit)
    assert case.client.delete(f"/schemas/{case.schema_id}").status_code == 409
    assert case.db.get(DocumentSchema, case.schema_id).reference_pdf == original
    assert list(case.storage.files) == [original["storage_path"]]


def test_missing_storage_file_returns_404(case, scanned_pdf):
    assert put(case, scanned_pdf).status_code == 200
    case.storage.files.clear()
    assert case.client.get(case.url + "/file").status_code == 404


def test_upload_and_delete_activity_is_transactional_and_contains_no_file_content(case, scanned_pdf):
    assert put(case, scanned_pdf, "private-reference.pdf").status_code == 200
    upload = case.db.query(ActivityLog).one()
    assert upload.user_id == case.user.id
    assert upload.action == ep.Actions.UPDATE_SCHEMA
    assert upload.resource_type == "schema" and upload.resource_id == case.schema_id
    assert upload.details == {"reference_pdf_action": "uploaded", "consent": True, "size": len(scanned_pdf)}
    assert case.client.delete(case.url).status_code == 204
    activities = case.db.query(ActivityLog).all()
    assert len(activities) == 2
    deletion = next(row for row in activities if row.id != upload.id)
    assert deletion.details == {"reference_pdf_action": "deleted"}
    assert deletion.user_id == case.user.id and deletion.resource_id == case.schema_id


def test_migration_adds_nullable_json_and_round_trips():
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import Column, MetaData, String, Table, inspect, text

    path = Path(__file__).parents[1] / "alembic" / "versions" / "0029_schema_reference_pdf.py"
    spec = importlib.util.spec_from_file_location("reference_pdf_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0028_confirmed_review_decision"
    engine = create_engine("sqlite://")
    table = Table("document_schemas", MetaData(), Column("id", String, primary_key=True))
    table.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(table.insert().values(id="old-schema"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        column = next(col for col in inspect(connection).get_columns(table.name) if col["name"] == "reference_pdf")
        assert column["nullable"]
        assert connection.execute(text("SELECT reference_pdf FROM document_schemas")).scalar() is None
        connection.execute(text("UPDATE document_schemas SET reference_pdf = :value"), {"value": '{"filename":"private.pdf"}'})
        with pytest.raises(RuntimeError, match="Remove reference PDFs"):
            migration.downgrade()
        connection.execute(text("UPDATE document_schemas SET reference_pdf = NULL"))
        connection.execute(text("INSERT INTO schema_reference_deletions (storage_path) VALUES ('pending.pdf')"))
        with pytest.raises(RuntimeError, match="pending storage cleanup"):
            migration.downgrade()
        connection.execute(text("DELETE FROM schema_reference_deletions"))
        migration.downgrade()
        assert "reference_pdf" not in {col["name"] for col in inspect(connection).get_columns(table.name)}
    engine.dispose()


def test_upload_intent_is_committed_before_storage_and_consumed_on_success(case, scanned_pdf, monkeypatch):
    upload = case.storage.upload_file

    def checked_upload(source, path, **kwargs):
        assert case.db.get(SchemaReferenceUpload, path) is not None
        # Rollback cannot remove a previously committed intent.
        case.db.rollback()
        assert case.db.get(SchemaReferenceUpload, path) is not None
        return upload(source, path, **kwargs)

    monkeypatch.setattr(case.storage, "upload_file", checked_upload)
    assert put(case, scanned_pdf).status_code == 200
    assert case.db.query(SchemaReferenceUpload).count() == 0


@pytest.mark.parametrize("commit_reached_database", [False, True])
def test_final_commit_failure_does_not_delete_a_published_pdf(case, scanned_pdf, monkeypatch, commit_reached_database):
    assert put(case, scanned_pdf, "old.pdf").status_code == 200
    old = case.db.get(DocumentSchema, case.schema_id).reference_pdf.copy()
    commit = case.db.commit
    calls = 0

    def interrupted_commit():
        nonlocal calls
        calls += 1
        if calls == 2:
            if commit_reached_database:
                commit()
            raise RuntimeError("Commit acknowledgement lost")
        commit()

    monkeypatch.setattr(case.db, "commit", interrupted_commit)
    assert put(case, scanned_pdf, "new.pdf").status_code == 500
    reference = case.db.get(DocumentSchema, case.schema_id).reference_pdf
    assert reference["filename"] == ("new.pdf" if commit_reached_database else "old.pdf")
    assert reference["storage_path"] in case.storage.files
    assert case.client.get(case.url + "/file").content == scanned_pdf
    assert case.db.query(SchemaReferenceUpload).count() == 0
    if commit_reached_database:
        assert case.db.query(SchemaReferenceDeletion).count() == 1
    else:
        assert set(case.storage.files) == {old["storage_path"]}


def test_cleanup_preserves_unexpired_and_published_uploads_and_retries_failures(case, scanned_pdf, monkeypatch):
    from app.tasks import maintenance_tasks
    monkeypatch.setattr(maintenance_tasks, "SessionLocal", lambda: case.db)
    now = datetime.now(timezone.utc)
    active_path = f"schema-references/{case.schema_id}/active.pdf"
    abandoned_path = f"schema-references/{case.schema_id}/abandoned.pdf"
    assert put(case, scanned_pdf).status_code == 200
    published_path = case.db.get(DocumentSchema, case.schema_id).reference_pdf["storage_path"]
    for path, deadline in [(active_path, now + timedelta(hours=1)),
                           (abandoned_path, now - timedelta(hours=1)),
                           (published_path, now - timedelta(hours=1))]:
        case.storage.files[path] = scanned_pdf
        case.db.add(SchemaReferenceUpload(storage_path=path, schema_id=case.schema_id, expires_at=deadline))
    case.db.commit()
    case.storage.fail_delete = True
    maintenance_tasks.purge_deleted_schema_references()
    assert case.db.get(SchemaReferenceUpload, active_path) is not None
    assert case.db.get(SchemaReferenceUpload, abandoned_path) is not None
    assert case.db.get(SchemaReferenceUpload, published_path) is None
    assert published_path not in case.storage.deleted
    case.storage.fail_delete = False
    maintenance_tasks.purge_deleted_schema_references()
    assert set(case.storage.files) == {active_path, published_path}
    assert case.db.query(SchemaReferenceUpload).count() == 1


def test_upload_intent_migration_refuses_to_discard_pending_cleanup():
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text

    path = Path(__file__).parents[1] / "alembic" / "versions" / "0030_schema_reference_uploads.py"
    spec = importlib.util.spec_from_file_location("reference_upload_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0029_schema_reference_pdf"
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        connection.execute(text("INSERT INTO schema_reference_uploads (storage_path, schema_id, expires_at) VALUES (:path, :schema, :expires)"),
                           {"path": "pending.pdf", "schema": uuid4().hex, "expires": datetime.now(timezone.utc)})
        with pytest.raises(RuntimeError, match="Finish pending reference PDF uploads"):
            migration.downgrade()
        connection.execute(text("DELETE FROM schema_reference_uploads"))
        migration.downgrade()
        assert "schema_reference_uploads" not in inspect(connection).get_table_names()
    engine.dispose()
