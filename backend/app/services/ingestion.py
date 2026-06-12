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

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.job import Job
from app.services.storage import get_storage_service


def ingest_file_into_job(
    db: Session,
    job_id: str,
    file_bytes: bytes,
    filename: str,
    mime_type: Optional[str] = None,
    schema_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Store a file in a Job and enqueue OCR processing. Returns ids/task_id."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise ValueError(f"Job not found: {job_id}")

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
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    # Enqueue background OCR/extraction (same task the manual flow uses)
    from app.tasks.document_tasks import process_document_task
    task = process_document_task.delay(
        str(document.id),
        str(schema_id) if schema_id else None,
    )
    document.task_id = task.id
    db.add(document)
    db.commit()

    return {
        "document_id": str(document.id),
        "filename": filename,
        "task_id": task.id,
    }
