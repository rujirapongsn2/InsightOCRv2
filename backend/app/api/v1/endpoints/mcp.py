"""Scoped MCP endpoint for InsightDOC.

The endpoint uses Personal API Tokens and the same ownership checks as the
public InsightDOC API. Read tools are available to every token; controlled
actions require an explicit, narrowly-scoped token permission.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime
from io import BytesIO
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api import deps
from app.api.v1.endpoints import documents as documents_endpoint
from app.api.permissions import ensure_document_access, ensure_job_access, is_admin_user
from app.core.config import settings
from app.models.document import Document
from app.models.integration import Integration, IntegrationStatus
from app.models.job import Job
from app.models.schema import DocumentSchema
from app.models.user import User
from app.services.api_token_scopes import (
    MCP_DOCUMENT_PROCESS_SCOPE,
    MCP_DOCUMENT_REVIEW_SCOPE,
    MCP_DOCUMENT_UPLOAD_SCOPE,
    MCP_JOB_WRITE_SCOPE,
    normalize_api_token_scopes,
)
from app.services.storage import get_storage_service
from app.utils.activity_logger import Actions, log_activity


router = APIRouter()

MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SUPPORTED_PROTOCOL_VERSIONS = {"2025-03-26", "2025-06-18"}
MCP_MAX_RESULTS = 100
MCP_MAX_TEXT_CHARS = 20_000
MCP_MAX_UPLOAD_BYTES = settings.MCP_MAX_UPLOAD_SIZE_MB * 1024 * 1024
MCP_MAX_REVIEW_BYTES = 1_000_000
MCP_MAX_REQUEST_BYTES = ((MCP_MAX_UPLOAD_BYTES + 2) // 3) * 4 + 64 * 1024


MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "insightdoc_list_jobs",
        "title": "List InsightDOC jobs",
        "description": "List the caller's InsightDOC jobs. Administrators can list all jobs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": MCP_MAX_RESULTS, "default": 20},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "status": {"type": "string", "description": "Optional job status, for example review or completed."},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_get_job",
        "title": "Get an InsightDOC job",
        "description": "Get a job summary and its configured schema.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string", "format": "uuid"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_list_job_documents",
        "title": "List job documents",
        "description": "List documents belonging to an accessible InsightDOC job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "format": "uuid"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MCP_MAX_RESULTS, "default": 50},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_get_document",
        "title": "Get document data",
        "description": "Get document metadata, extracted data, and reviewed data. Raw OCR text is available through insightdoc_get_document_text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "format": "uuid"},
                "include_data": {"type": "boolean", "default": True},
            },
            "required": ["document_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_get_document_text",
        "title": "Get document text",
        "description": "Read a bounded segment of the Markdown/OCR text extracted from an InsightDOC document.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "format": "uuid"},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "max_chars": {"type": "integer", "minimum": 1, "maximum": MCP_MAX_TEXT_CHARS, "default": 12_000},
            },
            "required": ["document_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_get_document_status",
        "title": "Get document processing status",
        "description": "Get the current extraction/review status and any safe processing error for a document.",
        "inputSchema": {
            "type": "object",
            "properties": {"document_id": {"type": "string", "format": "uuid"}},
            "required": ["document_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_get_document_evidence",
        "title": "Get document extraction evidence",
        "description": "Get extraction provenance and field evidence recorded by the document pipeline, when available.",
        "inputSchema": {
            "type": "object",
            "properties": {"document_id": {"type": "string", "format": "uuid"}},
            "required": ["document_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_search_documents",
        "title": "Search accessible documents",
        "description": "Search filenames and extracted OCR text in the caller's accessible documents.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 2, "maxLength": 200},
                "job_id": {"type": "string", "format": "uuid", "description": "Optional job to search within."},
                "limit": {"type": "integer", "minimum": 1, "maximum": MCP_MAX_RESULTS, "default": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_list_schemas",
        "title": "List document schemas",
        "description": "List document schemas available in InsightDOC, including field definitions.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": MCP_MAX_RESULTS, "default": 50}},
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_list_integrations",
        "title": "List integrations",
        "description": "List active integrations owned by the caller. Administrators can list all active integrations. Secret configuration is never returned.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": MCP_MAX_RESULTS, "default": 50}},
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_create_job",
        "title": "Create InsightDOC job",
        "description": "Create a draft job owned by the caller. Requires the mcp:jobs:write token scope.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 255},
                "description": {"type": "string", "maxLength": 2000},
                "schema_id": {"type": "string", "format": "uuid"},
                "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 128},
                "confirmed": {"type": "boolean", "description": "Must be true after the user confirms this action."},
            },
            "required": ["name", "confirmed"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_upload_document",
        "title": "Upload document to a job",
        "description": "Upload one supported document to an accessible job without processing it. Requires the mcp:documents:upload token scope.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "format": "uuid"},
                "filename": {"type": "string", "minLength": 1, "maxLength": 255},
                "content_base64": {"type": "string", "minLength": 1},
                "mime_type": {"type": "string", "maxLength": 255},
                "idempotency_key": {"type": "string", "minLength": 8, "maxLength": 128},
                "confirmed": {"type": "boolean", "description": "Must be true after the user confirms this action."},
            },
            "required": ["job_id", "filename", "content_base64", "confirmed"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_process_document",
        "title": "Process InsightDOC document",
        "description": "Queue a document for extraction with an optional schema. Requires the mcp:documents:process token scope.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "format": "uuid"},
                "schema_id": {"type": "string", "format": "uuid"},
                "confirmed": {"type": "boolean", "description": "Must be true after the user confirms this action."},
            },
            "required": ["document_id", "confirmed"],
            "additionalProperties": False,
        },
    },
    {
        "name": "insightdoc_save_document_review",
        "title": "Save document review data",
        "description": "Save edited structured data without approving or rejecting the document. Requires the mcp:documents:review token scope.",
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "format": "uuid"},
                "reviewed_data": {"type": "object"},
                "confirmed": {"type": "boolean", "description": "Must be true after the user confirms this action."},
            },
            "required": ["document_id", "reviewed_data", "confirmed"],
            "additionalProperties": False,
        },
    },
]
MCP_TOOL_DEFINITIONS = {tool["name"]: tool for tool in MCP_TOOLS}
MCP_TOOL_REQUIRED_SCOPES = {
    "insightdoc_create_job": {MCP_JOB_WRITE_SCOPE},
    "insightdoc_upload_document": {MCP_DOCUMENT_UPLOAD_SCOPE},
    "insightdoc_process_document": {MCP_DOCUMENT_PROCESS_SCOPE},
    "insightdoc_save_document_review": {MCP_DOCUMENT_REVIEW_SCOPE},
}
MCP_CONTROLLED_TOOLS = set(MCP_TOOL_REQUIRED_SCOPES)


def _visible_mcp_tools(current_user: User | None) -> list[dict[str, Any]]:
    """Return only tools that the authenticated token can actually call."""
    if current_user is None:
        # Keep the pure protocol handler useful for unauthenticated unit tests;
        # the HTTP endpoint always authenticates before calling it.
        return MCP_TOOLS
    api_token = getattr(current_user, "api_token", None)
    if not getattr(api_token, "mcp_access_only", False):
        return [tool for tool in MCP_TOOLS if tool["name"] not in MCP_CONTROLLED_TOOLS]
    token_scopes = set(normalize_api_token_scopes(getattr(api_token, "scopes", None)))
    return [
        tool
        for tool in MCP_TOOLS
        if MCP_TOOL_REQUIRED_SCOPES.get(tool["name"], set()) <= token_scopes
    ]


def _as_uuid(value: Any, field_name: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field_name} must be a valid UUID") from exc


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int, field_name: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")
    return parsed


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _integration_type_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _document_summary(document: Document) -> dict[str, Any]:
    return {
        "id": str(document.id),
        "job_id": str(document.job_id),
        "filename": document.filename,
        "mime_type": document.mime_type,
        "file_size": document.file_size,
        "status": document.status,
        "schema_id": str(document.schema_id) if document.schema_id else None,
        "review_decision": document.review_decision,
        "uploaded_at": _serialize_datetime(document.uploaded_at),
        "processed_at": _serialize_datetime(document.processed_at),
        "reviewed_at": _serialize_datetime(document.reviewed_at),
        "page_count": document.page_count,
        "processing_error": document.processing_error,
        "extraction": {
            "pipeline": (document.extraction_metadata or {}).get("pipeline"),
            "source": (document.extraction_metadata or {}).get("source"),
            "provider_counts": (document.extraction_metadata or {}).get("provider_counts"),
        },
    }


def _job_summary(job: Job) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "name": job.name,
        "description": job.description,
        "status": job.status,
        "schema_id": str(job.schema_id) if job.schema_id else None,
        "created_at": _serialize_datetime(job.created_at),
    }


def _get_job(db: Session, user: User, job_id: Any) -> Job:
    parsed_id = _as_uuid(job_id, "job_id")
    job = (
        db.query(Job)
        .options(selectinload(Job.documents), selectinload(Job.schema))
        .filter(Job.id == parsed_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return ensure_job_access(user, job)


def _get_document(db: Session, user: User, document_id: Any) -> Document:
    parsed_id = _as_uuid(document_id, "document_id")
    document = (
        db.query(Document)
        .options(selectinload(Document.job), selectinload(Document.schema))
        .filter(Document.id == parsed_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return ensure_document_access(user, document)


def _list_jobs(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    limit = _bounded_int(arguments.get("limit"), default=20, minimum=1, maximum=MCP_MAX_RESULTS, field_name="limit")
    offset = _bounded_int(arguments.get("offset"), default=0, minimum=0, maximum=1_000_000, field_name="offset")
    query = db.query(Job).options(selectinload(Job.documents), selectinload(Job.schema))
    if not is_admin_user(user):
        query = query.filter(Job.user_id == user.id)
    job_status = arguments.get("status")
    if job_status:
        query = query.filter(Job.status == str(job_status).strip())
    jobs = query.order_by(Job.created_at.desc()).offset(offset).limit(limit).all()
    return {
        "jobs": [
            {
                "id": str(job.id),
                "name": job.name,
                "description": job.description,
                "status": job.status,
                "schema": {"id": str(job.schema.id), "name": job.schema.name} if job.schema else None,
                "document_count": len(job.documents or []),
                "created_at": _serialize_datetime(job.created_at),
                "updated_at": _serialize_datetime(job.updated_at),
            }
            for job in jobs
        ],
        "offset": offset,
        "limit": limit,
    }


def _get_job_tool(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    job = _get_job(db, user, arguments.get("job_id"))
    return {
        "id": str(job.id),
        "name": job.name,
        "description": job.description,
        "status": job.status,
        "schema": (
            {"id": str(job.schema.id), "name": job.schema.name, "document_type": job.schema.document_type}
            if job.schema
            else None
        ),
        "document_count": len(job.documents or []),
        "created_at": _serialize_datetime(job.created_at),
        "updated_at": _serialize_datetime(job.updated_at),
    }


def _list_job_documents(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    job = _get_job(db, user, arguments.get("job_id"))
    limit = _bounded_int(arguments.get("limit"), default=50, minimum=1, maximum=MCP_MAX_RESULTS, field_name="limit")
    offset = _bounded_int(arguments.get("offset"), default=0, minimum=0, maximum=1_000_000, field_name="offset")
    documents = (
        db.query(Document)
        .filter(Document.job_id == job.id)
        .order_by(Document.uploaded_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"job_id": str(job.id), "documents": [_document_summary(document) for document in documents], "offset": offset, "limit": limit}


def _get_document_tool(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    document = _get_document(db, user, arguments.get("document_id"))
    result = _document_summary(document)
    if arguments.get("include_data", True):
        result["extracted_data"] = document.extracted_data
        result["reviewed_data"] = document.reviewed_data
    return result


def _get_document_text(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    document = _get_document(db, user, arguments.get("document_id"))
    offset = _bounded_int(arguments.get("offset"), default=0, minimum=0, maximum=10_000_000, field_name="offset")
    max_chars = _bounded_int(
        arguments.get("max_chars"), default=12_000, minimum=1, maximum=MCP_MAX_TEXT_CHARS, field_name="max_chars"
    )
    text = document.ocr_text or ""
    return {
        "document_id": str(document.id),
        "offset": offset,
        "max_chars": max_chars,
        "total_chars": len(text),
        "has_more": offset + max_chars < len(text),
        "text": text[offset : offset + max_chars],
    }


def _get_document_status(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    document = _get_document(db, user, arguments.get("document_id"))
    return {
        "document_id": str(document.id),
        "status": document.status,
        "review_decision": document.review_decision,
        "processing_error": document.processing_error,
        "page_count": document.page_count,
        "processing_started_at": _serialize_datetime(document.processing_started_at),
        "processed_at": _serialize_datetime(document.processed_at),
        "has_extracted_data": document.extracted_data is not None,
        "has_reviewed_data": document.reviewed_data is not None,
    }


def _get_document_evidence(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    document = _get_document(db, user, arguments.get("document_id"))
    metadata = document.extraction_metadata or {}
    return {
        "document_id": str(document.id),
        "pipeline": metadata.get("pipeline"),
        "parser": metadata.get("parser"),
        "parser_version": metadata.get("parser_version"),
        "source": metadata.get("source"),
        "text_layer_pages": metadata.get("text_layer_pages") or [],
        "ocr_pages": metadata.get("ocr_pages") or [],
        "provider_counts": metadata.get("provider_counts") or {},
        "field_evidence": metadata.get("field_evidence") or metadata.get("evidence") or {},
        "mapping": metadata.get("mapping") or {},
        "legacy_fallback": metadata.get("legacy_fallback"),
    }


def _search_documents(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    search_text = str(arguments.get("query") or "").strip()
    if len(search_text) < 2:
        raise ValueError("query must contain at least 2 characters")
    limit = _bounded_int(arguments.get("limit"), default=20, minimum=1, maximum=MCP_MAX_RESULTS, field_name="limit")
    query = db.query(Document).options(selectinload(Document.job)).join(Job, Document.job_id == Job.id)
    if not is_admin_user(user):
        query = query.filter(Job.user_id == user.id)
    job_id = arguments.get("job_id")
    if job_id is not None:
        job = _get_job(db, user, job_id)
        query = query.filter(Document.job_id == job.id)
    pattern = f"%{search_text}%"
    documents = (
        query.filter(or_(Document.filename.ilike(pattern), Document.ocr_text.ilike(pattern)))
        .order_by(Document.uploaded_at.desc())
        .limit(limit)
        .all()
    )
    results = []
    for document in documents:
        text = document.ocr_text or ""
        index = text.lower().find(search_text.lower())
        snippet = text[max(0, index - 140) : index + len(search_text) + 220] if index >= 0 else ""
        results.append({**_document_summary(document), "snippet": snippet})
    return {"query": search_text, "results": results, "limit": limit}


def _list_schemas(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    del user
    limit = _bounded_int(arguments.get("limit"), default=50, minimum=1, maximum=MCP_MAX_RESULTS, field_name="limit")
    schemas = db.query(DocumentSchema).order_by(DocumentSchema.created_at.desc()).limit(limit).all()
    return {
        "schemas": [
            {
                "id": str(schema.id),
                "name": schema.name,
                "description": schema.description,
                "document_type": schema.document_type,
                "extraction_profile": schema.extraction_profile,
                "fields": schema.fields or [],
                "created_at": _serialize_datetime(schema.created_at),
                "updated_at": _serialize_datetime(schema.updated_at),
            }
            for schema in schemas
        ],
        "limit": limit,
    }


def _list_integrations(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    limit = _bounded_int(arguments.get("limit"), default=50, minimum=1, maximum=MCP_MAX_RESULTS, field_name="limit")
    query = db.query(Integration).filter(Integration.status == IntegrationStatus.ACTIVE)
    if not is_admin_user(user):
        query = query.filter(Integration.user_id == user.id)
    integrations = query.order_by(Integration.name.asc()).limit(limit).all()
    return {
        "integrations": [
            {
                "id": str(integration.id),
                "name": integration.name,
                "type": _integration_type_value(integration.type),
                "description": integration.description,
                "status": _integration_type_value(integration.status),
                "created_at": _serialize_datetime(integration.created_at),
                "updated_at": _serialize_datetime(integration.updated_at),
            }
            for integration in integrations
        ],
        "limit": limit,
    }


def _mcp_audit_details(current_user: User) -> dict[str, str]:
    api_token = getattr(current_user, "api_token", None)
    return {
        "source": "mcp",
        "api_token_id": str(api_token.id) if api_token else "unknown",
        "api_token_name": str(api_token.name) if api_token else "unknown",
    }


def _idempotency_digest(tool_name: str, arguments: dict[str, Any], current_user: User) -> str | None:
    key = arguments.get("idempotency_key")
    if not key:
        return None
    key = key.strip()
    if not key:
        raise ValueError("idempotency_key must not be empty")
    api_token = getattr(current_user, "api_token", None)
    if api_token is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="MCP token context is required")
    material = f"{tool_name}:{api_token.id}:{key}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _create_job(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    name = str(arguments["name"]).strip()
    if not name:
        raise ValueError("name must not be empty")
    schema_id = None
    if arguments.get("schema_id"):
        schema_id = _as_uuid(arguments["schema_id"], "schema_id")
        if not db.query(DocumentSchema.id).filter(DocumentSchema.id == schema_id).first():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema not found")
    idempotency_key = _idempotency_digest("insightdoc_create_job", arguments, user)
    if idempotency_key:
        existing = db.query(Job).filter(Job.mcp_idempotency_key == idempotency_key).first()
        if existing:
            return _job_summary(existing)
    job = Job(
        name=name,
        description=arguments.get("description", "").strip() or None,
        schema_id=schema_id,
        status="draft",
        user_id=user.id,
        mcp_idempotency_key=idempotency_key,
    )
    try:
        db.add(job)
        db.commit()
        db.refresh(job)
    except IntegrityError:
        db.rollback()
        if idempotency_key:
            existing = db.query(Job).filter(Job.mcp_idempotency_key == idempotency_key).first()
            if existing:
                return _job_summary(existing)
        raise
    details = {"job_name": job.name, **_mcp_audit_details(user)}
    log_activity(db, user.id, Actions.CREATE_JOB, "job", job.id, details)
    return _job_summary(job)


def _upload_document(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    job = _get_job(db, user, arguments["job_id"])
    idempotency_key = _idempotency_digest("insightdoc_upload_document", arguments, user)
    if idempotency_key:
        existing = db.query(Document).filter(Document.mcp_idempotency_key == idempotency_key).first()
        if existing:
            return _document_summary(existing)
    filename = str(arguments["filename"]).strip()
    if not filename or "/" in filename or "\\" in filename:
        raise ValueError("filename must be a file name without a path")
    content_base64 = arguments["content_base64"]
    max_base64_chars = ((MCP_MAX_UPLOAD_BYTES + 2) // 3) * 4
    if len(content_base64) > max_base64_chars:
        raise ValueError(f"Upload exceeds the MCP limit of {settings.MCP_MAX_UPLOAD_SIZE_MB} MB")
    try:
        file_content = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("content_base64 must be valid base64 without a data URL prefix") from exc
    if not file_content:
        raise ValueError("Uploaded file is empty")
    if len(file_content) > MCP_MAX_UPLOAD_BYTES:
        raise ValueError(f"Upload exceeds the MCP limit of {settings.MCP_MAX_UPLOAD_SIZE_MB} MB")

    file_ext = filename[filename.rfind(".") :].lower() if "." in filename else ""
    allowed_exts = {extension.strip().lower() for extension in settings.ALLOWED_UPLOAD_EXTENSIONS.split(",") if extension.strip()}
    if file_ext not in allowed_exts:
        raise ValueError(f"File type '{file_ext or 'unknown'}' is not allowed")
    _validate_upload_content(file_ext, file_content)

    file_key = f"documents/{job.id}/{uuid4()}{file_ext}"
    try:
        get_storage_service().upload_file(
            BytesIO(file_content),
            file_key,
            content_type=arguments.get("mime_type") or "application/octet-stream",
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Document storage upload failed") from exc

    document = Document(
        job_id=job.id,
        filename=filename,
        file_path=file_key,
        file_size=len(file_content),
        mime_type=arguments.get("mime_type") or None,
        status="uploaded",
        mcp_idempotency_key=idempotency_key,
    )
    try:
        db.add(document)
        db.commit()
        db.refresh(document)
    except IntegrityError:
        db.rollback()
        try:
            get_storage_service().delete_file(file_key)
        except Exception:
            pass
        existing = db.query(Document).filter(Document.mcp_idempotency_key == idempotency_key).first()
        if existing:
            return _document_summary(existing)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A document upload with this idempotency key already exists")
    except Exception as exc:
        db.rollback()
        try:
            get_storage_service().delete_file(file_key)
        except Exception:
            pass
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Document upload could not be saved") from exc
    details = {"filename": document.filename, "job_id": str(job.id), **_mcp_audit_details(user)}
    log_activity(db, user.id, Actions.UPLOAD_DOCUMENT, "document", document.id, details)
    return _document_summary(document)


def _validate_upload_content(file_ext: str, file_content: bytes) -> None:
    """Reject obvious extension/content mismatches before storing a file."""
    signatures = {
        ".pdf": (b"%PDF-",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".tif": (b"II*\x00", b"MM\x00*"),
        ".tiff": (b"II*\x00", b"MM\x00*"),
        ".bmp": (b"BM",),
    }
    if file_ext == ".webp":
        if len(file_content) < 12 or not file_content.startswith(b"RIFF") or file_content[8:12] != b"WEBP":
            raise ValueError("File content does not match the '.webp' extension")
        return
    if file_ext == ".heic":
        heic_brands = {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
        if len(file_content) < 12 or file_content[4:8] != b"ftyp" or file_content[8:12] not in heic_brands:
            raise ValueError("File content does not match the '.heic' extension")
        return
    expected = signatures.get(file_ext)
    if expected and not any(file_content.startswith(signature) for signature in expected):
        raise ValueError(f"File content does not match the '{file_ext}' extension")


def _process_document(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    document = _get_document(db, user, arguments["document_id"])
    schema_id = _as_uuid(arguments["schema_id"], "schema_id") if arguments.get("schema_id") else None
    response = documents_endpoint.process_document(
        db=db,
        document_id=str(document.id),
        process_request=documents_endpoint.ProcessRequest(schema_id=schema_id),
        current_user=user,
    )
    details = {"filename": document.filename, "task_id": response.task_id, **_mcp_audit_details(user)}
    log_activity(db, user.id, Actions.PROCESS_DOCUMENT, "document", document.id, details)
    return response.model_dump()


def _save_document_review(arguments: dict[str, Any], db: Session, user: User) -> dict[str, Any]:
    document = _get_document(db, user, arguments["document_id"])
    if document.status != "extraction_completed" or document.review_decision is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MCP review saves are allowed only before a document is reviewed or decided",
        )
    reviewed_data = arguments["reviewed_data"]
    if len(json.dumps(reviewed_data, ensure_ascii=False).encode("utf-8")) > MCP_MAX_REVIEW_BYTES:
        raise ValueError("reviewed_data exceeds the MCP limit of 1 MB")
    document.reviewed_data = reviewed_data
    db.add(document)
    db.commit()
    db.refresh(document)
    details = {
        "filename": document.filename,
        "saved_review_only": True,
        "review_decision": None,
        **_mcp_audit_details(user),
    }
    log_activity(db, user.id, Actions.UPDATE_DOCUMENT, "document", document.id, details)
    return {
        "document_id": str(document.id),
        "status": document.status,
        "review_decision": document.review_decision,
        "reviewed_at": None,
        "message": "Review data saved for later approval. The document was not reviewed, approved, or rejected.",
    }


MCP_TOOL_HANDLERS: dict[str, Callable[[dict[str, Any], Session, User], dict[str, Any]]] = {
    "insightdoc_list_jobs": _list_jobs,
    "insightdoc_get_job": _get_job_tool,
    "insightdoc_list_job_documents": _list_job_documents,
    "insightdoc_get_document": _get_document_tool,
    "insightdoc_get_document_text": _get_document_text,
    "insightdoc_get_document_status": _get_document_status,
    "insightdoc_get_document_evidence": _get_document_evidence,
    "insightdoc_search_documents": _search_documents,
    "insightdoc_list_schemas": _list_schemas,
    "insightdoc_list_integrations": _list_integrations,
    "insightdoc_create_job": _create_job,
    "insightdoc_upload_document": _upload_document,
    "insightdoc_process_document": _process_document,
    "insightdoc_save_document_review": _save_document_review,
}


def _require_tool_scope(tool_name: str, current_user: User) -> None:
    required_scopes = MCP_TOOL_REQUIRED_SCOPES.get(tool_name, set())
    if not required_scopes:
        return
    api_token = getattr(current_user, "api_token", None)
    if not getattr(api_token, "mcp_access_only", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Controlled MCP actions require a dedicated MCP-only token",
        )
    token_scopes = normalize_api_token_scopes(getattr(api_token, "scopes", None))
    missing_scopes = sorted(required_scopes - set(token_scopes))
    if missing_scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This MCP tool requires token scope(s): {', '.join(missing_scopes)}",
        )


def _require_action_confirmation(tool_name: str, arguments: dict[str, Any]) -> None:
    if tool_name in MCP_CONTROLLED_TOOLS and arguments.get("confirmed") is not True:
        raise ValueError("This MCP action requires confirmed=true after the user approves it")


def _jsonrpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_result(data: dict[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    serialized = jsonable_encoder(data)
    text = json.dumps(serialized, ensure_ascii=False, indent=2, default=str)
    result: dict[str, Any] = {"content": [{"type": "text", "text": text}], "structuredContent": serialized}
    if is_error:
        result["isError"] = True
    return result


def _validate_tool_arguments(tool_name: str, arguments: dict[str, Any]) -> None:
    """Apply the advertised JSON-schema basics before a handler sees input.

    The server does not depend on a separate JSON-schema package for this
    small, fixed tool catalog. Rejecting unexpected fields is important here:
    it prevents clients from assuming that a read-only tool supports hidden
    filters or output modes that were never reviewed.
    """
    definition = MCP_TOOL_DEFINITIONS[tool_name]
    schema = definition["inputSchema"]
    properties = schema.get("properties", {})
    unexpected = sorted(set(arguments) - set(properties))
    if unexpected:
        raise ValueError(f"Unsupported argument(s): {', '.join(unexpected)}")
    for required_name in schema.get("required", []):
        if required_name not in arguments:
            raise ValueError(f"Missing required argument: {required_name}")
    for name, value in arguments.items():
        field = properties[name]
        field_type = field.get("type")
        if field_type == "string":
            if not isinstance(value, str):
                raise ValueError(f"{name} must be a string")
            if "minLength" in field and len(value) < field["minLength"]:
                raise ValueError(f"{name} is too short")
            if "maxLength" in field and len(value) > field["maxLength"]:
                raise ValueError(f"{name} is too long")
        elif field_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if "minimum" in field and value < field["minimum"]:
                raise ValueError(f"{name} is below the minimum")
            if "maximum" in field and value > field["maximum"]:
                raise ValueError(f"{name} is above the maximum")
        elif field_type == "boolean" and not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")
        elif field_type == "object" and not isinstance(value, dict):
            raise ValueError(f"{name} must be an object")


def handle_mcp_message(payload: Any, db: Session | None, current_user: User | None) -> dict[str, Any] | None:
    """Handle one stateless MCP JSON-RPC message.

    Keeping protocol handling separate from FastAPI makes the core contract
    straightforward to test without a web server.
    """
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
        return _jsonrpc_error(payload.get("id") if isinstance(payload, dict) else None, -32600, "Invalid JSON-RPC request")

    method = payload.get("method")
    request_id = payload.get("id")
    is_notification = "id" not in payload
    params = payload.get("params") or {}
    if not isinstance(method, str) or not isinstance(params, dict):
        return _jsonrpc_error(request_id, -32600, "Invalid JSON-RPC request")

    if method == "initialize":
        requested_version = params.get("protocolVersion")
        protocol_version = requested_version if requested_version in MCP_SUPPORTED_PROTOCOL_VERSIONS else MCP_PROTOCOL_VERSION
        return _jsonrpc_result(
            request_id,
            {
                "protocolVersion": protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "insightdoc", "version": "1.0.0"},
                "instructions": "InsightDOC MCP reads jobs, documents, extraction results, schemas, and integrations. Controlled actions require explicit Personal API Token scopes."
            },
        )

    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None if is_notification else _jsonrpc_result(request_id, {})

    if method == "ping":
        return _jsonrpc_result(request_id, {})

    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": _visible_mcp_tools(current_user)})

    if method == "tools/call":
        if db is None or current_user is None:
            return _jsonrpc_error(request_id, -32603, "MCP tool execution requires an authenticated request")
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(tool_name, str) or not isinstance(arguments, dict):
            return _jsonrpc_error(request_id, -32602, "tools/call requires a tool name and object arguments")
        handler = MCP_TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return _jsonrpc_result(request_id, _tool_result({"error": f"Unknown MCP tool: {tool_name}"}, is_error=True))
        try:
            _validate_tool_arguments(tool_name, arguments)
            _require_action_confirmation(tool_name, arguments)
            _require_tool_scope(tool_name, current_user)
            return _jsonrpc_result(request_id, _tool_result(handler(arguments, db, current_user)))
        except HTTPException as exc:
            detail = str(exc.detail)
            message = detail if detail.startswith(("This MCP tool requires", "Controlled MCP actions require")) else (
                "Resource not found or not permitted" if exc.status_code in {403, 404} else detail
            )
            return _jsonrpc_result(request_id, _tool_result({"error": message}, is_error=True))
        except ValueError as exc:
            return _jsonrpc_result(request_id, _tool_result({"error": str(exc)}, is_error=True))
        except Exception:
            return _jsonrpc_result(request_id, _tool_result({"error": "Unable to complete the requested operation"}, is_error=True))

    return _jsonrpc_error(request_id, -32601, f"Method not found: {method}")


def _allowed_origins() -> set[str]:
    configured = [settings.PUBLIC_APP_URL, settings.BACKEND_CORS_ORIGINS, settings.BACKEND_EXTRA_CORS_ORIGINS]
    origins = {
        origin.strip().rstrip("/")
        for value in configured
        for origin in str(value or "").split(",")
        if origin.strip()
    }
    return origins


def _validate_origin(request: Request) -> None:
    """Reject browser requests from unexpected origins while allowing native MCP clients."""
    origin = request.headers.get("origin")
    if not origin:
        return
    normalized_origin = origin.rstrip("/")
    parsed = urlparse(normalized_origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or normalized_origin not in _allowed_origins():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="MCP origin is not allowed")


def _validate_request_size(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if content_length is None:
        return
    try:
        parsed_length = int(content_length)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Content-Length header") from exc
    if parsed_length > MCP_MAX_REQUEST_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="MCP request exceeds the allowed size")


async def _read_request_body(request: Request) -> bytes:
    """Read chunked requests with the same limit used for Content-Length."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MCP_MAX_REQUEST_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="MCP request exceeds the allowed size",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _mcp_response(payload: dict[str, Any] | None, protocol_version: str | None = None) -> Response:
    headers = {"Cache-Control": "no-store"}
    if protocol_version in MCP_SUPPORTED_PROTOCOL_VERSIONS:
        headers["MCP-Protocol-Version"] = protocol_version
    if payload is None:
        return Response(status_code=status.HTTP_202_ACCEPTED, headers=headers)
    return JSONResponse(content=payload, headers=headers)


@router.post("")
async def mcp_post(
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: deps.APIAccessTokenPrincipal = Depends(deps.get_current_active_api_token_principal),
) -> Response:
    """Serve stateless Streamable HTTP MCP requests at ``/api/v1/mcp``."""
    _validate_origin(request)
    _validate_request_size(request)
    try:
        payload = json.loads(await _read_request_body(request))
    except Exception:
        return _mcp_response(_jsonrpc_error(None, -32700, "Parse error"), request.headers.get("MCP-Protocol-Version"))
    response = handle_mcp_message(payload, db, current_user)
    response_version = request.headers.get("MCP-Protocol-Version")
    if not response_version and isinstance(response, dict):
        response_version = (response.get("result") or {}).get("protocolVersion")
    return _mcp_response(response, response_version)


@router.get("")
async def mcp_get(request: Request) -> Response:
    """This stateless server does not open server-to-client SSE streams."""
    _validate_origin(request)
    return Response(status_code=status.HTTP_405_METHOD_NOT_ALLOWED, headers={"Allow": "POST", "Cache-Control": "no-store"})
