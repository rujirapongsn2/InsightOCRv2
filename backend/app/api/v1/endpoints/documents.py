from typing import List, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from app.models.user import User
from sqlalchemy.orm import Session
from app.api import deps
from app.models.document import Document
from app.models.job import Job
from app.schemas.document import Document as DocumentSchema
from app.services.ocr import process_ocr
from app.services.structure import extract_structure
from app.models.setting import Setting
from app.models.schema import DocumentSchema as SchemaModel
from app.services.storage import get_storage_service
from app.utils.activity_logger import log_activity, Actions
import shutil
import os
import uuid
import requests
import warnings
import json
import re
import logging
from pydantic import BaseModel

# Configure logging for structure extraction debugging
logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = "/app/uploads" # Inside container
os.makedirs(UPLOAD_DIR, exist_ok=True)

def parse_extracted_json(extracted_data: Any) -> Any:
    """
    Parse extracted data from structure API response.
    Handles cases where JSON is embedded in markdown code blocks,
    wrapped in 'answer' field, or other common API response formats.

    Args:
        extracted_data: The structured_output from API

    Returns:
        Parsed JSON object or original data if already valid
    """
    if extracted_data is None:
        logger.warning("parse_extracted_json: received None")
        return None

    logger.info(f"parse_extracted_json: input type={type(extracted_data).__name__}, preview={str(extracted_data)[:300]}")

    # Handle 'answer' wrapper (some APIs wrap response in 'answer' field)
    if isinstance(extracted_data, dict) and 'answer' in extracted_data:
        logger.info("Unwrapping 'answer' field from response")
        return parse_extracted_json(extracted_data['answer'])

    # Handle 'structured_output' wrapper
    if isinstance(extracted_data, dict) and 'structured_output' in extracted_data:
        logger.info("Unwrapping 'structured_output' field from response")
        return parse_extracted_json(extracted_data['structured_output'])

    # Handle 'data' wrapper
    if isinstance(extracted_data, dict) and 'data' in extracted_data and len(extracted_data) == 1:
        logger.info("Unwrapping 'data' field from response")
        return parse_extracted_json(extracted_data['data'])

    # Try parsing when API returns a raw JSON string (or string with code fences)
    if isinstance(extracted_data, str):
        # Try markdown code block first
        json_match = re.search(r'```json\s*\n(.*?)\n```', extracted_data, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                logger.info(f"Successfully parsed JSON from markdown code block")
                return parsed
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse markdown JSON: {e}")

        # Try plain JSON string
        try:
            parsed = json.loads(extracted_data)
            logger.info(f"Successfully parsed plain JSON string")
            return parsed
        except json.JSONDecodeError:
            # Fall back to wrapping the string so UI can still display something meaningful
            logger.warning(f"Could not parse string as JSON, wrapping as extracted_text")
            return {"extracted_text": extracted_data}

    # Normalize list responses by parsing individual entries
    if isinstance(extracted_data, list):
        logger.info(f"Processing list with {len(extracted_data)} items")
        parsed_list = []
        for item in extracted_data:
            parsed_item = parse_extracted_json(item)
            parsed_list.append(parsed_item if parsed_item is not None else item)
        return parsed_list

    # Check if data has 'extracted_text' key (markdown format)
    if isinstance(extracted_data, dict) and 'extracted_text' in extracted_data:
        text = extracted_data['extracted_text']
        logger.info("Processing extracted_text field")

        # Try to extract JSON from markdown code block
        json_match = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
        if json_match:
            try:
                parsed = json.loads(json_match.group(1))
                logger.info("Successfully parsed JSON from extracted_text markdown")
                return parsed
            except json.JSONDecodeError:
                pass

        # Try to extract JSON without markdown
        try:
            parsed = json.loads(text)
            logger.info("Successfully parsed JSON from extracted_text")
            return parsed
        except json.JSONDecodeError:
            # Return original text if can't parse
            logger.warning("Could not parse extracted_text as JSON")
            return extracted_data

    # Return as-is if already in correct format (dict with actual data)
    if isinstance(extracted_data, dict):
        logger.info(f"Returning dict as-is with keys: {list(extracted_data.keys())}")
    return extracted_data


def table_to_key_values(content: str) -> List[str]:
    """
    Convert simple markdown pipe tables into key:value lines to help structure extraction.
    """
    key_values = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Skip separator rows or malformed rows
        if set(line) <= {"|", "-", " "} or line.count("|") < 2:
            continue

        # Strip leading/trailing pipes then split
        parts = [p.strip().strip("*").strip(":") for p in line.strip("|").split("|")]
        if len(parts) >= 2 and parts[0]:
            key, value = parts[0], parts[1]
            if key or value:
                key_values.append(f"{key}: {value}")
    return key_values

@router.get("/job/{job_id}", response_model=List[DocumentSchema])
def read_job_documents(
    *,
    db: Session = Depends(deps.get_db),
    job_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    List documents belonging to a job.
    """
    documents = db.query(Document).filter(Document.job_id == job_id).all()
    return documents

@router.post("/upload", response_model=DocumentSchema)
async def upload_document(
    *,
    db: Session = Depends(deps.get_db),
    job_id: str = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Upload a document and trigger OCR.
    """
    # Verify job exists
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Move job out of draft once a document is uploaded
    if job.status == "draft":
        job.status = "processing"
        db.add(job)

    # Upload file via StorageService
    file_ext = os.path.splitext(file.filename)[1]
    # Use a relative path key: documents/{job_id}/{uuid}{ext}
    file_key = f"documents/{job_id}/{uuid.uuid4()}{file_ext}"
    
    storage = get_storage_service()
    try:
        storage.upload_file(file.file, file_key, content_type=file.content_type)
    except Exception as e:
        logger.error(f"Failed to upload file: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
    
    # Create Document record
    db_document = Document(
        job_id=job_id,
        filename=file.filename,
        file_path=file_key, # Store the key, not absolute path
        mime_type=file.content_type,
        status="uploaded"
    )
    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    
    return db_document

class ProcessRequest(BaseModel):
    schema_id: uuid.UUID

class ProcessResponse(BaseModel):
    document_id: str
    task_id: str
    status: str
    message: str

@router.post("/{document_id}/process", response_model=ProcessResponse)
def process_document(
    *,
    db: Session = Depends(deps.get_db),
    document_id: str,
    process_request: ProcessRequest,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Queue a document for background processing: Page Counting -> Multi-Page OCR -> Structure Extraction.
    Returns immediately with task_id for status polling.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Update schema_id and queue status
    document.schema_id = process_request.schema_id
    document.status = "queued"
    document.processing_error = None  # Clear any previous errors
    db.add(document)
    db.commit()

    # Import and dispatch Celery task
    from app.tasks.document_tasks import process_document_task
    
    task = process_document_task.delay(str(document.id), str(process_request.schema_id))
    
    logger.info(f"Dispatched processing task {task.id} for document {document_id}")

    return ProcessResponse(
        document_id=str(document.id),
        task_id=task.id,
        status="queued",
        message="Document processing started in background. Poll /task-status for updates."
    )

class TaskStatusResponse(BaseModel):
    document_id: str
    status: str
    extracted_data: Any = None
    processing_error: Optional[str] = None
    page_count: Optional[int] = None

@router.get("/{document_id}/task-status", response_model=TaskStatusResponse)
def get_task_status(
    *,
    db: Session = Depends(deps.get_db),
    document_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get current processing status of a document.
    Used for polling after process_document dispatches a background task.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return TaskStatusResponse(
        document_id=str(document.id),
        status=document.status,
        extracted_data=document.extracted_data,
        processing_error=document.processing_error,
        page_count=document.page_count
    )

@router.get("/{document_id}", response_model=DocumentSchema)
def read_document(
    *,
    db: Session = Depends(deps.get_db),
    document_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Get document by ID.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document

@router.post("/extract-ocr")
async def extract_ocr_for_suggestion(
    *,
    db: Session = Depends(deps.get_db),
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Extract OCR text from uploaded document for AI field suggestion.
    This endpoint doesn't create a permanent document record.
    """
    # Validate file type
    allowed_types = ["application/pdf", "image/jpeg", "image/jpg", "image/png"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only PDF, JPG, and PNG are allowed."
        )

    # Save file temporarily
    file_ext = os.path.splitext(file.filename)[1]
    file_name = f"temp_{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, file_name)

    try:
        # Save file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Process OCR
        ocr_result = process_ocr(file_path, db, filename=file.filename, mime_type=file.content_type)

        # Extract text content
        ocr_content = ""
        if ocr_result.get('status') == 'success':
            pages = ocr_result.get('results', {}).get('pages', [])
            for page in pages:
                page_num = page.get('page_number')
                ocr_content += f"--- Page {page_num} ---\n"
                
                # Try AI processing first
                ai_processing = page.get('ai_processing', {})
                if ai_processing.get('success') and ai_processing.get('content'):
                    ocr_content += ai_processing.get('content', '') + "\n\n"
                # Fallback to raw OCR text if AI processing failed or empty
                elif page.get('ocr_text'):
                    ocr_content += page.get('ocr_text', '') + "\n\n"

        if not ocr_content:
            raise HTTPException(
                status_code=400,
                detail="No text could be extracted from the document"
            )

        return {
            "status": "success",
            "ocr_text": ocr_content,
            "text_content": ocr_content,
            "filename": file.filename,
            "pages": len(pages) if 'pages' in locals() else 1
        }

    except ValueError as e:
        # Settings not configured or valid
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        logger.exception(f"OCR extraction failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"OCR extraction failed: {str(e)}"
        )
    finally:
        # Cleanup temporary file
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass

from app.schemas.document import DocumentUpdate

@router.put("/{document_id}", response_model=DocumentSchema)
def update_document(
    *,
    db: Session = Depends(deps.get_db),
    document_id: str,
    document_in: DocumentUpdate,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Update document (e.g. save review data).
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    update_data = document_in.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(document, field, value)
    
    # If reviewed_data is present, we can mark as reviewed if status not explicitly set
    if "reviewed_data" in update_data and "status" not in update_data:
        document.status = "reviewed"

    # Keep parent job status in sync with document review lifecycle
    if document.status == "reviewed" and document.job:
        document.job.status = "review"

    db.add(document)
    db.commit()
    db.refresh(document)
    return document

@router.get("/{document_id}/file")
def download_document_file(
    *,
    db: Session = Depends(deps.get_db),
    document_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Download/view the original document file.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    storage = get_storage_service()
    
    # If local, strictly validate and return FileResponse
    from app.core.config import settings
    if settings.STORAGE_TYPE == "local":
        # For local storage, the file_path in DB might be relative or absolute (legacy)
        # StorageService handles relative paths, but we need absolute for FileResponse
        try:
             # Use StorageService's internal logic to get full path if it's a LocalStorage instance
             # But here we can't easily access that without using private methods or get_local_path logic
             # Let's rely on standard check if we assume it's relative to UPLOAD_DIR
             full_path = os.path.abspath(os.path.join(UPLOAD_DIR, document.file_path))
             
             # Fallback for absolute paths from legacy data
             if os.path.isabs(document.file_path):
                 full_path = document.file_path
                 
             if not os.path.exists(full_path):
                 raise HTTPException(status_code=404, detail="File not found on server")
                 
             # Traversal check
             if not os.path.abspath(full_path).startswith(os.path.abspath(UPLOAD_DIR)):
                 raise HTTPException(status_code=400, detail="Invalid file path")
                 
             return FileResponse(
                path=full_path,
                media_type=document.mime_type or "application/pdf",
                filename=document.filename
            )
        except Exception as e:
            logger.error(f"Download error: {e}")
            raise HTTPException(status_code=404, detail="File not found")

    # For remote storage, download from storage and stream to client
    with storage.get_local_path(document.file_path) as local_file_path:
        # get_local_path returns a file path string, not a file object
        # Read file content into memory before context manager exits
        with open(local_file_path, 'rb') as f:
            file_content = f.read()

        def iter_file():
            yield file_content

        return StreamingResponse(
            iter_file(),
            media_type=document.mime_type or "application/pdf",
            headers={"Content-Disposition": f'inline; filename="{document.filename}"'}
        )

@router.delete("/{document_id}")
def delete_document(
    *,
    db: Session = Depends(deps.get_db),
    document_id: str,
    current_user: User = Depends(deps.get_current_active_user),
) -> Any:
    """
    Delete a document and its associated file.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check if user has permission to delete (owner or admin)
    # Assuming documents are associated with jobs owned by users
    if document.job_id:
        job = db.query(Job).filter(Job.id == document.job_id).first()
        if job and job.user_id != current_user.id and not current_user.is_admin:
            raise HTTPException(status_code=403, detail="Not enough permissions")

    try:
        # Store filename for logging
        filename = document.filename

        # Delete file from storage
        storage = get_storage_service()
        storage.delete_file(document.file_path)

        # Delete document from database
        db.delete(document)
        db.commit()

        # Log activity
        log_activity(
            db=db,
            user_id=current_user.id,
            action=Actions.DELETE_DOCUMENT,
            resource_type="document",
            resource_id=document_id,
            details={"filename": filename}
        )

        return {"message": "Document deleted successfully", "id": document_id}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete document {document_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")
