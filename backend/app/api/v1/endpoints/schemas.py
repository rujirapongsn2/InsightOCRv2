import logging
import os
import tempfile
import json
import re
from typing import List, Any, Literal
from urllib.parse import urlparse, urlencode
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Response, status
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
import requests
from app.api import deps
from app.db.session import SessionLocal
from app.models.schema import DocumentSchema, SchemaSample, SchemaVersion
from app.models.document import Document
from app.models.job import Job
from app.models.setting import Setting
from app.schemas.schema import DocumentSchema as DocumentSchemaSchema
from app.schemas.schema import DocumentSchemaCreate, DocumentSchemaUpdate, SchemaField, _validate_field_names
from app.models.user import User
from app.api.permissions import can_manage_group_resource
from app.services import schema_studio, schema_versions
from app.services.schema_suggestion_service import SchemaSuggestionService
from app.services.anydoc_pipeline import (
    AnydocFallbackToLegacy,
    AnydocTerminalError,
    extract_schema_sample,
)
from app.services.anydoc_bbox import BboxLocatorError, extract_fixed_position_fields
from app.services.extraction_profiles import validate_extraction_profile
from app.core.config import settings
from app.utils.activity_logger import log_activity, Actions

router = APIRouter()
logger = logging.getLogger(__name__)

SCHEMA_PACKAGE_FORMAT = "insightdoc.schema-package"
SCHEMA_PACKAGE_VERSION = 1


def _validate_suggestion_upload(file: UploadFile) -> None:
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is required")

    extension = os.path.splitext(file.filename)[1].lower()
    allowed_extensions = {
        value.strip().lower()
        for value in settings.ALLOWED_UPLOAD_EXTENSIONS.split(",")
        if value.strip()
    }
    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type '{extension or 'unknown'}' is not allowed",
        )

    file.file.seek(0, os.SEEK_END)
    file_size = file.file.tell()
    file.file.seek(0)
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File is too large. Maximum is {settings.MAX_UPLOAD_SIZE_MB} MB",
        )
    if file_size == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Uploaded file is empty")


def _ensure_valid_extraction_profile(document_type: str | None, profile: str | None) -> str:
    try:
        return validate_extraction_profile(document_type, profile)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _schema_update_values(schema_in: DocumentSchemaUpdate, schema: DocumentSchema) -> dict[str, Any]:
    """Return normalized values for a schema update before writing them to the DB."""
    effective_document_type = schema_in.document_type or schema.document_type
    effective_profile = schema_in.extraction_profile or schema.extraction_profile or "anydoc_hybrid"
    normalized_profile = _ensure_valid_extraction_profile(effective_document_type, effective_profile)

    if hasattr(schema_in, "model_dump"):
        values = schema_in.model_dump(exclude_unset=True)
    else:  # pragma: no cover - compatibility with Pydantic v1
        values = schema_in.dict(exclude_unset=True)

    # A schema created before the extraction-profile migration may have a null
    # value. Normalize it while saving, so the API never silently falls back.
    values["extraction_profile"] = normalized_profile
    if "fields" in values:
        normalized_fields = []
        for field in values["fields"] or []:
            if hasattr(field, "model_dump"):
                normalized_fields.append(field.model_dump())
            elif hasattr(field, "dict"):  # pragma: no cover - Pydantic v1
                normalized_fields.append(field.dict())
            else:
                normalized_fields.append(field)
        values["fields"] = normalized_fields
    return values

def _normalize_role(role: str | None) -> str:
    if not role:
        return "user"
    return "manager" if role == "documents_admin" else role

def _ensure_can_manage(schema: DocumentSchema, current_user: User) -> None:
    if _can_manage_schema(schema, current_user):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions to manage this schema.",
    )


def _can_manage_schema(schema: DocumentSchema, current_user: User) -> bool:
    normalized = _normalize_role(current_user.role)
    is_admin = current_user.is_superuser or normalized == "admin"
    if is_admin:
        return True
    if normalized == "manager" and schema.created_by == current_user.id:
        return True
    if can_manage_group_resource(current_user, schema.creator):
        return True
    return False


def _ensure_can_create_schema(current_user: User) -> None:
    normalized = _normalize_role(current_user.role)
    if current_user.is_superuser or normalized in {"admin", "manager"}:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions to create schema.",
    )


def _extract_schema_sample_in_worker(file_path: str):
    """Run CPU and OCR work with a session owned by the worker thread."""
    worker_db = SessionLocal()
    try:
        return extract_schema_sample(file_path, worker_db)
    finally:
        worker_db.close()


def _extract_bbox_preview_in_worker(file_path: str, fields: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate BBox locators outside the async request loop."""
    from types import SimpleNamespace
    from app.services.field_mapping import map_fields
    values, report = map_fields("", SimpleNamespace(name="sample", fields=fields), None,
                                file_path, engine="fixed")
    return values, report["fields"]

@router.get("/", response_model=List[DocumentSchemaSchema])
def read_schemas(
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Retrieve schemas.
    Admin: all schemas
    Manager: read all, manage own
    User: read-only access to all schemas (no write actions allowed)
    """
    normalized = _normalize_role(current_user.role)
    is_admin = current_user.is_superuser or normalized == "admin"

    query = db.query(DocumentSchema)

    # New schemas have no updated_at until their first edit, so use created_at
    # as the initial activity timestamp.
    schemas = (
        query
        .order_by(
            func.coalesce(DocumentSchema.updated_at, DocumentSchema.created_at).desc(),
            DocumentSchema.id.desc(),
        )
        .offset(skip)
        .limit(limit)
        .all()
    )

    for schema in schemas:
        if schema.creator:
            schema.created_by_email = schema.creator.email
            schema.created_by_name = schema.creator.full_name
        schema.can_manage = _can_manage_schema(schema, current_user)

    return schemas

@router.post("/", response_model=DocumentSchemaSchema)
def create_schema(
    *,
    db: Session = Depends(deps.get_db),
    schema_in: DocumentSchemaCreate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Create new schema.
    Only Admins and Managers (documents_admin) can create schemas.
    """
    _ensure_can_create_schema(current_user)

    extraction_profile = _ensure_valid_extraction_profile(
        schema_in.document_type,
        schema_in.extraction_profile,
    )
    db_schema = DocumentSchema(
        name=schema_in.name,
        description=schema_in.description,
        document_type=schema_in.document_type,
        ocr_engine=schema_in.ocr_engine,
        extraction_profile=extraction_profile,
        fields=[field.dict() for field in schema_in.fields], # Store as JSON
        created_by=current_user.id,
    )
    db.add(db_schema)
    db.flush()
    schema_versions.ensure_current_version(db, db_schema, current_user.id, "Created")
    db.commit()
    db.refresh(db_schema)

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.CREATE_SCHEMA,
        resource_type="schema",
        resource_id=db_schema.id,
        details={"schema_name": db_schema.name, "document_type": db_schema.document_type}
    )

    return db_schema


# Sample text shown back to the browser for evidence highlighting.


@router.post("/suggest-from-file", status_code=status.HTTP_202_ACCEPTED)
async def suggest_schema_from_file(
    *,
    files: List[UploadFile] = File(default=[]),
    file: UploadFile | None = File(default=None),
    document_type: str | None = None,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Start reading one or more sample documents and suggesting schema fields.

    The request only stores the uploads. A worker then reads them (AnyDoc text
    layer; scanned pages use TesseractOCR and then the configured OCR fallback,
    which can take minutes), asks AI once for all samples and verifies the
    answer. Poll ``GET /schemas/sample-runs/{run_id}``: ``stage`` is
    ``reading`` then ``suggesting``; ``session_id`` and ``samples`` appear once
    the files are read, and ``result`` holds the suggested fields at the end.
    """
    from io import BytesIO
    from uuid import uuid4
    from app.services.storage import get_storage_service
    from app.tasks.maintenance_tasks import delete_schema_sample_files
    from app.tasks.schema_studio_tasks import RUN_TTL_SECONDS, extract_and_suggest_task, run_key, suggestion_state

    _ensure_can_create_schema(current_user)
    uploads = [upload for upload in ([file] if file else []) + list(files) if upload is not None]
    if not uploads:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Choose at least one file")
    if len(uploads) > settings.SCHEMA_SAMPLE_MAX_FILES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Upload up to {settings.SCHEMA_SAMPLE_MAX_FILES} sample files")
    for upload in uploads:
        _validate_suggestion_upload(upload)

    run_id = uuid4().hex
    storage = get_storage_service()
    stored: list[dict[str, Any]] = []
    try:
        for index, upload in enumerate(uploads):
            file_bytes = await upload.read()
            if not file_bytes:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{upload.filename} is empty")
            # Workers run in other containers, so the files go through object storage.
            path = f"schema-suggest-tmp/{run_id}/{index}{os.path.splitext(upload.filename or '')[1].lower()}"
            storage.upload_file(BytesIO(file_bytes), path, content_type=upload.content_type)
            stored.append({"path": path, "filename": upload.filename or f"sample-{index + 1}"})
        client = schema_studio._redis_client()
        try:
            client.set(run_key(current_user.id, run_id), json.dumps(suggestion_state(len(stored))), ex=RUN_TTL_SECONDS)
        finally:
            client.close()
        extract_and_suggest_task.delay(str(current_user.id), run_id, stored, document_type)
    except HTTPException:
        delete_schema_sample_files([item["path"] for item in stored])
        raise
    except Exception as exc:
        delete_schema_sample_files([item["path"] for item in stored])
        logger.exception("Could not queue schema suggestion")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="The suggestion service is unavailable. Try again shortly.") from exc
    return {
        "run_id": run_id,
        "total": len(stored),
        "sample_ttl_seconds": schema_studio.SAMPLE_TTL_SECONDS,
        "sample_retention_days": settings.SCHEMA_SAMPLE_RETENTION_DAYS,
    }


class SampleDryRunRequest(BaseModel):
    session_id: str
    fields: List[SchemaField]
    engine: Literal["auto", "softnix", "jev", "llm"] | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "SampleDryRunRequest":
        _validate_field_names(self.fields)
        return self


def _test_fields(fields: List[SchemaField]) -> list[dict[str, Any]]:
    # Fixed-position fields need the original file, which a test run on text cannot use.
    selected = [field.model_dump(exclude_none=True) for field in fields if not field.locator]
    if not selected:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Add at least one field to test")
    return selected


def _start_sample_run(user_id: Any, samples: list[dict[str, Any]], fields: list[dict[str, Any]],
                      engine: str | None, schema_id: str | None = None,
                      schema_version: int | None = None) -> dict[str, Any]:
    from uuid import uuid4
    from app.tasks.schema_studio_tasks import RUN_TTL_SECONDS, initial_state, run_key, run_schema_samples_task

    run_id = uuid4().hex
    try:
        # Written before queueing so a missing key later means "not found", not "not started yet".
        client = schema_studio._redis_client()
        try:
            client.set(run_key(user_id, run_id), json.dumps(initial_state(len(samples))), ex=RUN_TTL_SECONDS)
        finally:
            client.close()
        run_schema_samples_task.delay(str(user_id), run_id, samples, fields, engine, schema_id, schema_version)
    except Exception as exc:
        logger.exception("Could not queue schema test run")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="The test service is unavailable. Try again shortly.") from exc
    return {"run_id": run_id, "total": len(samples)}


@router.post("/sample-dry-run", status_code=status.HTTP_202_ACCEPTED)
def dry_run_schema_on_samples(
    *,
    payload: SampleDryRunRequest,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Start extracting the draft fields from the uploaded samples with the real engines.

    Poll ``GET /schemas/sample-runs/{run_id}`` for progress and results.
    """
    _ensure_can_create_schema(current_user)
    fields = _test_fields(payload.fields)
    try:
        samples = schema_studio.load_samples(current_user.id, payload.session_id)
    except Exception as exc:
        logger.exception("Could not read schema samples for dry run")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="The test service is unavailable. Try again shortly.") from exc
    if not samples:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="The samples have expired. Upload the files again to test.")
    run_samples = [{"index": index, "filename": sample.get("filename"), "text": sample.get("text", "")}
                   for index, sample in enumerate(samples)]
    return _start_sample_run(current_user.id, run_samples, fields, payload.engine)


@router.get("/sample-runs/{run_id}")
def read_sample_run(run_id: str, current_user: User = Depends(deps.get_current_active_user)) -> Any:
    from app.tasks.schema_studio_tasks import run_key

    if not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Test run not found")
    try:
        client = schema_studio._redis_client()
        try:
            raw = client.get(run_key(current_user.id, run_id))
        finally:
            client.close()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="The test service is unavailable. Try again shortly.") from exc
    if not raw:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="This test run was not found or has expired. Run the test again.")
    return json.loads(raw)


def _parse_id(value: str, what: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found") from exc


def _get_managed_schema(db: Session, schema_id: str, current_user: User) -> DocumentSchema:
    schema = db.query(DocumentSchema).filter(DocumentSchema.id == _parse_id(schema_id, "Schema")).first()
    if not schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema not found")
    _ensure_can_manage(schema, current_user)
    return schema


def _sample_summary(row: SchemaSample, field_names: set[str] | None = None) -> dict[str, Any]:
    confirmed = sorted((row.expected or {}).keys())
    return {
        "id": str(row.id),
        "filename": row.filename,
        "mime_type": row.mime_type,
        # Values confirmed for fields later renamed or removed are not tested.
        "confirmed_fields": [name for name in confirmed if field_names is None or name in field_names],
        "outdated_fields": [name for name in confirmed if field_names is not None and name not in field_names],
        "last_run": row.last_run,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
    }


@router.post("/{schema_id}/samples", status_code=status.HTTP_201_CREATED)
async def store_schema_samples(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    files: List[UploadFile] = File(...),
    expected: str = Form("[]"),
    session_id: str | None = Form(None),
    consent: bool = Form(False),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Keep sample files as the schema's test set.

    Requires explicit consent: files and their text are stored for
    SCHEMA_SAMPLE_RETENTION_DAYS and are visible only to schema managers.
    ``expected`` is a JSON list aligned with ``files``: confirmed values per field.
    """
    from datetime import datetime, timedelta, timezone
    from io import BytesIO
    from uuid import uuid4
    from app.services.storage import get_storage_service

    schema = _get_managed_schema(db, schema_id, current_user)
    if not consent:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Confirm that the sample files may be stored before keeping them")
    existing = db.query(SchemaSample).filter(SchemaSample.schema_id == schema.id).count()
    if not files or existing + len(files) > settings.SCHEMA_SAMPLE_MAX_FILES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"A schema can keep up to {settings.SCHEMA_SAMPLE_MAX_FILES} sample files")
    try:
        expected_values = json.loads(expected or "[]")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid confirmed values") from exc
    if not isinstance(expected_values, list):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid confirmed values")
    field_names = {field.get("name") for field in schema.fields or []}

    cached: list[dict[str, Any]] = []
    if session_id:
        try:
            cached = schema_studio.load_samples(current_user.id, session_id) or []
        except Exception:  # noqa: BLE001 — fall back to reading the files again
            cached = []

    storage = get_storage_service()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.SCHEMA_SAMPLE_RETENTION_DAYS)
    stored_paths: list[str] = []
    rows: list[SchemaSample] = []
    try:
        for index, upload in enumerate(files):
            _validate_suggestion_upload(upload)
            data = await upload.read()
            cached_sample = cached[index] if index < len(cached) else None
            if cached_sample and cached_sample.get("filename") == upload.filename:
                text = cached_sample.get("text", "")
            else:
                with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(upload.filename)[1]) as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name
                try:
                    text = (await run_in_threadpool(_extract_schema_sample_in_worker, tmp_path)).markdown
                except (AnydocFallbackToLegacy, AnydocTerminalError, ValueError) as exc:
                    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                        detail=f"Could not read {upload.filename}: {exc}") from exc
                finally:
                    os.unlink(tmp_path)
            # A sample without text would fail every future test run.
            if not (text or "").strip():
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    detail=f"No text could be read from {upload.filename}, so it cannot be used as a test sample")
            path = f"schema-samples/{schema.id}/{uuid4().hex}{os.path.splitext(upload.filename)[1].lower()}"
            storage.upload_file(BytesIO(data), path, content_type=upload.content_type)
            stored_paths.append(path)
            confirmed = expected_values[index] if index < len(expected_values) and isinstance(expected_values[index], dict) else {}
            rows.append(SchemaSample(
                schema_id=schema.id, filename=upload.filename, mime_type=upload.content_type,
                storage_path=path, text=text,
                expected={name: value for name, value in confirmed.items() if name in field_names},
                created_by=current_user.id, expires_at=expires_at,
            ))
        db.add_all(rows)
        db.commit()
    except Exception:
        db.rollback()
        from app.tasks.maintenance_tasks import delete_schema_sample_files
        delete_schema_sample_files(stored_paths)
        raise
    log_activity(db=db, user_id=current_user.id, action=Actions.UPDATE_SCHEMA, resource_type="schema",
                 resource_id=schema.id, details={"schema_name": schema.name, "samples_stored": len(rows)})
    if any(row.expected for row in rows):
        _queue_auto_test(schema, schema.current_version, "samples_added")
    return [_sample_summary(row) for row in rows]


@router.get("/{schema_id}/samples")
def list_schema_samples(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    schema = _get_managed_schema(db, schema_id, current_user)
    rows = (db.query(SchemaSample).filter(SchemaSample.schema_id == schema.id)
            .order_by(SchemaSample.created_at).all())
    field_names = {field.get("name") for field in schema.fields or []}
    return {"retention_days": settings.SCHEMA_SAMPLE_RETENTION_DAYS,
            "samples": [_sample_summary(row, field_names) for row in rows]}


@router.delete("/{schema_id}/samples/{sample_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schema_sample(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    sample_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Response:
    from app.tasks.maintenance_tasks import delete_schema_sample_files

    schema = _get_managed_schema(db, schema_id, current_user)
    row = db.query(SchemaSample).filter(SchemaSample.id == _parse_id(sample_id, "Sample"),
                                        SchemaSample.schema_id == schema.id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sample not found")
    delete_schema_sample_files([row.storage_path])
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class SampleExpectedUpdate(BaseModel):
    expected: dict[str, Any]


@router.put("/{schema_id}/samples/{sample_id}/expected")
def update_schema_sample_expected(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    sample_id: str,
    payload: SampleExpectedUpdate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Replace the confirmed values of one stored sample (unknown field names are ignored)."""
    schema = _get_managed_schema(db, schema_id, current_user)
    row = db.query(SchemaSample).filter(SchemaSample.id == _parse_id(sample_id, "Sample"),
                                        SchemaSample.schema_id == schema.id).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sample not found")
    field_names = {field.get("name") for field in schema.fields or []}
    row.expected = {name: value for name, value in payload.expected.items() if name in field_names}
    db.commit()
    return _sample_summary(row)


class SampleRunRequest(BaseModel):
    engine: Literal["auto", "softnix", "jev", "llm"] | None = None


@router.post("/{schema_id}/samples/run", status_code=status.HTTP_202_ACCEPTED)
def run_schema_test_set(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    payload: SampleRunRequest,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Re-run the current fields on the stored samples and compare with confirmed values."""
    schema = _get_managed_schema(db, schema_id, current_user)
    rows = (db.query(SchemaSample).filter(SchemaSample.schema_id == schema.id)
            .order_by(SchemaSample.created_at).all())
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This schema has no test set yet")
    fields = _test_fields([SchemaField.model_validate(field) for field in schema.fields or []])
    version = schema_versions.ensure_current_version(db, schema, current_user.id)
    db.commit()
    samples = [{"index": index, "filename": row.filename, "sample_id": str(row.id)} for index, row in enumerate(rows)]
    return _start_sample_run(current_user.id, samples, fields, payload.engine, str(schema.id), version.version)


@router.get("/{schema_id}/versions")
def list_schema_versions(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    schema = db.query(DocumentSchema).filter(DocumentSchema.id == _parse_id(schema_id, "Schema")).first()
    if not schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema not found")
    rows = (db.query(SchemaVersion).filter(SchemaVersion.schema_id == schema.id)
            .order_by(SchemaVersion.version.desc()).all())
    history = schema_versions.version_test_history(rows)
    return {
        "current_version": schema.current_version,
        "auto_test": _auto_test_status(schema),
        "versions": [
            {
                "version": row.version,
                "note": row.note,
                "field_names": [field.get("name") for field in row.fields or []],
                "created_at": row.created_at,
                "created_by_name": row.creator.full_name if row.creator else None,
                "fields": row.fields,
                "test": history.get(row.version),
            }
            for row in rows
        ],
    }


def _queue_auto_test(schema: DocumentSchema, version: int | None, trigger: str) -> None:
    from app.tasks.schema_studio_tasks import queue_auto_test

    queue_auto_test(schema.id, version, trigger)


def _auto_test_status(schema: DocumentSchema) -> dict[str, Any]:
    """Whether an automatic test run is queued or running for this schema."""
    from app.tasks.schema_studio_tasks import auto_test_key

    status_info: dict[str, Any] = {"enabled": settings.SCHEMA_TEST_AUTO_RUN, "pending": False}
    try:
        client = schema_studio._redis_client()
        try:
            marker = client.get(auto_test_key(schema.id))
        finally:
            client.close()
    except Exception:  # noqa: BLE001 — status is informational
        return status_info
    if marker:
        status_info.update(pending=True, **{key: value for key, value in json.loads(marker).items()
                                             if key in {"trigger", "version"}})
    return status_info


@router.get("/{schema_id}/accuracy")
def read_schema_accuracy(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    days: int | None = Query(None, ge=1, le=3650),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Per-field accuracy of mapped values against what reviewers confirmed."""
    from app.services.schema_accuracy import schema_accuracy

    schema = _get_managed_schema(db, schema_id, current_user)
    return schema_accuracy(db, schema, days)


@router.get("/{schema_id}/improvements")
def read_schema_improvements(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    days: int | None = Query(None, ge=1, le=3650),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Schema changes suggested by reviewer corrections (labels, format rules, required flags)."""
    from app.services.schema_accuracy import suggest_improvements

    schema = _get_managed_schema(db, schema_id, current_user)
    result = suggest_improvements(db, schema, days)
    setting = db.query(Setting).first()
    # Labels are only read when the mapping engine is Auto.
    result["label_pass_active"] = (getattr(setting, "mapping_engine", None) or "auto") == "auto"
    return result


class SchemaImprovementChange(BaseModel):
    field: str
    kind: Literal["add_labels", "replace_pattern", "remove_pattern", "make_optional"]
    labels: list[str] | None = None
    pattern: str | None = None


class SchemaImprovementApply(BaseModel):
    changes: list[SchemaImprovementChange] = Field(..., min_length=1, max_length=50)


@router.post("/{schema_id}/improvements/apply", response_model=DocumentSchemaSchema)
def apply_schema_improvements(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    payload: SchemaImprovementApply,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Apply accepted suggestions as a new schema version, then re-run the test set."""
    from app.services.schema_accuracy import apply_improvements, describe_changes

    schema = _get_managed_schema(db, schema_id, current_user)
    changes = [change.model_dump() for change in payload.changes]
    try:
        fields = apply_improvements(schema.fields or [], changes)
        update = DocumentSchemaUpdate(fields=fields)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=str(exc.errors()[0].get("msg") if isinstance(exc, ValidationError) else exc)) from exc
    schema.fields = _schema_update_values(update, schema)["fields"]
    previous_version = schema.current_version
    version = schema_versions.ensure_current_version(db, schema, current_user.id, describe_changes(changes))
    db.commit()
    db.refresh(schema)
    log_activity(db=db, user_id=current_user.id, action=Actions.UPDATE_SCHEMA, resource_type="schema",
                 resource_id=schema.id, details={"schema_name": schema.name, "review_suggestions_applied": len(changes)})
    if version.version != previous_version:
        _queue_auto_test(schema, version.version, "review_suggestions")
    return schema


SAMPLE_WORDS_MAX_PAGES = 5


def _sample_words_in_worker(file_path: str, is_pdf: bool) -> dict[int, list[dict[str, Any]]]:
    """Tesseract word positions (percent of the page) for the first pages of a sample."""
    from app.services.anydoc_pipeline import _cleanup_rendered_page, _render_pdf_page
    from app.services.ocr import count_pdf_pages
    from app.services.tesseract_ocr import TesseractOcrError, process_tesseract_ocr

    pages: dict[int, list[dict[str, Any]]] = {}
    total = min(count_pdf_pages(file_path), SAMPLE_WORDS_MAX_PAGES) if is_pdf else 1
    for page_number in range(1, total + 1):
        image_path = _render_pdf_page(file_path, page_number) if is_pdf else file_path
        try:
            words: list[dict[str, Any]] = []
            process_tesseract_ocr(image_path, language=settings.TESSERACT_OCR_LANGUAGE,
                                  timeout=settings.TESSERACT_OCR_TIMEOUT_SECONDS, words_out=words)
            pages[page_number] = words
        except TesseractOcrError:
            pages[page_number] = []
        finally:
            if is_pdf:
                _cleanup_rendered_page(image_path)
    return pages


@router.post("/sample-words")
async def read_sample_words(
    *,
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Word positions read by local Tesseract, for finding values on a scanned sample form.

    Used when the sample has no text layer to search in the browser. Nothing is
    stored and no external provider is called.
    """
    _ensure_can_create_schema(current_user)
    _validate_suggestion_upload(file)
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    suffix = os.path.splitext(file.filename or "")[1].lower()
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_file.write(file_bytes)
            tmp_path = tmp_file.name
        pages = await run_in_threadpool(_sample_words_in_worker, tmp_path, suffix == ".pdf")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not read sample word positions")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="The sample could not be read for word positions") from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return {"pages": pages, "max_pages": SAMPLE_WORDS_MAX_PAGES, "coordinate_unit": "percent"}


@router.post("/preview-fixed-fields")
async def preview_fixed_position_fields(
    *,
    file: UploadFile = File(...),
    fields_json: str = Form(...),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """Read test values for fixed-position Schema fields from a sample file.

    PDF pages are read from their text layer first.  A page without text is
    rendered and read locally through TesseractOCR so the response always has
    real coordinates rather than a guessed position from an external provider.
    """
    _ensure_can_create_schema(current_user)
    _validate_suggestion_upload(file)
    try:
        raw_fields = json.loads(fields_json)
        if not isinstance(raw_fields, list) or not raw_fields:
            raise ValueError("At least one fixed-position field is required")
        fields = []
        for raw_field in raw_fields:
            validated = SchemaField.model_validate(raw_field)
            if not validated.locator:
                raise ValueError("Each preview field must include a BBox locator")
            fields.append(validated.model_dump())
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    suffix = os.path.splitext(file.filename)[1]
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_file.write(file_bytes)
            tmp_path = tmp_file.name
        raw_values, evidence = await run_in_threadpool(_extract_bbox_preview_in_worker, tmp_path, fields)
        values = raw_values
        return {
            "values": values,
            "raw_values": {name: item.get("raw_rows", item.get("raw_text")) for name, item in evidence.items()},
            "evidence": evidence,
            "coordinate_unit": "percent",
            "coordinate_origin": "top_left",
            "errors": {name: item.get("reason", "Field requires review") for name, item in evidence.items() if name not in values},
        }
    except BboxLocatorError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                logger.warning("Failed to remove temporary fixed-position sample: %s", tmp_path)

class ImportSchemaRequest(BaseModel):
    json_schema: str  # Raw JSON text from user


class SchemaExportRequest(BaseModel):
    schema_ids: List[UUID]


def _schema_id_keys(schema_ids: list[UUID]) -> list[str]:
    """Normalize UUID request values to the string keys used by the lookup map."""
    return [str(schema_id) for schema_id in schema_ids]


def _extract_import_records(payload: Any) -> list[Any]:
    """Validate the package envelope and return its schema records."""
    if not isinstance(payload, dict):
        raise ValueError("Schema package must be a JSON object")
    if payload.get("format") is not None:
        if payload.get("format") != SCHEMA_PACKAGE_FORMAT:
            raise ValueError("Unsupported schema package format")
        if payload.get("version") != SCHEMA_PACKAGE_VERSION:
            raise ValueError("Unsupported schema package version")
        records = payload.get("schemas")
    elif payload.get("name") and "schemas" not in payload:
        # Keep accepting a single schema JSON for backwards compatibility.
        records = [payload]
    else:
        raise ValueError("Package must contain a supported format and schemas array")
    if not isinstance(records, list) or not records:
        raise ValueError("Package must contain a non-empty schemas array")
    return records


def _schema_export_record(schema: DocumentSchema) -> dict[str, Any]:
    """Return only portable schema configuration, never database ownership IDs."""
    return {
        "name": schema.name,
        "description": schema.description,
        "document_type": schema.document_type,
        "ocr_engine": schema.ocr_engine,
        "extraction_profile": schema.extraction_profile or "anydoc_hybrid",
        "fields": schema.fields or [],
    }


def _unique_import_name(db: Session, name: str, reserved: set[str]) -> str:
    """Avoid silently overwriting a schema already present in the target system."""
    base = name.strip()
    candidate = base
    suffix = 2
    while candidate in reserved or db.query(DocumentSchema.id).filter(DocumentSchema.name == candidate).first():
        candidate = f"{base} (Imported {suffix})"
        suffix += 1
    reserved.add(candidate)
    return candidate


def _normalize_import_schema(raw: Any) -> dict[str, Any]:
    """Validate a portable schema while retaining supported UI metadata in fields."""
    if not isinstance(raw, dict):
        raise ValueError("Each imported schema must be an object")

    # Validate all server-owned schema constraints, including locator and array config.
    candidate = DocumentSchemaCreate.model_validate({
        "name": raw.get("name"),
        "description": raw.get("description"),
        "document_type": raw.get("document_type"),
        "ocr_engine": raw.get("ocr_engine") or "tesseract",
        "extraction_profile": raw.get("extraction_profile") or "anydoc_hybrid",
        "fields": raw.get("fields") or [],
    })
    fields = []
    for raw_field, validated_field in zip(raw.get("fields") or [], candidate.fields):
        # `id` is a local UI key and must not travel between environments.
        field = {key: value for key, value in raw_field.items() if key != "id"}
        field.update(validated_field.model_dump(exclude_none=True))
        fields.append(field)
    name = candidate.name.strip()
    if not name:
        raise ValueError("Schema name cannot be empty")
    return {
        "name": name,
        "description": candidate.description,
        "document_type": candidate.document_type,
        "ocr_engine": candidate.ocr_engine or "tesseract",
        "extraction_profile": candidate.extraction_profile,
        "fields": fields,
    }


@router.post("/export")
def export_schemas(
    payload: SchemaExportRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Response:
    """Download one portable JSON package containing the selected schemas."""
    if not payload.schema_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Select at least one schema")

    schemas = db.query(DocumentSchema).filter(DocumentSchema.id.in_(payload.schema_ids)).all()
    found = {str(schema.id): schema for schema in schemas}
    requested_ids = _schema_id_keys(payload.schema_ids)
    missing = [schema_id for schema_id in requested_ids if schema_id not in found]
    if missing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more schemas were not found")
    for schema in schemas:
        _ensure_can_manage(schema, current_user)

    package = {
        "format": SCHEMA_PACKAGE_FORMAT,
        "version": SCHEMA_PACKAGE_VERSION,
        "schemas": [_schema_export_record(found[schema_id]) for schema_id in requested_ids],
    }
    content = json.dumps(package, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=insightdoc-schemas.json"},
    )


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_schema_package(
    file: UploadFile = File(...),
    on_conflict: Literal["suffix", "skip", "error"] = Form("suffix"),
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> dict[str, Any]:
    """Import a portable JSON package as new schemas owned by the current user."""
    _ensure_can_create_schema(current_user)
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Import a .json schema package")

    raw_bytes = await file.read()
    if len(raw_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Schema package is too large")
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid schema package JSON: {exc}") from exc

    try:
        records = _extract_import_records(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if len(records) > 100:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="A package may contain at most 100 schemas")

    normalized: list[dict[str, Any]] = []
    try:
        normalized = [_normalize_import_schema(record) for record in records]
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Invalid schema: {exc}") from exc

    existing_names = {name for (name,) in db.query(DocumentSchema.name).all()}
    incoming_names = [record["name"] for record in normalized]
    duplicate_names = sorted({name for name in incoming_names if incoming_names.count(name) > 1 or name in existing_names})
    if on_conflict == "error" and duplicate_names:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"message": "Schema names already exist", "names": duplicate_names})

    imported = []
    skipped = []
    reserved = set(existing_names)
    for record in normalized:
        original_name = record["name"]
        if original_name in reserved and on_conflict == "skip":
            skipped.append(original_name)
            continue
        name = _unique_import_name(db, original_name, reserved) if on_conflict == "suffix" else original_name
        db_schema = DocumentSchema(**{**record, "name": name, "created_by": current_user.id})
        db.add(db_schema)
        reserved.add(name)
        imported.append({"name": name, "source_name": original_name})
    db.commit()
    return {"imported": imported, "skipped": skipped, "count": len(imported)}


def _repair_truncated_json(text: str) -> str | None:
    """
    Repair a JSON document that is otherwise valid but truncated at EOF.
    Only handles missing closing braces/brackets and leaves other syntax errors
    untouched.
    """
    stack: list[str] = []
    in_string = False
    escape = False

    for char in text:
        if in_string:
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            stack.append("}")
        elif char == "[":
            stack.append("]")
        elif char in "}]":
            if not stack or stack.pop() != char:
                return None

    if in_string or not stack:
        return None

    return text + "".join(reversed(stack))


def _extract_schema_object(payload: Any) -> dict[str, Any]:
    """
    Accept either a raw JSON Schema object or an envelope that contains it
    under a top-level `schema` key.
    """
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Imported JSON must be an object.",
        )

    if "schema" in payload and isinstance(payload["schema"], dict):
        return payload["schema"]

    return payload


@router.post("/validate-import")
async def validate_import_schema(
    payload: ImportSchemaRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Validate a JSON Schema string against the External API and parse its fields.
    """
    import json

    # 1. Parse JSON client-side first to give early feedback
    try:
        raw_obj = json.loads(payload.json_schema)
    except json.JSONDecodeError as exc:
        repaired = _repair_truncated_json(payload.json_schema)
        if repaired is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON: {exc}")

        try:
            raw_obj = json.loads(repaired)
        except json.JSONDecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON: {exc}")

    schema_obj = _extract_schema_object(raw_obj)
    schema_json = json.dumps(schema_obj)

    # 2. Load settings
    setting = db.query(Setting).first()
    if not setting:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Settings are not configured")

    token = setting.api_token
    suggestion_endpoint = setting.schema_suggestion_endpoint
    verify_ssl = setting.verify_ssl if setting.verify_ssl is not None else False

    if not suggestion_endpoint or not token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Schema Suggestion Endpoint and Bearer Token are required in Settings",
        )

    # 3. Build validate-schema URL from base of schema_suggestion_endpoint
    parsed = urlparse(suggestion_endpoint)
    validate_url = f"{parsed.scheme}://{parsed.netloc}/validate-schema"

    headers = {"Authorization": f"Bearer {token}"}

    # 4. POST to External API as form-encoded
    try:
        resp = requests.post(
            validate_url,
            headers=headers,
            data={"json_schema": schema_json},
            timeout=30,
            verify=verify_ssl,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"External API request failed: {exc}")

    if not resp.ok:
        detail = resp.text
        try:
            detail = resp.json().get("detail", detail)
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    # 5. Parse fields from the original input schema
    service = SchemaSuggestionService(db)
    suggested_fields = service._schema_to_fields(schema_obj)

    return {
        "valid": True,
        "schema": schema_obj,
        "suggested_fields": suggested_fields,
    }


@router.get("/{schema_id}", response_model=DocumentSchemaSchema)
def read_schema(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get schema by ID (read-only for all authenticated users).
    """
    schema = db.query(DocumentSchema).filter(DocumentSchema.id == schema_id).first()
    if not schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema not found")

    if schema.creator:
        schema.created_by_email = schema.creator.email
        schema.created_by_name = schema.creator.full_name

    return schema

@router.put("/{schema_id}", response_model=DocumentSchemaSchema)
def update_schema(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    schema_in: DocumentSchemaUpdate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Update schema.
    Admin: any schema
    Manager: only schemas created by self
    """
    schema = db.query(DocumentSchema).filter(DocumentSchema.id == schema_id).first()
    if not schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema not found")

    _ensure_can_manage(schema, current_user)

    update_values = _schema_update_values(schema_in, schema)
    for field, value in update_values.items():
        setattr(schema, field, value)

    db.add(schema)
    previous_version = schema.current_version
    version = schema_versions.ensure_current_version(db, schema, current_user.id, "Edited")
    db.commit()
    db.refresh(schema)
    if version.version != previous_version:
        _queue_auto_test(schema, version.version, "schema_change")

    # Log activity
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.UPDATE_SCHEMA,
        resource_type="schema",
        resource_id=schema.id,
        details={"schema_name": schema.name}
    )

    logger.info(
        "Updated schema %s: extraction_profile=%s document_type=%s",
        schema.id,
        schema.extraction_profile,
        schema.document_type,
    )
    return schema

@router.delete("/{schema_id}", response_model=DocumentSchemaSchema)
def delete_schema(
    *,
    db: Session = Depends(deps.get_db),
    schema_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Delete schema.
    Admin: any schema
    Manager: only schemas created by self
    """
    schema = db.query(DocumentSchema).filter(DocumentSchema.id == schema_id).first()
    if not schema:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema not found")

    _ensure_can_manage(schema, current_user)

    # Log activity before deletion
    log_activity(
        db=db,
        user_id=current_user.id,
        action=Actions.DELETE_SCHEMA,
        resource_type="schema",
        resource_id=schema.id,
        details={"schema_name": schema.name}
    )

    # Clear references before deletion to avoid FK constraint failures.
    db.query(Document).filter(Document.schema_id == schema.id).update(
        {Document.schema_id: None},
        synchronize_session=False,
    )
    db.query(Job).filter(Job.schema_id == schema.id).update(
        {Job.schema_id: None},
        synchronize_session=False,
    )

    # Sample rows go with the schema (ON DELETE CASCADE); their files must be removed too.
    sample_paths = [row.storage_path for row in
                    db.query(SchemaSample).filter(SchemaSample.schema_id == schema.id).all()]
    db.delete(schema)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete schema because it is still referenced by related records.",
        )
    if sample_paths:
        from app.tasks.maintenance_tasks import delete_schema_sample_files
        delete_schema_sample_files(sample_paths)
    return schema
