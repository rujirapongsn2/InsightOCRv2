"""
Celery background tasks for document processing.
Handles OCR and structure extraction asynchronously.
"""
import json
import logging
import os
import time
from datetime import datetime
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models import Document, DocumentSchema as SchemaModel, Setting
from app.services.storage import get_storage_service
from app.utils.activity_logger import log_activity, Actions
from app.utils.job_logger import get_job_logger
import requests
import re
import redis as redis_lib
import threading
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

    # Keep structured dict payloads intact (e.g. schema_source/data/success envelopes)
    if isinstance(extracted_data, dict):
        return extracted_data

    return extracted_data


def _to_snake_key(text: str) -> str:
    """Normalize a label string to a snake_case dict key."""
    key = text.strip().strip("*").strip("-").strip()
    key = re.sub(r'\s+', '_', key.lower())
    key = re.sub(r'[^a-z0-9_]', '', key)
    return key


def _looks_like_label(text: str) -> bool:
    """Return True if text looks like a field label (short, no sentence punctuation)."""
    t = text.strip()
    if not t or len(t) > 60:
        return False
    # Labels are short and don't look like addresses or sentences
    if re.search(r'\d{4,}', t):  # long numbers → address/date value
        return False
    if t.count(',') >= 2:  # multiple commas → address value
        return False
    return True


def extract_structured_from_markdown(content: str) -> dict[str, Any] | None:
    """
    Extract structured key-value fields from AI-generated markdown content.
    Used as fallback when the external API does not return structured_output.
    Handles:
      - Inline bold labels: **Key:** value
      - Bullet bold labels: - **Key:** value
      - Multi-column data tables: | No. | Description | ... |
    """
    if not content or not isinstance(content, str):
        return None

    result: dict[str, Any] = {}

    # Pattern 0: ## Section heading followed by value on the next non-empty line(s)
    # e.g.  ## Shipping Terms\nFOB Shenzhen
    # Also handles multi-line section bodies like Buyer/Seller blocks
    lines = content.splitlines()
    section_header_re = re.compile(r'^#{1,3}\s+(.+)')
    skip_section_keywords = {
        "order items", "authorization", "authorized", "accepted",
        "purchase order", "invoice", "receipt", "document",
    }
    i_sec = 0
    while i_sec < len(lines):
        hdr_match = section_header_re.match(lines[i_sec].strip())
        if hdr_match:
            section_name = hdr_match.group(1).strip().strip(":").strip()
            # Skip sections that are really block-level containers, not single values
            if section_name.lower() in skip_section_keywords or not _looks_like_label(section_name):
                i_sec += 1
                continue
            # Collect the body lines until next heading or table or blank+blank
            body_lines = []
            j = i_sec + 1
            blank_count = 0
            while j < len(lines):
                l = lines[j].strip()
                if section_header_re.match(l):
                    break
                if l.startswith('|'):
                    break
                if not l:
                    blank_count += 1
                    if blank_count >= 2:
                        break
                    j += 1
                    continue
                blank_count = 0
                body_lines.append(l)
                j += 1

            body = ' '.join(body_lines).strip()
            # Only store if body is a concise value (not a long paragraph)
            if body and len(body) <= 200:
                norm_key = _to_snake_key(section_name)
                if norm_key and norm_key not in result:
                    result[norm_key] = body
                elif norm_key:
                    idx = 2
                    while f"{norm_key}_{idx}" in result:
                        idx += 1
                    result[f"{norm_key}_{idx}"] = body
        i_sec += 1

    # Pattern 1: bold inline/bullet labels:  **Key:** value  or  - **Key:** value
    bold_label_pattern = re.compile(
        r'(?:^|\n)\s*(?:-\s*)?\*{1,2}([^*\n:]{2,60}?)\*{0,2}\s*:\s*([^\n]+)',
    )
    for match in bold_label_pattern.finditer(content):
        raw_key = match.group(1).strip().strip("*").strip("-").strip()
        raw_val = match.group(2).strip().strip("*").strip()
        if not raw_key or not raw_val:
            continue
        if not _looks_like_label(raw_key):
            continue
        norm_key = _to_snake_key(raw_key)
        if not norm_key:
            continue
        if norm_key not in result:
            result[norm_key] = raw_val
        else:
            # Append numbered suffix for duplicate keys
            idx = 2
            while f"{norm_key}_{idx}" in result:
                idx += 1
            result[f"{norm_key}_{idx}"] = raw_val

    # Pattern 2: parse pipe tables — collect each table block separately
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Detect start of a pipe table
        if not (line.startswith('|') and line.endswith('|') and line.count('|') >= 2):
            i += 1
            continue

        # Collect all lines of this table block
        table_lines = []
        while i < len(lines):
            tl = lines[i].strip()
            if tl.startswith('|') and tl.endswith('|'):
                table_lines.append(tl)
                i += 1
            else:
                break

        if len(table_lines) < 2:
            continue

        # Parse header row
        sep_re = re.compile(r'^\|[-| :]+\|$')
        raw_rows: list[list[str]] = []
        for tl in table_lines:
            if sep_re.match(tl):
                continue
            cells = [c.strip().strip('*') for c in tl.strip('|').split('|')]
            raw_rows.append(cells)

        if not raw_rows:
            continue

        header_cells = raw_rows[0]
        data_rows = raw_rows[1:]

        # Determine if this is a multi-column data table (e.g. items list)
        # by checking if header has >= 3 columns or looks like an item table
        item_keywords = {"no", "no.", "#", "item", "description", "desc", "qty", "sku", "unit", "price"}
        header_lower = {h.lower() for h in header_cells if h}
        is_item_table = (
            len(header_cells) >= 3
            or bool(header_lower & item_keywords)
        )

        if is_item_table and data_rows:
            items = []
            for row in data_rows:
                # Pad/truncate row to header length
                padded = (row + [''] * len(header_cells))[:len(header_cells)]
                item: dict[str, Any] = {}
                for h, v in zip(header_cells, padded):
                    if h and v:
                        k = _to_snake_key(h)
                        if k:
                            item[k] = v
                if item:
                    items.append(item)
            if items:
                result["items"] = items
        elif len(header_cells) == 2 and data_rows:
            # Two-column key/value table — only use if header looks like field labels
            # AND the two header values are different (not a Buyer/Seller-style category table)
            h0, h1 = header_cells[0], header_cells[1]
            # Skip if both headers are category names (e.g. Buyer: / Seller:) not field/value
            both_categories = (
                _looks_like_label(h0) and _looks_like_label(h1)
                and h0.lower().rstrip(':') != 'field'
                and not any(kw in h1.lower() for kw in ('value', 'amount', 'detail', 'info'))
                and h1.strip() not in ('', )
            )
            if both_categories:
                # Check if data rows look like key/value (col1 short label, col2 longer value)
                # Skip this table block — it's a side-by-side category table
                pass
            else:
                all_pairs = [(h0, h1)] + [(r[0], r[1]) for r in data_rows if len(r) >= 2]
                for col1, col2 in all_pairs:
                    if _looks_like_label(col1) and col2:
                        k = _to_snake_key(col1)
                        if k:
                            result[k] = col2

    if not result:
        return None

    return result


def extract_key_fields_from_text(content: str) -> dict[str, Any]:
    """
    Extract common invoice header fields from raw OCR/AI text.
    This is a fallback for documents where the structured response is partial.
    """
    if not content or not isinstance(content, str):
        return {}

    result: dict[str, Any] = {}
    lines = [line.strip() for line in content.splitlines()]

    def set_if_missing(key: str, value: str | None) -> None:
        if not value:
            return
        value = value.strip()
        if not value:
            return
        if key not in result or result[key] in (None, "", [], {}):
            result[key] = value

    def is_boundary(line: str) -> bool:
        normalized = line.strip().replace("：", ":")
        return bool(re.match(
            r"^(?:"
            r"invoice\s*no\.?|document\s*no\.?|doc\s*no\.?|no\.?|เลขที่|หมายเลขเอกสาร|"
            r"invoice\s*date|document\s*date|date|วันที่|"
            r"buyer|ผู้ซื้อ|seller|ผู้ขาย|customer|vendor|supplier|"
            r"item|items|line\s*items|description|qty|quantity|unit\s*price|amount|"
            r"summary|totals?|total|vat|grand\s*total|รวมเงิน|ภาษี"
            r")\b",
            normalized,
            re.IGNORECASE,
        ))

    def extract_after_colon(text: str) -> str:
        return text.split(":", 1)[1].strip() if ":" in text else ""

    current_block: str | None = None
    block_lines: list[str] = []

    def flush_block() -> None:
        nonlocal current_block, block_lines
        if current_block and block_lines:
            value = " ".join(part for part in block_lines if part).strip()
            set_if_missing(current_block, value)
        current_block = None
        block_lines = []

    for line in lines:
        if not line:
            continue

        normalized = line.replace("：", ":").strip()

        doc_no_match = re.match(
            r"^(?:document\s*no\.?|doc\s*no\.?|invoice\s*no\.?|no\.?|เลขที่|หมายเลขเอกสาร)\s*(?:\([^)]*\))?\s*:\s*(.+)$",
            normalized,
            re.IGNORECASE,
        )
        if doc_no_match:
            set_if_missing("document_number", doc_no_match.group(1))
            continue

        date_match = re.match(
            r"^(?:document\s*date|invoice\s*date|date|วันที่)\s*(?:\([^)]*\))?\s*:\s*(.+)$",
            normalized,
            re.IGNORECASE,
        )
        if date_match:
            set_if_missing("document_date", date_match.group(1))
            continue

        seller_label = re.match(
            r"^(?:seller|ผู้ขาย|vendor|supplier)\s*(?:\([^)]*\))?\s*:?\s*(.*)$",
            normalized,
            re.IGNORECASE,
        )
        if seller_label and seller_label.group(0).lower().startswith(("seller", "ผู้ขาย", "vendor", "supplier")):
            flush_block()
            current_block = "seller"
            initial = seller_label.group(1).strip() or extract_after_colon(normalized)
            if initial:
                block_lines.append(initial)
            continue

        buyer_label = re.match(
            r"^(?:buyer|ผู้ซื้อ|customer|bill to|ship to)\s*(?:\([^)]*\))?\s*:?\s*(.*)$",
            normalized,
            re.IGNORECASE,
        )
        if buyer_label and buyer_label.group(0).lower().startswith(("buyer", "ผู้ซื้อ", "customer", "bill to", "ship to")):
            flush_block()
            current_block = "buyer"
            initial = buyer_label.group(1).strip() or extract_after_colon(normalized)
            if initial:
                block_lines.append(initial)
            continue

        if current_block:
            if is_boundary(normalized):
                flush_block()
            else:
                block_lines.append(normalized)
                continue

        inline_match = re.match(r"^(.{1,60}?)\s*:\s*(.+)$", normalized)
        if inline_match:
            label = inline_match.group(1).strip().lower()
            value = inline_match.group(2).strip()
            if any(token in label for token in ("เลขที่", "document no", "invoice no", "doc no", "no.")):
                set_if_missing("document_number", value)
            elif any(token in label for token in ("วันที่", "document date", "invoice date", "date")):
                set_if_missing("document_date", value)
            elif any(token in label for token in ("seller", "ผู้ขาย", "vendor", "supplier")):
                set_if_missing("seller", value)
            elif any(token in label for token in ("buyer", "ผู้ซื้อ", "customer", "bill to", "ship to")):
                set_if_missing("buyer", value)

    flush_block()
    return result


def merge_missing_fields(primary: Any, fallback: dict[str, Any]) -> Any:
    if not isinstance(primary, dict) or not fallback:
        return primary

    merged = dict(primary)
    for key, value in fallback.items():
        if key not in merged or merged[key] in (None, "", [], {}):
            merged[key] = value
    return merged


def map_field_type_to_json_schema(field_type: str, field_description: str) -> dict[str, Any]:
    normalized_type = (field_type or "text").lower()

    if normalized_type == "array":
        return {
            "type": "array",
            "description": field_description,
            "items": {"type": "object"},
        }
    if normalized_type in {"number", "currency"}:
        return {"type": "number", "description": field_description}
    if normalized_type == "boolean":
        return {"type": "boolean", "description": field_description}
    if normalized_type == "date":
        return {"type": "string", "format": "date", "description": field_description}

    return {"type": "string", "description": field_description}


def build_schema_json(schema: SchemaModel | None) -> str:
    if not schema:
        return ""

    properties: dict[str, Any] = {}
    required_fields: list[str] = []

    for field in schema.fields or []:
        field_name = (field.get("name") or "").strip()
        if not field_name:
            continue

        properties[field_name] = map_field_type_to_json_schema(
            field.get("type", "text"),
            field.get("description", ""),
        )
        if field.get("required"):
            required_fields.append(field_name)

    json_schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required_fields,
    }

    return json.dumps(json_schema)


def extract_job_id(payload: dict[str, Any]) -> str | None:
    for key in ("job_id", "task_id", "id", "request_id"):
        value = payload.get(key)
        if value:
            return str(value)

    nested = payload.get("data")
    if isinstance(nested, dict):
        for key in ("job_id", "task_id", "id", "request_id"):
            value = nested.get(key)
            if value:
                return str(value)

    return None


def extract_status(payload: dict[str, Any]) -> str:
    for key in ("status", "state"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()

    nested = payload.get("data")
    if isinstance(nested, dict):
        for key in ("status", "state"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().lower()

    return ""


def extract_ai_text(result_payload: dict[str, Any]) -> str:
    def append_unique(parts: list[str], value: Any) -> None:
        if isinstance(value, str):
            text = value.strip()
            if text and text not in parts:
                parts.append(text)

    ai_processing = result_payload.get("ai_processing")
    if isinstance(ai_processing, str):
        return ai_processing.strip()

    combined_parts: list[str] = []
    if isinstance(ai_processing, dict):
        for key in ("content", "text", "output", "result"):
            append_unique(combined_parts, ai_processing.get(key))

    pages = result_payload.get("results", {}).get("pages")
    if not isinstance(pages, list):
        pages = result_payload.get("pages") if isinstance(result_payload.get("pages"), list) else []

    for page in pages:
        if not isinstance(page, dict):
            continue

        page_ai = page.get("ai_processing")
        page_parts: list[str] = []
        if isinstance(page_ai, dict):
            for key in ("content", "text", "output", "result"):
                append_unique(page_parts, page_ai.get(key))
        elif isinstance(page_ai, str) and page_ai.strip():
            append_unique(page_parts, page_ai)

        fallback_ocr_text = page.get("ocr_text")
        append_unique(page_parts, fallback_ocr_text)

        for part in page_parts:
            append_unique(combined_parts, part)

    return "\n\n".join(combined_parts).strip()


def extract_structured_data(result_payload: dict[str, Any]) -> Any:
    combined_text = extract_ai_text(result_payload)
    text_extracted = extract_key_fields_from_text(combined_text)

    candidate_paths = [
        result_payload.get("structured_data"),
        result_payload.get("data", {}).get("structured_data") if isinstance(result_payload.get("data"), dict) else None,
        result_payload.get("result", {}).get("structured_data") if isinstance(result_payload.get("result"), dict) else None,
        result_payload.get("results", {}).get("structured_data") if isinstance(result_payload.get("results"), dict) else None,
        result_payload.get("results", {}).get("structured_output") if isinstance(result_payload.get("results"), dict) else None,
        result_payload.get("structured_output"),
    ]

    for candidate in candidate_paths:
        if candidate is None:
            continue
        # Unwrap structured_output envelope {"schema_source":..., "data":{...}}
        if isinstance(candidate, dict) and "schema_source" in candidate and "data" in candidate:
            inner = candidate["data"]
            if inner not in (None, {}, []):
                return merge_missing_fields(inner, text_extracted)
            continue
        parsed = parse_extracted_json(candidate)
        if parsed not in (None, {}, []):
            if isinstance(parsed, dict):
                return merge_missing_fields(parsed, text_extracted)
            return parsed

    pages = result_payload.get("results", {}).get("pages")
    if not isinstance(pages, list):
        pages = result_payload.get("pages") if isinstance(result_payload.get("pages"), list) else []

    for page in pages:
        if not isinstance(page, dict):
            continue

        page_candidates = [
            page.get("structured_data"),
            page.get("structured_output"),
            page.get("result"),
        ]

        page_ai = page.get("ai_processing")
        if isinstance(page_ai, dict):
            page_candidates.extend(
                [
                    page_ai.get("structured_data"),
                    page_ai.get("structured_output"),
                    page_ai.get("result"),
                ]
            )

        for candidate in page_candidates:
            if candidate is None:
                continue
            parsed = parse_extracted_json(candidate)
            if parsed not in (None, {}, []):
                if isinstance(parsed, dict):
                    return merge_missing_fields(parsed, text_extracted)
                return parsed

    # Fallback: extract structured fields from ai_processing.content markdown
    # (used in Auto mode when the external API returns no structured_output)
    combined_content_parts: list[str] = []
    if not isinstance(pages, list):
        pages = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_ai = page.get("ai_processing")
        if isinstance(page_ai, dict):
            for key in ("content", "text", "output", "result"):
                value = page_ai.get(key)
                if isinstance(value, str) and value.strip():
                    combined_content_parts.append(value.strip())
        elif isinstance(page_ai, str) and page_ai.strip():
            combined_content_parts.append(page_ai.strip())

        fallback_ocr_text = page.get("ocr_text")
        if isinstance(fallback_ocr_text, str) and fallback_ocr_text.strip():
            combined_content_parts.append(fallback_ocr_text.strip())

    if combined_content_parts:
        combined = "\n\n".join(combined_content_parts)
        markdown_extracted = extract_structured_from_markdown(combined)
        if markdown_extracted not in (None, {}):
            return merge_missing_fields(markdown_extracted, text_extracted)

        if text_extracted:
            return text_extracted

    return None


@celery_app.task(bind=True, max_retries=3)
def process_document_task(self, document_id: str, schema_id: str | None = None):
    """
    Background task to process a document through external AI processing API.
    
    Args:
        document_id: UUID of the document to process
        schema_id: UUID of selected schema, or None for Auto mode
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
        db.add(document)
        db.commit()

        # Initialize job logger if we have a job
        job_logger = get_job_logger(str(document.job_id)) if document.job_id else logger
        
        job_logger.info(f"Starting processing for document {document.filename} (ID: {document_id}) with schema {schema_id}")

        setting = db.query(Setting).first()
        if not setting:
            raise ValueError("Settings not configured. Please configure OCR endpoint and API token in Settings.")

        ocr_endpoint = setting.ocr_endpoint or setting.api_endpoint
        if not ocr_endpoint or not setting.api_token:
            raise ValueError("OCR Processing Endpoint and API token are required in Settings.")

        verify_ssl = setting.verify_ssl if setting.verify_ssl is not None else False
        ocr_engine = setting.ocr_engine if setting.ocr_engine and setting.ocr_engine != "default" else "tesseract"
        model = "" if not setting.model or setting.model == "default" else setting.model

        schema = None
        if schema_id:
            schema = db.query(SchemaModel).filter(SchemaModel.id == schema_id).first()
            if not schema:
                raise ValueError("Selected schema not found")

        schema_source = "auto" if not schema else f"schema:{schema.name}"
        job_logger.info(
            f"Starting processing for document {document.filename} (ID: {document_id}) "
            f"using schema_source={schema_source}"
        )

        document.schema_id = schema.id if schema else None
        db.add(document)
        db.commit()

        json_schema_str = build_schema_json(schema)

        storage = get_storage_service()
        with storage.get_local_path(document.file_path) as local_file_path:
            headers = {
                "accept": "application/json",
                "Authorization": f"Bearer {setting.api_token}",
            }
            data = {
                "ocr_engine": ocr_engine,
                "prompt": "",
                "pages": "",
                "image_size": "",
                "model": model,
                "callback_url": "",
                "structure_model": "",
            }
            if json_schema_str.strip():
                data["json_schema"] = json_schema_str
            else:
                # For Auto mode, keep an explicit empty field to request auto structured output.
                data["json_schema"] = ""

            upload_filename = document.filename or os.path.basename(local_file_path)
            content_type = document.mime_type or "application/octet-stream"

            submit_payload: dict[str, Any] | None = None
            final_result: dict[str, Any] | None = None
            external_job_id: str | None = None
            failed_statuses = {"failed", "error", "cancelled", "canceled"}

            # Setup Redis progress key (used by /task-status endpoint)
            _redis_prog: redis_lib.Redis | None = None
            _redis_prog_key = f"doc_progress:{document_id}"
            try:
                from app.core.config import settings as _cfg
                _redis_prog = redis_lib.from_url(_cfg.REDIS_URL, decode_responses=True)
            except Exception:
                _redis_prog = None

            def _set_progress(percent: int, stage: str) -> None:
                if _redis_prog:
                    try:
                        _redis_prog.set(_redis_prog_key, json.dumps({"percent": percent, "stage": stage, "message": ""}), ex=1800)
                    except Exception:
                        pass

            # Simulated progress ticker: advances through stages while submit blocks
            _stop_ticker = threading.Event()
            def _progress_ticker() -> None:
                stages = [
                    (5,  "uploading"),
                    (15, "uploading"),
                    (25, "ocr"),
                    (40, "ocr"),
                    (55, "ai_processing"),
                    (70, "ai_processing"),
                    (82, "schema_generation"),
                    (92, "structured_extraction"),
                ]
                for pct, stg in stages:
                    if _stop_ticker.wait(timeout=4.0):
                        break
                    _set_progress(pct, stg)

            _set_progress(0, "queuing")

            submit_variants = [data]
            if not json_schema_str.strip():
                submit_variants.append({k: v for k, v in data.items() if k != "json_schema"})

            _ticker_thread = threading.Thread(target=_progress_ticker, daemon=True)
            _ticker_thread.start()

            for attempt_index, submit_data in enumerate(submit_variants, start=1):
                # Retry submit up to 3 times on transient SSL/connection errors
                ssl_retries = 3
                submit_response = None
                for ssl_attempt in range(1, ssl_retries + 1):
                    try:
                        with open(local_file_path, "rb") as file_stream:
                            submit_response = requests.post(
                                ocr_endpoint,
                                headers=headers,
                                data=submit_data,
                                files={"file": (upload_filename, file_stream, content_type)},
                                timeout=180,
                                verify=verify_ssl,
                            )
                        break
                    except requests.exceptions.SSLError as ssl_err:
                        if ssl_attempt < ssl_retries:
                            job_logger.warning(
                                f"SSL error on submit attempt {ssl_attempt}/{ssl_retries}, retrying in 5s: {ssl_err}"
                            )
                            time.sleep(5)
                        else:
                            raise
                    except requests.exceptions.ConnectionError as conn_err:
                        if ssl_attempt < ssl_retries:
                            job_logger.warning(
                                f"Connection error on submit attempt {ssl_attempt}/{ssl_retries}, retrying in 5s: {conn_err}"
                            )
                            time.sleep(5)
                        else:
                            raise

                try:
                    submit_response.raise_for_status()
                except requests.HTTPError:
                    response_text = submit_response.text.lower()
                    can_retry = attempt_index < len(submit_variants)
                    if can_retry and "invalid json schema" in response_text:
                        job_logger.warning(
                            "External submit rejected json_schema for Auto mode; retrying without json_schema field"
                        )
                        continue
                    raise

                # Stop the progress ticker now that submit has returned
                _stop_ticker.set()
                _set_progress(95, "structured_extraction")

                submit_payload = submit_response.json()
                external_job_id = extract_job_id(submit_payload)
                submit_status = extract_status(submit_payload)
                job_logger.info(f"Submit payload keys: {list(submit_payload.keys()) if isinstance(submit_payload, dict) else type(submit_payload).__name__}; external_job_id={external_job_id}; status={submit_status}")

                if not external_job_id and submit_status in failed_statuses:
                    payload_text = json.dumps(submit_payload).lower()
                    can_retry = attempt_index < len(submit_variants)
                    if can_retry and "invalid json schema" in payload_text:
                        job_logger.warning(
                            "External submit failed due to invalid json_schema in Auto mode; retrying without json_schema"
                        )
                        continue
                    raise ValueError(f"External OCR submit failed: {submit_payload}")

                final_result = submit_payload
                break

            if submit_payload is None or final_result is None:
                raise ValueError("External OCR submit failed after retry attempts")

            if external_job_id:
                _ocr_base = ocr_endpoint.rstrip('/')
                stream_url = f"{_ocr_base}/{external_job_id}/stream"
                result_url = f"{_ocr_base}/{external_job_id}/result"

                stream_completed = False
                stream_failed = False
                # headers has lowercase "accept" from submit; override with proper Accept for SSE
                stream_headers = {k: v for k, v in headers.items() if k.lower() != "accept"}
                stream_headers["Accept"] = "text/event-stream"

                # Redis client for writing live progress (bypasses Celery state override)
                try:
                    from app.core.config import settings as _settings
                    _redis = redis_lib.from_url(_settings.REDIS_URL, decode_responses=True)
                    _redis_key = f"doc_progress:{document_id}"
                except Exception:
                    _redis = None
                    _redis_key = None

                job_logger.info(f"SSE stream starting: {stream_url}")
                try:
                    with requests.get(
                        stream_url,
                        headers=stream_headers,
                        timeout=1500,
                        verify=verify_ssl,
                        stream=True,
                    ) as stream_response:
                        job_logger.info(f"SSE stream connected: HTTP {stream_response.status_code}")
                        stream_response.raise_for_status()
                        event_type = None
                        data_lines: list[str] = []

                        for raw_line in stream_response.iter_lines(decode_unicode=True):
                            if raw_line.startswith("event:"):
                                event_type = raw_line[6:].strip()
                            elif raw_line.startswith("data:"):
                                data_lines.append(raw_line[5:].strip())
                            elif raw_line == "":
                                if data_lines:
                                    raw_data = "\n".join(data_lines)
                                    try:
                                        event_obj = json.loads(raw_data)
                                    except (json.JSONDecodeError, ValueError):
                                        event_obj = {}

                                    current_status = extract_status(event_obj) if event_obj else ""

                                    # percent/stage may be at top-level OR nested in a "progress" dict
                                    _prog_dict = event_obj.get("progress") if isinstance(event_obj, dict) else None
                                    if isinstance(_prog_dict, dict):
                                        _percent = _prog_dict.get("percent")
                                        _stage   = _prog_dict.get("stage", "")
                                        _message = _prog_dict.get("message", "")
                                    else:
                                        _percent = event_obj.get("percent") if isinstance(event_obj, dict) else None
                                        _stage   = event_obj.get("stage", "") if isinstance(event_obj, dict) else ""
                                        _message = event_obj.get("message", "") if isinstance(event_obj, dict) else ""

                                    if _percent is not None and event_type == "progress":
                                        _progress_data = json.dumps({
                                            "percent": int(_percent),
                                            "stage": _stage,
                                            "message": _message,
                                        })
                                        if _redis and _redis_key:
                                            try:
                                                _redis.set(_redis_key, _progress_data, ex=1800)
                                            except Exception:
                                                pass
                                        job_logger.info(
                                            f"Stream progress: {_percent}% [{_stage}]"
                                        )

                                    if event_type == "completed" or current_status in {"completed", "success", "done"}:
                                        stream_completed = True
                                        break

                                    if event_type == "error" or current_status in {"failed", "error", "cancelled", "canceled"}:
                                        stream_failed = True
                                        raise ValueError(f"External OCR processing failed: {event_obj}")

                                event_type = None
                                data_lines = []

                except requests.exceptions.RequestException as stream_err:
                    job_logger.warning(f"SSE stream failed ({stream_err}), falling back to polling")
                    # Fallback: poll /status until done
                    status_url = f"{ocr_endpoint.rstrip('/')}/{external_job_id}/status"
                    for _ in range(600):
                        status_response = requests.get(
                            status_url, headers=headers, timeout=30, verify=verify_ssl,
                        )
                        status_response.raise_for_status()
                        status_payload = status_response.json()
                        current_status = extract_status(status_payload)

                        ext_progress = status_payload.get("progress") if isinstance(status_payload, dict) else None
                        if isinstance(ext_progress, dict):
                            self.update_state(
                                state="PROGRESS",
                                meta={
                                    "percent": ext_progress.get("percent", 0),
                                    "stage": ext_progress.get("stage", ""),
                                    "message": ext_progress.get("message", ""),
                                },
                            )

                        if current_status in {"completed", "success", "done"}:
                            stream_completed = True
                            break
                        if current_status in {"failed", "error", "cancelled", "canceled"}:
                            raise ValueError(f"External OCR processing failed: {status_payload}")
                        time.sleep(2)
                    else:
                        raise TimeoutError("Timeout waiting for external OCR processing result")

                if not stream_completed and not stream_failed:
                    raise TimeoutError("SSE stream ended without a completed event")

                result_response = requests.get(
                    result_url,
                    headers=headers,
                    timeout=60,
                    verify=verify_ssl,
                )
                result_response.raise_for_status()
                final_result = result_response.json()

            ai_extract_text = extract_ai_text(final_result)
            structured_data = extract_structured_data(final_result)

            pages = final_result.get("results", {}).get("pages")
            if not isinstance(pages, list):
                pages = final_result.get("pages") if isinstance(final_result.get("pages"), list) else None

            document.ocr_pages = pages
            if isinstance(pages, list):
                document.page_count = len(pages)

            ai_processing_errors: list[str] = []
            if isinstance(pages, list):
                for page in pages:
                    if not isinstance(page, dict):
                        continue
                    page_ai = page.get("ai_processing")
                    if isinstance(page_ai, dict) and page_ai.get("success") is False:
                        page_no = page.get("page_number", "?")
                        ai_error = page_ai.get("error") or "Unknown AI processing error"
                        ai_processing_errors.append(f"Page {page_no}: {ai_error}")

            document.ocr_text = ai_extract_text or ""
            document.extracted_data = structured_data if structured_data not in ({}, []) else None
            document.status = "extraction_completed"
            if ai_processing_errors:
                document.processing_error = "AI processing degraded: " + " | ".join(ai_processing_errors)
            else:
                document.processing_error = None
            document.processed_at = datetime.utcnow()

            db.add(document)
            db.commit()

            job_logger.info(
                f"External OCR processing completed for {document.filename}; "
                f"schema_source={schema_source}; extracted_records_type={type(document.extracted_data).__name__}"
            )

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
                    "schema_source": schema_source,
                    "document_status": document.status
                }
            )

        job_logger.info(f"Document {document.filename} processing completed with status: {document.status}")
        return {
            "status": document.status,
            "document_id": document_id,
            "extracted_data": document.extracted_data
        }

    except SoftTimeLimitExceeded:
        logger.error(f"Soft time limit exceeded for document {document_id} — marking as failed")
        try:
            doc = db.query(Document).filter(Document.id == document_id).first()
            if doc:
                doc.status = "failed"
                doc.processing_error = "Processing timeout: task exceeded time limit"
                db.add(doc)
                db.commit()
                if doc.job_id:
                    get_job_logger(str(doc.job_id)).error(
                        f"Soft time limit exceeded for {doc.filename} — marked as failed"
                    )
        except Exception:
            pass
        return {"status": "failed", "error": "SoftTimeLimitExceeded"}

    except Exception as e:
        logger.exception(f"Processing failed for document {document_id}: {e}")
        try:
            db_doc = db.query(Document).filter(Document.id == document_id).first()
            if db_doc and db_doc.job_id:
                jl = get_job_logger(str(db_doc.job_id))
                jl.error(f"Unexpected processing error for document {db_doc.filename}: {e}", exc_info=True)
        except Exception:
            pass

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
