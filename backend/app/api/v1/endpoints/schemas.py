import logging
import os
import tempfile
from typing import List, Any
from urllib.parse import urlparse, urlencode
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import requests
from app.api import deps
from app.models.schema import DocumentSchema
from app.models.document import Document
from app.models.job import Job
from app.models.setting import Setting
from app.schemas.schema import DocumentSchema as DocumentSchemaSchema
from app.schemas.schema import DocumentSchemaCreate, DocumentSchemaUpdate
from app.models.user import User
from app.services.ai_suggestion_service import AISuggestionService
from app.services.ocr import process_ocr
from app.services.schema_suggestion_service import SchemaSuggestionService
from app.utils.activity_logger import log_activity, Actions

router = APIRouter()
logger = logging.getLogger(__name__)

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
    normalized = _normalize_role(current_user.role)
    if not (current_user.is_superuser or normalized in ["admin", "manager"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions to create schema.")

    db_schema = DocumentSchema(
        name=schema_in.name,
        description=schema_in.description,
        document_type=schema_in.document_type,
        ocr_engine=schema_in.ocr_engine,
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
    Uses configured schema_suggestion_endpoint + api_token from Settings.
    """
    del current_user

    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is required")

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")

    service = SchemaSuggestionService(db)
    legacy_error: Exception | None = None
    try:
        result = service.suggest_from_file(
            file_bytes=file_bytes,
            filename=file.filename,
            content_type=file.content_type,
            document_type=document_type,
        )
        if result.get("suggested_fields"):
            return result
        legacy_error = ValueError("Schema suggestion API returned no fields")
    except ValueError as exc:
        legacy_error = exc
    except Exception as exc:
        legacy_error = exc

    logger.warning("Legacy schema suggestion failed; falling back to OCR + AI provider: %s", legacy_error)

    suffix = os.path.splitext(file.filename)[1]
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
            tmp_file.write(file_bytes)
            tmp_path = tmp_file.name

        ocr_result = process_ocr(tmp_path, db, filename=file.filename, mime_type=file.content_type)
        ocr_content = _extract_ocr_content(ocr_result)
        if not ocr_content:
            raise ValueError("No text could be extracted from the document")

        ai_service = AISuggestionService(db)
        suggestion = await ai_service.suggest_fields_from_ocr(
            ocr_content=ocr_content,
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
                "source": "ocr_ai_provider",
                "provider_used": suggestion.provider_used,
                "confidence_score": suggestion.confidence_score,
                "document_preview": suggestion.document_preview,
                "legacy_error": str(legacy_error) if legacy_error else None,
            },
        }
    except ValueError as exc:
        detail = str(exc)
        if legacy_error:
            detail = f"{detail} (legacy schema suggestion also failed: {legacy_error})"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Schema suggestion request failed: {str(exc)}",
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                logger.warning("Failed to remove temporary schema suggestion file: %s", tmp_path)


def _extract_ocr_content(ocr_result: dict[str, Any]) -> str:
    if ocr_result.get("status") != "success":
        return ""

    chunks: list[str] = []
    pages = ocr_result.get("results", {}).get("pages", [])
    for page in pages:
        ai_processing = page.get("ai_processing") or {}
        if ai_processing.get("success") and ai_processing.get("content"):
            chunks.append(str(ai_processing["content"]))
        elif page.get("ocr_text"):
            chunks.append(str(page["ocr_text"]))

    return "\n\n".join(chunk.strip() for chunk in chunks if chunk and chunk.strip())


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

    for field, value in schema_in.dict(exclude_unset=True).items():
        if field == "fields":
            normalized_fields = []
            for f in value or []:
                if hasattr(f, "dict"):
                    normalized_fields.append(f.dict())
                else:
                    normalized_fields.append(f)
            setattr(schema, field, normalized_fields)
        else:
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
