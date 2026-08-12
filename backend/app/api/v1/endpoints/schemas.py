import logging
import os
import tempfile
from typing import List, Any
from urllib.parse import urlparse, urlencode
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel
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
from app.schemas.schema import DocumentSchemaCreate, DocumentSchemaUpdate
from app.models.user import User
from app.services.ai_suggestion_service import AISuggestionService
from app.services.schema_suggestion_service import SchemaSuggestionService
from app.services.anydoc_pipeline import (
    AnydocFallbackToLegacy,
    AnydocTerminalError,
    extract_schema_sample,
)
from app.services.extraction_profiles import validate_extraction_profile
from app.core.config import settings
from app.utils.activity_logger import log_activity, Actions

router = APIRouter()
logger = logging.getLogger(__name__)


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
    normalized = _normalize_role(current_user.role)
    is_admin = current_user.is_superuser or normalized == "admin"
    if is_admin:
        return
    if normalized == "manager" and schema.created_by == current_user.id:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions to manage this schema.",
    )


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

    schemas = query.offset(skip).limit(limit).all()

    for schema in schemas:
        if schema.creator:
            schema.created_by_email = schema.creator.email
            schema.created_by_name = schema.creator.full_name

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
