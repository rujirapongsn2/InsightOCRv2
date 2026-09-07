import logging
import os
import tempfile
import json
from typing import List, Any, Literal
from urllib.parse import urlparse, urlencode
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Response, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
import requests
from app.api import deps
from app.db.session import SessionLocal
from app.models.schema import DocumentSchema
from app.models.document import Document
from app.models.job import Job
from app.models.setting import Setting
from app.schemas.schema import DocumentSchema as DocumentSchemaSchema
from app.schemas.schema import DocumentSchemaCreate, DocumentSchemaUpdate, SchemaField
from app.models.user import User
from app.api.permissions import can_manage_group_resource
from app.services.ai_suggestion_service import AISuggestionService
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


@router.post("/suggest-from-file")
async def suggest_schema_from_file(
    *,
    db: Session = Depends(deps.get_db),
    file: UploadFile = File(...),
    document_type: str | None = None,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Suggest JSON schema fields from an uploaded document.
    AnyDoc reads text-layer documents locally. Scanned pages use TesseractOCR
    and then the configured OCR fallback before the active AI provider suggests
    editable fields.
    """
    _ensure_can_create_schema(current_user)

    _validate_suggestion_upload(file)

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    suffix = os.path.splitext(file.filename)[1]
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_file.write(file_bytes)
            tmp_path = tmp_file.name

        extraction = await run_in_threadpool(_extract_schema_sample_in_worker, tmp_path)
        if not extraction.markdown.strip():
            raise ValueError("No text could be extracted from the document")

        ai_service = AISuggestionService(db)
        suggestion = await ai_service.suggest_fields_from_ocr(
            ocr_content=extraction.markdown,
            document_type=document_type,
        )

        suggested_fields = [
            {
                "name": field.name,
                "type": field.type,
                "description": field.description,
                "required": False,
                "confidence": field.confidence,
                "example_value": field.example_value,
            }
            for field in suggestion.suggested_fields
        ]

        if not suggested_fields:
            raise ValueError("AI provider returned no field suggestions")

        return {
            "schema": _fields_to_schema(suggested_fields),
            "suggested_fields": suggested_fields,
            "raw_result": {
                "source": "anydoc_schema_sample",
                "provider_used": suggestion.provider_used,
                "confidence_score": suggestion.confidence_score,
                "document_preview": suggestion.document_preview,
                "extraction": {
                    "pipeline": extraction.metadata.get("pipeline"),
                    "parser": extraction.metadata.get("parser"),
                    "page_count": extraction.metadata.get("page_count"),
                    "page_sources": extraction.metadata.get("page_sources", []),
                    "provider_counts": extraction.metadata.get("provider_counts", {}),
                },
            },
        }
    except (AnydocFallbackToLegacy, AnydocTerminalError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Schema suggestion failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Schema suggestion request failed. Check the active AI provider and try again.",
        ) from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                logger.warning("Failed to remove temporary schema suggestion file: %s", tmp_path)


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

def _fields_to_schema(fields: list[dict[str, Any]]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []

    for field in fields:
        name = field["name"]
        properties[name] = {
            "type": _field_type_to_json_schema(field.get("type")),
            "description": field.get("description", ""),
        }
        if field.get("example_value") is not None:
            properties[name]["example"] = field["example_value"]
        if field.get("required"):
            required.append(name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    return schema


def _field_type_to_json_schema(field_type: str | None) -> str:
    if field_type in {"number", "currency"}:
        return "number"
    if field_type == "boolean":
        return "boolean"
    if field_type == "array":
        return "array"
    return "string"

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
    db.commit()
    db.refresh(schema)

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

    db.delete(schema)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete schema because it is still referenced by related records.",
        )
    return schema
