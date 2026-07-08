"""
Reusable file ingestion into a Job.

Mirrors the normal upload flow (api/v1/endpoints/documents.py: upload_document
+ process_document): store bytes → create Document → enqueue OCR processing.
Used by the cloud-drive import workflow nodes so a Drive/OneDrive file lands in
a Job exactly like a manual upload.
"""
import os
import uuid
from io import BytesIO
from typing import Any, Dict, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.job import Job
from app.services.storage import get_storage_service


class DuplicateSourceFile(Exception):
    """Raised when a source file was already imported into the job (dedup)."""


class UnsupportedFile(Exception):
    """Raised when an imported file violates the upload size/type limits."""


def _allowed_extensions() -> set:
    return {
        e.strip().lower()
        for e in settings.ALLOWED_UPLOAD_EXTENSIONS.split(",")
        if e.strip()
    }


def validate_import_file(filename: str, size_bytes: Optional[int]) -> None:
    """Enforce the same extension + size limits as the manual upload endpoint.

    ``size_bytes`` may be None (source metadata without a size) — in that case
    only the extension is checked here; the byte-count guard in
    ``ingest_file_into_job`` remains the authoritative size check after download.
    Raises ``UnsupportedFile`` on violation.
    """
    ext = os.path.splitext(filename or "")[1].lower()
    allowed = _allowed_extensions()
    if allowed and ext not in allowed:
        raise UnsupportedFile(
            f"ชนิดไฟล์ '{ext or 'unknown'}' ไม่รองรับ (อนุญาต: {', '.join(sorted(allowed))})"
        )
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if size_bytes is not None and size_bytes > max_bytes:
        raise UnsupportedFile(
            f"ไฟล์ใหญ่เกินไป ({size_bytes // (1024 * 1024)} MB) — "
            f"สูงสุด {settings.MAX_UPLOAD_SIZE_MB} MB"
        )


def ingest_file_into_job(
    db: Session,
    job_id: str,
    file_bytes: bytes,
    filename: str,
    mime_type: Optional[str] = None,
    schema_id: Optional[str] = None,
    source_file_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Store a file in a Job and enqueue OCR processing. Returns ids/task_id.

    If ``source_file_id`` is given and a document with that source already
    exists in the job, raises ``DuplicateSourceFile`` instead of re-importing.
    """
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise ValueError(f"Job not found: {job_id}")

    # Authoritative size/type guard: file_bytes is the real payload, so this
    # catches oversize files even when the source metadata reported no size.
    validate_import_file(filename, len(file_bytes))

    # Move job out of draft once a document arrives (same as upload_document)
    if job.status == "draft":
        job.status = "processing"
        db.add(job)

    file_ext = os.path.splitext(filename)[1]
    file_key = f"documents/{job_id}/{uuid.uuid4()}{file_ext}"
    storage = get_storage_service()
    storage.upload_file(BytesIO(file_bytes), file_key, content_type=mime_type)

    document = Document(
        job_id=job_id,
        filename=filename,
        file_path=file_key,
        file_size=len(file_bytes),
        mime_type=mime_type,
        status="queued",
        schema_id=schema_id or None,
        source_file_id=source_file_id or None,
    )
    db.add(document)
    try:
        db.commit()
    except IntegrityError:
        # Concurrent import run inserted the same (job_id, source_file_id)
        # first — the partial unique index rejected this one. Clean up the
        # already-uploaded storage object and signal a skip to the caller.
        db.rollback()
        try:
            storage.delete_file(file_key)
        except Exception:
            pass
        raise DuplicateSourceFile(source_file_id or filename)
    db.refresh(document)

    # Enqueue background OCR/extraction (same task the manual flow uses)
    from app.tasks.document_tasks import process_document_task
    try:
        task = process_document_task.delay(
            str(document.id),
            str(schema_id) if schema_id else None,
        )
    except Exception:
        # Broker unavailable — don't leave the document stuck in "queued".
        document.status = "failed"
        document.processing_error = "Failed to enqueue processing task (broker unavailable)"
        db.add(document)
        db.commit()
        raise
    document.task_id = task.id
    db.add(document)
    db.commit()

    return {
        "document_id": str(document.id),
        "filename": filename,
        "task_id": task.id,
    }
