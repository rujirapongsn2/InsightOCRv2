"""
Celery background tasks for document processing.
Handles OCR and structure extraction asynchronously.
"""
import json
import logging
import os
from datetime import datetime
from celery import shared_task
from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models import Document, Job, User, DocumentSchema as SchemaModel
from app.services.ocr import process_ocr, count_pdf_pages
from app.services.structure import extract_structure
from app.services.storage import get_storage_service
from app.utils.activity_logger import log_activity, Actions
import requests
import re
from typing import Any, List

logger = logging.getLogger(__name__)


def table_to_key_values(content: str) -> List[str]:
    """
    Convert markdown pipe tables into key:value lines to help structure extraction.
    Only processes content that contains a real markdown table separator row (e.g. |---|---|).
    Returns empty list if no real table is detected, so caller falls back to original text.
    """
    # Only process if content has a real markdown table separator row
    has_separator = any(
        set(line.strip()) <= {"|", "-", " ", ":"} and "-" in line and "|" in line
        for line in content.splitlines()
        if line.strip()
    )
    if not has_separator:
        return []

    key_values = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Skip separator rows or malformed rows
        if set(line) <= {"|", "-", " ", ":"} or line.count("|") < 2:
            continue

        # Strip leading/trailing pipes then split
        parts = [p.strip().strip("*").strip(":") for p in line.strip("|").split("|")]
        if len(parts) >= 2 and parts[0]:
            key, value = parts[0], parts[1]
            if key or value:
                key_values.append(f"{key}: {value}")
    return key_values


def parse_extracted_json(extracted_data: Any) -> Any:
    """
    Parse extracted data from structure API response.
    """
    if extracted_data is None:
        return None

    # Handle 'answer' wrapper
    if isinstance(extracted_data, dict) and 'answer' in extracted_data:
        return parse_extracted_json(extracted_data['answer'])

    # Handle 'structured_output' wrapper
    if isinstance(extracted_data, dict) and 'structured_output' in extracted_data:
        return parse_extracted_json(extracted_data['structured_output'])

    # Handle 'data' wrapper
    if isinstance(extracted_data, dict) and 'data' in extracted_data and len(extracted_data) == 1:
        return parse_extracted_json(extracted_data['data'])

    # Try parsing string with code fences
    if isinstance(extracted_data, str):
        json_match = re.search(r'```json\s*\n(.*?)\n```', extracted_data, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(extracted_data)
        except json.JSONDecodeError:
            return {"extracted_text": extracted_data}

    # Normalize list responses
    if isinstance(extracted_data, list):
        parsed_list = []
        for item in extracted_data:
            parsed_item = parse_extracted_json(item)
            parsed_list.append(parsed_item if parsed_item is not None else item)
        return parsed_list

    # Handle extracted_text field
    if isinstance(extracted_data, dict) and 'extracted_text' in extracted_data:
        text = extracted_data['extracted_text']
        json_match = re.search(r'```json\s*\n(.*?)\n```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return extracted_data

    return extracted_data


@celery_app.task(bind=True, max_retries=3)
def process_document_task(self, document_id: str, schema_id: str):
    """
    Background task to process a document through OCR and structure extraction.
    
    Args:
        document_id: UUID of the document to process
        schema_id: UUID of the schema to use for extraction
    """
    db = SessionLocal()
    
    try:
        # Get document
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            logger.error(f"Document {document_id} not found")
            return {"status": "failed", "error": "Document not found"}

        # Update status to processing
        document.status = "processing"
        document.schema_id = schema_id
        db.add(document)
        db.commit()

        logger.info(f"Starting processing for document {document_id} with schema {schema_id}")

        # Use StorageService to get local path (handles download if remote)
        storage = get_storage_service()
        
        with storage.get_local_path(document.file_path) as local_file_path:
            logger.info(f"Processing using local file: {local_file_path}")

            # STEP 1: Count pages (PDF or Image)
            try:
                # Use original filename for extension check (temp files have no extension)
                file_ext = os.path.splitext(document.filename)[1].lower()

                if file_ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp']:
                    # Image files have only 1 page
                    page_count = 1
                    logger.info(f"Document {document_id} is an image file ({file_ext}), page_count=1")
                else:
                    # Assume PDF, use PDF page counter
                    page_count = count_pdf_pages(local_file_path)
                    logger.info(f"Document {document_id} is a PDF with {page_count} pages")

                document.page_count = page_count
                db.add(document)
                db.commit()
            except ValueError as e:
                document.status = "failed"
                document.processing_error = f"File validation failed: {str(e)}"
                db.add(document)
                db.commit()
                return {"status": "failed", "error": str(e)}
    
            # STEP 2: Process each page with OCR
            ocr_pages_results = []
            ocr_content_combined = ""
            ai_processing_warnings = []

            for page_num in range(1, page_count + 1):
                try:
                    # Call OCR for this specific page
                    ocr_result = process_ocr(
                        local_file_path,
                        db,
                        page_number=page_num,
                        filename=document.filename,
                        mime_type=document.mime_type
                    )

                    # Extract content from OCR API response
                    page_content = ""
                    page_success = False

                    if ocr_result.get('status') == 'success':
                        pages = ocr_result.get('results', {}).get('pages', [])

                        for page in pages:
                            if page.get('page_number') == page_num:
                                ai_processing = page.get('ai_processing', {})

                                # Handle both response formats:
                                # 1. ai_processing as dict with success/content fields
                                # 2. ai_processing as boolean, content in ocr_text field
                                page_content = ""

                                if isinstance(ai_processing, dict):
                                    # Try to get content from AI processing first
                                    if ai_processing.get('success', False):
                                        page_content = ai_processing.get('content', '')
                                    else:
                                        # Track AI processing failure
                                        ai_error = ai_processing.get('error', 'Unknown error')
                                        ai_processing_warnings.append(
                                            f"Page {page_num}: AI text enhancement failed ({ai_error}). Using raw OCR text."
                                        )
                                        logger.warning(f"AI processing failed for document {document_id} page {page_num}: {ai_error}")

                                    # Fallback to ocr_text if AI processing failed or no content
                                    if not page_content:
                                        page_content = page.get('ocr_text', '')
                                else:
                                    # Use ocr_text field if ai_processing is not a dict
                                    page_content = page.get('ocr_text', '')

                                page_success = bool(page_content.strip())

                                if page_success and page_content:
                                    ocr_content_combined += f"--- Page {page_num} Content ---\n"
                                    ocr_content_combined += page_content + "\n"

                    # Store page result
                    page_result = {
                        "page_number": page_num,
                        "success": page_success,
                        "content": page_content,
                        "confidence": None,
                        "processed_at": datetime.utcnow().isoformat(),
                        "error": None if page_success else "OCR processing returned no content"
                    }
                    ocr_pages_results.append(page_result)

                    # If any page fails, stop and fail entire document
                    if not page_success:
                        error_msg = f"Page {page_num} OCR processing failed"
                        document.status = "failed"
                        document.processing_error = error_msg
                        document.ocr_pages = ocr_pages_results
                        db.add(document)
                        db.commit()
                        return {"status": "failed", "error": error_msg}

                except requests.exceptions.RequestException as e:
                    # OCR API call failed for this page
                    error_msg = f"OCR API failed for page {page_num}: {str(e)}"
                    page_result = {
                        "page_number": page_num,
                        "success": False,
                        "content": None,
                        "confidence": None,
                        "processed_at": datetime.utcnow().isoformat(),
                        "error": str(e)
                    }
                    ocr_pages_results.append(page_result)

                    document.status = "failed"
                    document.processing_error = error_msg
                    document.ocr_pages = ocr_pages_results
                    db.add(document)
                    db.commit()
                    return {"status": "failed", "error": error_msg}

            # STEP 3: Store OCR results
            document.ocr_pages = ocr_pages_results
            document.ocr_text = ocr_content_combined
            if ai_processing_warnings:
                document.processing_error = "OCR quality degraded: " + "; ".join(ai_processing_warnings)
            db.add(document)
            db.commit()

        logger.info(f"OCR completed for document {document_id}, starting structure extraction")

        # STEP 4: Structure Extraction
        schema = db.query(SchemaModel).filter(SchemaModel.id == schema_id).first()
        if not schema:
            document.status = "failed"
            document.processing_error = "Schema not found"
            db.add(document)
            db.commit()
            return {"status": "failed", "error": "Schema not found"}

        # Normalize OCR text into key:value lines per page
        structure_context_parts = []
        for page_result in ocr_pages_results:
            content = page_result.get("content")
            if not content:
                continue

            kv_lines = table_to_key_values(content)
            normalized = "\n".join(kv_lines) if kv_lines else content
            structure_context_parts.append(f"Page {page_result.get('page_number')}:\n{normalized}")

        structure_context = "\n\n".join(structure_context_parts) if structure_context_parts else ocr_content_combined

        # Convert Schema fields to JSON Schema
        json_schema_dict = {
            "type": "object",
            "properties": {},
            "required": []
        }

        for field in schema.fields:
            field_name = field.get("name")
            json_schema_dict["properties"][field_name] = {
                "type": "string",
                "description": field.get("description", "")
            }
            if field.get("required"):
                json_schema_dict["required"].append(field_name)

        json_schema_str = json.dumps(json_schema_dict)

        # Call Structure Service
        extraction_prompt = (
            "Return a JSON array of objects that match the schema. "
            "If multiple people/records appear across pages, include one object per record. "
            "Fill missing values with null or an empty string."
        )

        try:
            structure_result = extract_structure(structure_context, json_schema_str, db, prompt=extraction_prompt)
            logger.info(f"Structure extraction result: {structure_result}")
        except Exception as structure_error:
            logger.error(f"Structure extraction exception: {structure_error}", exc_info=True)
            document.status = "failed"
            document.processing_error = f"Structure extraction error: {str(structure_error)}"
            db.add(document)
            db.commit()
            return {"status": "failed", "error": str(structure_error)}

        if structure_result.get('status') == 'success':
            raw_output = structure_result.get('structured_output')
            parsed_output = parse_extracted_json(raw_output)

            document.extracted_data = parsed_output if parsed_output is not None else raw_output
            document.status = "extraction_completed"

            # Check if extracted data has meaningful values (majority of fields populated)
            def _extraction_quality(data) -> float:
                """Return ratio of non-empty fields (0.0 to 1.0)."""
                if isinstance(data, dict):
                    fields = [v for v in data.values() if not isinstance(v, (dict, list))]
                    if not fields:
                        return 0.0
                    filled = sum(1 for v in fields if v and str(v).strip())
                    return filled / len(fields)
                if isinstance(data, list) and data:
                    return max(_extraction_quality(item) for item in data)
                return 0.0

            if not parsed_output or parsed_output == {} or (isinstance(parsed_output, dict) and 'extracted_text' in parsed_output):
                # Extraction produced no useful data — keep/append OCR warning
                parse_warning = f"Parse may be incomplete. Raw response preview: {str(raw_output)[:500]}"
                if document.processing_error:
                    document.processing_error += f" | {parse_warning}"
                else:
                    document.processing_error = parse_warning
            elif _extraction_quality(parsed_output) >= 0.5:
                # Majority of fields populated — OCR degradation didn't matter, clear warning
                document.processing_error = None
            # else: less than half populated — keep the OCR degraded warning as-is
        else:
            document.status = "failed"
            error_msg = structure_result.get('message', 'Unknown error')
            document.processing_error = f"Structure extraction failed: {error_msg}"

        db.add(document)
        db.commit()

        # Log activity
        if document.job and document.job.user_id:
            # Determine extraction status
            extraction_status = "completed" if document.status in ["extraction_completed", "reviewed"] else "failed" if document.status == "failed" else "processing"

            # Determine review status
            review_status = "reviewed" if document.reviewed_data or document.status == "reviewed" else "pending"

            log_activity(
                db=db,
                user_id=document.job.user_id,
                action=Actions.PROCESS_DOCUMENT,
                resource_type="document",
                resource_id=document.id,
                details={
                    "job_name": document.job.name or f"Job-{str(document.job.id)[:8]}",
                    "filename": document.filename,
                    "extraction_status": extraction_status,
                    "review_status": review_status,
                    "integration_status": None,  # Will be updated when sent to integration
                    "schema_id": str(schema_id) if schema_id else None,
                    "document_status": document.status
                }
            )

        logger.info(f"Document {document_id} processing completed with status: {document.status}")
        return {
            "status": document.status,
            "document_id": document_id,
            "extracted_data": document.extracted_data
        }

    except Exception as e:
        logger.exception(f"Processing failed for document {document_id}: {e}")
        
        # Update document status
        try:
            document = db.query(Document).filter(Document.id == document_id).first()
            if document:
                document.status = "failed"
                document.processing_error = f"Unexpected error: {str(e)}"
                db.add(document)
                db.commit()
        except:
            pass
        
        return {"status": "failed", "error": str(e)}
    
    finally:
        db.close()
