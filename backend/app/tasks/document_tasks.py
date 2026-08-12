"""
Celery background tasks for document processing.
Handles OCR and structure extraction asynchronously.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone as dt_timezone
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from app.celery_app import celery_app
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import Document, DocumentSchema as SchemaModel, Setting
from app.services.storage import get_storage_service
from app.services.structure import extract_structure
from app.services.tls import get_verify_ssl
from app.services.ocr_fallback import process_fallback_ocr, resolve_fallback_api_key
from app.services.anydoc_pipeline import (
    AnydocFallbackToLegacy,
    AnydocTerminalError,
    extract_anydoc_document,
)
from app.services.anydoc_bbox import BboxLocatorError, extract_fixed_position_fields
from app.services.extraction_profiles import supports_anydoc_source, validate_extraction_profile
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


def build_schema_json(
    schema: SchemaModel | None,
    fields: list[dict[str, Any]] | None = None,
) -> str:
    if not schema and fields is None:
        return ""

    properties: dict[str, Any] = {}
    required_fields: list[str] = []

    for field in (schema.fields if fields is None and schema else fields) or []:
        field_name = (field.get("name") or "").strip()
        if not field_name:
            continue

        field_schema = map_field_type_to_json_schema(
            field.get("type", "text"),
            field.get("description", ""),
        )
        validation_rules = field.get("validation_rules") or {}
        if isinstance(validation_rules, dict):
            if "min" in validation_rules:
                field_schema["minimum"] = validation_rules["min"]
            if "max" in validation_rules:
                field_schema["maximum"] = validation_rules["max"]
            if "pattern" in validation_rules:
                field_schema["pattern"] = validation_rules["pattern"]
        properties[field_name] = field_schema
        if field.get("required"):
            required_fields.append(field_name)

    json_schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required_fields,
    }

    return json.dumps(json_schema)


def _normalize_schema_value(value: Any, field_schema: dict[str, Any], field_name: str) -> Any:
    """Validate and normalize a provider value to the Schema field type."""
    expected_type = field_schema.get("type", "string")
    if value is None:
        return None

    if expected_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"Field '{field_name}' must be text")
        if field_schema.get("format") == "date":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(f"Field '{field_name}' must use ISO date format") from exc
        pattern = field_schema.get("pattern")
        if pattern and not re.fullmatch(str(pattern), value):
            raise ValueError(f"Field '{field_name}' does not match its validation rule")
        return value

    if expected_type == "number":
        if isinstance(value, bool):
            raise ValueError(f"Field '{field_name}' must be a number")
        if isinstance(value, str):
            try:
                value = float(value.replace(",", "").strip())
            except ValueError as exc:
                raise ValueError(f"Field '{field_name}' must be a number") from exc
        if not isinstance(value, (int, float)):
            raise ValueError(f"Field '{field_name}' must be a number")
        if "minimum" in field_schema and value < field_schema["minimum"]:
            raise ValueError(f"Field '{field_name}' is below its minimum value")
        if "maximum" in field_schema and value > field_schema["maximum"]:
            raise ValueError(f"Field '{field_name}' exceeds its maximum value")
        return value

    if expected_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"Field '{field_name}' must be true or false")
        return value

    if expected_type == "array":
        if not isinstance(value, list):
            raise ValueError(f"Field '{field_name}' must be a list")
        return value

    raise ValueError(f"Field '{field_name}' has unsupported type '{expected_type}'")


def validate_mapped_schema_fields(mapped: Any, schema_payload: dict[str, Any]) -> dict[str, Any]:
    """Reject provider output that is not a faithful instance of the selected Schema."""
    if not isinstance(mapped, dict):
        raise ValueError("Structured output must be a JSON object")

    properties = schema_payload.get("properties") or {}
    unexpected_fields = set(mapped) - set(properties)
    if unexpected_fields:
        raise ValueError(
            "Structured output contains fields outside the selected schema: "
            + ", ".join(sorted(unexpected_fields))
        )

    required_fields = schema_payload.get("required") or []
    missing_fields = [field for field in required_fields if mapped.get(field) in (None, "", [], {})]
    if missing_fields:
        raise ValueError("Structured output is missing required fields: " + ", ".join(missing_fields))

    return {
        field_name: _normalize_schema_value(value, properties[field_name], field_name)
        for field_name, value in mapped.items()
    }


def map_anydoc_schema_fields(
    markdown: str,
    schema: SchemaModel | None,
    db: Any,
) -> Any:
    """Map a completed AnyDoc extraction only when the user selected a Schema."""
    if not schema:
        return None

    schema_json = build_schema_json(schema)
    schema_payload = json.loads(schema_json)
    if not schema_payload.get("properties"):
        raise ValueError(f"Selected schema '{schema.name}' has no extraction fields")

    result = extract_structure(
        markdown,
        schema_json,
        db,
        prompt=(
            "Extract only values supported by the supplied JSON Schema. "
            "Return valid JSON and do not invent values that are not present in the document."
        ),
    )
    mapped = parse_extracted_json(result)
    if mapped in (None, {}, []):
        raise ValueError("Structured output provider returned no mapped fields")
    return validate_mapped_schema_fields(mapped, schema_payload)


def _normalise_fixed_position_value(
    value: str,
    field_schema: dict[str, Any],
    field_name: str,
) -> Any:
    """Normalize deterministic BBox text through the same Schema type rules."""
    if not value.strip():
        return None
    if field_schema.get("format") == "date":
        value = _normalise_fixed_position_date(value)
    return _normalize_schema_value(value, field_schema, field_name)


def _normalise_fixed_position_date(value: str) -> str:
    """Return a Gregorian ISO date from common English and Thai form values."""
    cleaned = value.strip().translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))
    thai_months = {
        "มกราคม": 1, "ม.ค.": 1, "มค": 1,
        "กุมภาพันธ์": 2, "ก.พ.": 2, "กพ": 2,
        "มีนาคม": 3, "มี.ค.": 3, "มีค": 3,
        "เมษายน": 4, "เม.ย.": 4, "เมย": 4,
        "พฤษภาคม": 5, "พ.ค.": 5, "พค": 5,
        "มิถุนายน": 6, "มิ.ย.": 6, "มิย": 6,
        "กรกฎาคม": 7, "ก.ค.": 7, "กค": 7,
        "สิงหาคม": 8, "ส.ค.": 8, "สค": 8,
        "กันยายน": 9, "ก.ย.": 9, "กย": 9,
        "ตุลาคม": 10, "ต.ค.": 10, "ตค": 10,
        "พฤศจิกายน": 11, "พ.ย.": 11, "พย": 11,
        "ธันวาคม": 12, "ธ.ค.": 12, "ธค": 12,
    }

    def to_iso(day: int, month: int, year: int) -> str:
        if year >= 2400:
            year -= 543
        return datetime(year, month, day).date().isoformat()

    numeric = re.search(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})(?!\d)", cleaned)
    if numeric:
        return to_iso(*(int(part) for part in numeric.groups()))

    thai_named = re.search(r"(?<!\d)(\d{1,2})\s+([^\s]+)\s+(\d{4})(?!\d)", cleaned)
    if thai_named:
        day, month_name, year = thai_named.groups()
        month = thai_months.get(month_name.lower())
        if month:
            return to_iso(int(day), month, int(year))

    candidates = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y", "%B %d, %Y")
    for date_format in candidates:
        try:
            return datetime.strptime(cleaned, date_format).date().isoformat()
        except ValueError:
            continue
    return cleaned


class PartialSchemaMappingError(ValueError):
    """Structured mapping failed after deterministic BBox fields succeeded."""

    def __init__(self, mapped: dict[str, Any], evidence: dict[str, Any], reason: Exception):
        super().__init__(str(reason))
        self.mapped = mapped
        self.evidence = evidence


def map_schema_fields_with_locators(
    markdown: str,
    schema: SchemaModel,
    db: Any,
    file_path: str,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Map BBox fields directly and use structured output only for remaining fields."""
    fields = [field for field in schema.fields or [] if isinstance(field, dict)]
    locator_fields = [field for field in fields if isinstance(field.get("locator"), dict)]
    if not locator_fields:
        return map_anydoc_schema_fields(markdown, schema, db), {}, "structured_output"

    raw_fixed_values, evidence = extract_fixed_position_fields(file_path, locator_fields)
    schema_payload = json.loads(build_schema_json(schema))
    mapped: dict[str, Any] = {}
    for field in locator_fields:
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        field_evidence = evidence.get(name, {})
        mapped[name] = _normalise_fixed_position_value(
            str(field_evidence.get("cleaned_text", raw_fixed_values.get(name, ""))),
            schema_payload["properties"][name],
            name,
        )

    remaining_fields = [field for field in fields if not isinstance(field.get("locator"), dict)]
    if remaining_fields:
        try:
            remaining_schema = json.loads(build_schema_json(schema, remaining_fields))
            result = extract_structure(
                markdown,
                json.dumps(remaining_schema),
                db,
                prompt=(
                    "Extract only values supported by the supplied JSON Schema. "
                    "Return valid JSON and do not invent values that are not present in the document."
                ),
            )
            remaining_mapped = parse_extracted_json(result)
            mapped.update(validate_mapped_schema_fields(remaining_mapped, remaining_schema))
        except Exception as exc:
            locator_schema = json.loads(build_schema_json(schema, locator_fields))
            raise PartialSchemaMappingError(
                validate_mapped_schema_fields(mapped, locator_schema),
                evidence,
                exc,
            ) from exc

    return validate_mapped_schema_fields(mapped, schema_payload), evidence, (
        "bbox+structured_output" if remaining_fields else "bbox"
    )


def apply_schema_mapping(
    document: Document,
    schema: SchemaModel | None,
    db: Any,
    extraction_metadata: dict[str, Any],
    file_path: str | None = None,
) -> str | None:
    """Apply selected Schema mapping after any successful text extraction route."""
    if not schema:
        document.extracted_data = None
        extraction_metadata["mapping"] = "not_requested"
        return None

    try:
        has_locator_fields = any(
            isinstance(field, dict) and isinstance(field.get("locator"), dict)
            for field in (schema.fields or [])
        )
        if has_locator_fields:
            if not file_path:
                raise BboxLocatorError("The source document is unavailable for fixed-position fields")
            mapped, evidence, provider = map_schema_fields_with_locators(
                document.ocr_text or "", schema, db, file_path
            )
            document.extracted_data = mapped
            extraction_metadata["field_evidence"] = evidence
        else:
            document.extracted_data = map_anydoc_schema_fields(document.ocr_text or "", schema, db)
            provider = "structured_output"
        extraction_metadata["mapping"] = {
            "status": "completed",
            "schema": schema.name,
            "provider": provider,
        }
        return None
    except PartialSchemaMappingError as exc:
        document.extracted_data = exc.mapped
        extraction_metadata["field_evidence"] = exc.evidence
        mapping_error = str(exc)
        extraction_metadata["mapping"] = {
            "status": "partial",
            "schema": schema.name,
            "provider": "bbox",
            "reason": mapping_error,
        }
        logger.warning(
            "Structured mapping partially failed for %s with schema %s: %s",
            document.filename,
            schema.name,
            mapping_error,
        )
        return mapping_error
    except Exception as exc:
        document.extracted_data = None
        mapping_error = str(exc)
        extraction_metadata["mapping"] = {
            "status": "failed",
            "schema": schema.name,
            "provider": "structured_output",
            "reason": mapping_error,
        }
        logger.warning(
            "Structured mapping failed for %s with schema %s: %s",
            document.filename,
            schema.name,
            mapping_error,
        )
        return mapping_error


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


def should_attempt_ocr_fallback(
    *,
    fallback_eligible: bool,
    document: Document | None,
    setting: Setting | None,
    api_key: str,
) -> bool:
    """Return whether a Softnix OCR failure may use the cloud fallback."""
    return bool(
        fallback_eligible
        and document
        and setting
        and setting.ocr_fallback_enabled
        and api_key
        and document.status in {"queued", "processing"}
    )


@celery_app.task(bind=True, max_retries=3)
def process_document_task(
    self,
    document_id: str,
    schema_id: str | None = None,
    requested_extraction_profile: str | None = None,
):
    """
    Background task to process a document through external AI processing API.
    
    Args:
        document_id: UUID of the document to process
        schema_id: UUID of selected schema, or None for Auto mode
    """
    db = SessionLocal()
    # Only errors raised while the legacy Softnix OCR provider is in flight may
    # be recovered by the external OCR fallback. Keep unrelated task failures
    # (database, storage, activity logging) from exporting a document again.
    fallback_eligible = False

    try:
        # Atomic claim: only a "queued" document may start processing. A
        # duplicate delivery (double click, broker redelivery with acks_late)
        # finds the status already changed and skips instead of re-running
        # the paid external OCR call. Celery retries re-enter with the
        # document still in "processing", which is allowed.
        claimed = (
            db.query(Document)
            .filter(Document.id == document_id, Document.status == "queued")
            .update(
                {
                    "status": "processing",
                    "processing_started_at": datetime.now(dt_timezone.utc),
                },
                synchronize_session=False,
            )
        )
        db.commit()
        document = db.query(Document).filter(Document.id == document_id).first()
        if not document:
            logger.error(f"Document {document_id} not found")
            return {"status": "failed", "error": "Document not found"}
        if not claimed:
            if self.request.retries == 0:
                logger.info(
                    f"Document {document_id} not claimable (status={document.status}) — skipping duplicate task"
                )
                return {"status": "skipped", "document_id": document_id}
            # Retry attempt: keep going, refresh the started timestamp
            document.processing_started_at = datetime.now(dt_timezone.utc)
            db.add(document)
            db.commit()

        # Initialize job logger if we have a job
        job_logger = get_job_logger(str(document.job_id)) if document.job_id else logger
        
        job_logger.info(f"Starting processing for document {document.filename} (ID: {document_id}) with schema {schema_id}")

        setting = db.query(Setting).first()
        if not setting:
            raise ValueError("Settings not configured. Please configure OCR endpoint and API token in Settings.")

        ocr_endpoint = setting.ocr_endpoint or setting.api_endpoint
        schema = None
        if schema_id:
            schema = db.query(SchemaModel).filter(SchemaModel.id == schema_id).first()
            if not schema:
                raise ValueError("Selected schema not found")

        try:
            extraction_profile = (
                "anydoc_hybrid"
                if supports_anydoc_source(document.filename, document.mime_type)
                else "legacy"
            )
            if requested_extraction_profile == "anydoc_hybrid":
                extraction_profile = validate_extraction_profile(
                    getattr(schema, "document_type", None),
                    requested_extraction_profile,
                )
        except ValueError as exc:
            raise ValueError(f"Invalid extraction pipeline for selected schema: {exc}") from exc
        if extraction_profile != "anydoc_hybrid" and (not setting.api_token or not ocr_endpoint):
            raise ValueError("Softnix OCR endpoint and API token are required in Settings.")

        verify_ssl = get_verify_ssl(setting, "document processing provider requests")
        ocr_engine = setting.ocr_engine if setting.ocr_engine and setting.ocr_engine != "default" else "tesseract"
        model = "" if not setting.model or setting.model == "default" else setting.model

        schema_source = "auto" if not schema else f"schema:{schema.name}"
        job_logger.info(
            f"Starting processing for document {document.filename} (ID: {document_id}) "
            f"using schema_source={schema_source}"
        )

        document.schema_id = schema.id if schema else None
        db.add(document)
        db.commit()

        storage = get_storage_service()
        with storage.get_local_path(document.file_path) as local_file_path:
            if extraction_profile == "anydoc_hybrid":
                try:
                    anydoc_result = extract_anydoc_document(local_file_path, db, schema)
                    document.ocr_text = anydoc_result.markdown
                    document.ocr_pages = anydoc_result.pages
                    document.page_count = len(anydoc_result.pages)
                    extraction_metadata = dict(anydoc_result.metadata or {})
                    mapping_error = apply_schema_mapping(
                        document,
                        schema,
                        db,
                        extraction_metadata,
                        file_path=local_file_path,
                    )
                    document.extraction_metadata = extraction_metadata
                    document.status = "extraction_completed"
                    document.processing_error = (
                        f"Structured mapping failed: {mapping_error}"
                        if mapping_error
                        else None
                    )
                    document.processed_at = datetime.utcnow()
                    db.add(document)
                    db.commit()

                    if document.job and document.job.user_id:
                        log_activity(
                            db=db,
                            user_id=document.job.user_id,
                            action=Actions.PROCESS_DOCUMENT,
                            resource_type="document",
                            resource_id=document.id,
                            details={
                                "job_name": document.job.name or f"Job-{str(document.job.id)[:8]}",
                                "filename": document.filename,
                                "extraction_status": "completed",
                                "review_status": "pending",
                                "schema_id": str(schema_id),
                                "schema_source": schema_source,
                                "pipeline": "anydoc_hybrid",
                            },
                        )
                    job_logger.info("AnyDoc hybrid extraction completed for %s", document.filename)
                    return {
                        "status": document.status,
                        "document_id": document_id,
                        "extracted_data": document.extracted_data,
                        "pipeline": "anydoc_hybrid",
                    }
                except AnydocFallbackToLegacy as anydoc_error:
                    document.extraction_metadata = {
                        "pipeline": "legacy_fallback",
                        "legacy_fallback": {"reason": str(anydoc_error), "from": "anydoc_hybrid"},
                    }
                    db.add(document)
                    db.commit()
                    job_logger.warning("AnyDoc hybrid fell back to legacy for %s: %s", document.filename, anydoc_error)
                except AnydocTerminalError as anydoc_error:
                    document.status = "failed"
                    document.processing_error = str(anydoc_error)
                    document.extraction_metadata = {
                        "pipeline": "anydoc_hybrid",
                        "failure": {"reason": str(anydoc_error), "terminal": True},
                    }
                    db.add(document)
                    db.commit()
                    job_logger.error("AnyDoc hybrid failed for %s: %s", document.filename, anydoc_error)
                    return {"status": "failed", "document_id": document_id, "error": str(anydoc_error)}

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
            upload_filename = document.filename or os.path.basename(local_file_path)
            content_type = document.mime_type or "application/octet-stream"

            submit_payload: dict[str, Any] | None = None
            final_result: dict[str, Any] | None = None
            external_job_id: str | None = None
            failed_statuses = {"failed", "error", "cancelled", "canceled"}

            # Setup Redis progress key (used by /task-status and /progress-stream endpoints)
            _redis_prog: redis_lib.Redis | None = None
            _redis_prog_key = f"doc_progress:{document_id}"
            try:
                from app.db.redis import get_redis_client
                _redis_prog = get_redis_client()
            except Exception:
                _redis_prog = None

            def _set_progress(percent: int, stage: str) -> None:
                if _redis_prog:
                    try:
                        _redis_prog.set(_redis_prog_key, json.dumps({"percent": percent, "stage": stage, "message": ""}), ex=1800)
                    except Exception:
                        pass

            # The provider only reports real processing progress after it accepts
            # the upload. Keep the upload indicator modest so the UI never implies
            # that structured extraction is nearly complete before it has started.
            _stop_ticker = threading.Event()
            def _progress_ticker() -> None:
                stages = [
                    (5,  "uploading"),
                    (10, "uploading"),
                    (15, "uploading"),
                ]
                for pct, stg in stages:
                    if _stop_ticker.wait(timeout=4.0):
                        break
                    _set_progress(pct, stg)

            _set_progress(0, "queuing")

            # Schema Mapping runs after OCR returns canonical text so legacy and
            # AnyDoc routes share the same validation path.
            submit_variants = [data]

            fallback_eligible = True
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
                    raise

                # Stop the upload ticker now that the provider has accepted the
                # document. Completion progress comes from the job status below.
                _stop_ticker.set()
                _set_progress(15, "processing")

                submit_payload = submit_response.json()
                external_job_id = extract_job_id(submit_payload)
                submit_status = extract_status(submit_payload)
                job_logger.info(f"Submit payload keys: {list(submit_payload.keys()) if isinstance(submit_payload, dict) else type(submit_payload).__name__}; external_job_id={external_job_id}; status={submit_status}")

                if not external_job_id and submit_status in failed_statuses:
                    raise ValueError(f"External OCR submit failed: {submit_payload}")

                final_result = submit_payload
                break

            if submit_payload is None or final_result is None:
                raise ValueError("External OCR submit failed after retry attempts")

            if external_job_id:
                _ocr_base = ocr_endpoint.rstrip('/')
                status_url = f"{_ocr_base}/{external_job_id}/status"
                result_url = f"{_ocr_base}/{external_job_id}/result"
                job_timeout = max(30, settings.OCR_EXTERNAL_JOB_TIMEOUT_SECONDS)
                queue_timeout = max(10, settings.OCR_EXTERNAL_QUEUE_TIMEOUT_SECONDS)
                poll_interval = max(1, settings.OCR_STATUS_POLL_INTERVAL_SECONDS)
                request_timeout = max(5, settings.OCR_STATUS_REQUEST_TIMEOUT_SECONDS)
                deadline = time.monotonic() + job_timeout
                queued_since: float | None = None
                completed = False

                # Polling is deliberate. The upstream SSE endpoint can remain open
                # without emitting an event, which previously left documents at a
                # misleading 95% until Celery's 30-minute task limit intervened.
                job_logger.info(
                    "Polling external OCR job %s every %ss (deadline %ss)",
                    external_job_id,
                    poll_interval,
                    job_timeout,
                )
                while time.monotonic() < deadline:
                    remaining = max(1, int(deadline - time.monotonic()))
                    status_response = requests.get(
                        status_url,
                        headers=headers,
                        timeout=min(request_timeout, remaining),
                        verify=verify_ssl,
                    )
                    status_response.raise_for_status()
                    status_payload = status_response.json()
                    current_status = extract_status(status_payload)
                    ext_progress = status_payload.get("progress") if isinstance(status_payload, dict) else None
                    if isinstance(ext_progress, dict):
                        percent = int(ext_progress.get("percent", 15) or 15)
                        stage = str(ext_progress.get("stage") or "processing")
                        message = str(ext_progress.get("message") or "")
                        _set_progress(percent, stage)
                        self.update_state(
                            state="PROGRESS",
                            meta={"percent": percent, "stage": stage, "message": message},
                        )

                    if current_status in {"queued", "queueing", "pending"}:
                        queued_since = queued_since or time.monotonic()
                        queue_wait = time.monotonic() - queued_since
                        _set_progress(15, "queued")
                        if queue_wait >= queue_timeout:
                            raise TimeoutError(
                                "External OCR job remained queued for more than "
                                f"{queue_timeout} seconds"
                            )
                    else:
                        queued_since = None

                    if current_status in {"completed", "success", "done"}:
                        completed = True
                        break
                    if current_status in failed_statuses:
                        raise ValueError(f"External OCR processing failed: {status_payload}")
                    time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))

                if not completed:
                    raise TimeoutError(
                        f"External OCR job did not complete within {job_timeout} seconds"
                    )

                remaining = max(1, int(deadline - time.monotonic()))
                result_response = requests.get(
                    result_url,
                    headers=headers,
                    timeout=min(60, remaining),
                    verify=verify_ssl,
                )
                result_response.raise_for_status()
                final_result = result_response.json()

            ai_extract_text = extract_ai_text(final_result)
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
            legacy_metadata = dict(document.extraction_metadata or {})
            legacy_metadata.update({
                "pipeline": "legacy_fallback" if legacy_metadata.get("legacy_fallback") else "legacy",
                "schema_context": schema.name if schema else None,
            })
            mapping_error = apply_schema_mapping(
                document,
                schema,
                db,
                legacy_metadata,
                file_path=local_file_path,
            )
            document.extraction_metadata = legacy_metadata
            document.status = "extraction_completed"
            processing_errors = ai_processing_errors[:]
            if mapping_error:
                processing_errors.append(f"Structured mapping failed: {mapping_error}")
            document.processing_error = " | ".join(processing_errors) if processing_errors else None
            document.processed_at = datetime.utcnow()

            db.add(document)
            db.commit()
            fallback_eligible = False

            job_logger.info(
                f"External OCR processing completed for {document.filename}; "
                f"schema_source={schema_source}; mapping={legacy_metadata['mapping']}"
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
        # Use the environment-configured fallback before Celery retries a
        # transient Softnix OCR failure. The fallback is opt-in per settings.
        fallback_db = None
        try:
            fallback_db = SessionLocal()
            fallback_document = fallback_db.query(Document).filter(Document.id == document_id).first()
            fallback_setting = fallback_db.query(Setting).first()
            fallback_key, fallback_source = resolve_fallback_api_key(fallback_setting)
            should_fallback = should_attempt_ocr_fallback(
                fallback_eligible=fallback_eligible,
                document=fallback_document,
                setting=fallback_setting,
                api_key=fallback_key,
            )
            if should_fallback:
                fallback_logger = get_job_logger(str(fallback_document.job_id)) if fallback_document.job_id else logger
                fallback_logger.warning(
                    f"Softnix OCR failed for {fallback_document.filename}; trying configured OCR fallback from {fallback_source}"
                )
                fallback_storage = get_storage_service()
                with fallback_storage.get_local_path(fallback_document.file_path) as fallback_path:
                    fallback_result = process_fallback_ocr(
                        fallback_path,
                        api_key=fallback_key,
                        filename=fallback_document.filename or os.path.basename(fallback_path),
                        mime_type=fallback_document.mime_type or "application/octet-stream",
                        verify_ssl=get_verify_ssl(fallback_setting, "OCR fallback requests"),
                        request_timeout=settings.ANYDOC_FALLBACK_REQUEST_TIMEOUT_SECONDS,
                    )
                fallback_pages = fallback_result["results"]["pages"]
                fallback_document.ocr_pages = fallback_pages
                fallback_document.page_count = len(fallback_pages)
                fallback_document.ocr_text = extract_ai_text(fallback_result)
                fallback_schema = None
                if fallback_document.schema_id:
                    fallback_schema = (
                        fallback_db.query(SchemaModel)
                        .filter(SchemaModel.id == fallback_document.schema_id)
                        .first()
                    )
                fallback_metadata = {
                    "pipeline": "ocr_fallback",
                    "provider": "ocr_fallback",
                    "key_source": fallback_source,
                    "recovered_primary_error": str(e),
                }
                # The first storage context has already released its temporary
                # file. Reopen it only when a fixed-position Schema needs the
                # original page geometry for BBox extraction.
                with fallback_storage.get_local_path(fallback_document.file_path) as mapping_path:
                    mapping_error = apply_schema_mapping(
                        fallback_document,
                        fallback_schema,
                        fallback_db,
                        fallback_metadata,
                        file_path=mapping_path,
                    )
                fallback_document.extraction_metadata = fallback_metadata
                fallback_document.status = "extraction_completed"
                fallback_document.processing_error = (
                    f"Structured mapping failed: {mapping_error}" if mapping_error else None
                )
                fallback_document.processed_at = datetime.utcnow()
                fallback_db.add(fallback_document)
                fallback_db.commit()
                fallback_logger.info(
                    f"Fallback OCR completed for {fallback_document.filename}; primary error was recovered"
                )
                return {
                    "status": fallback_document.status,
                    "document_id": document_id,
                    "extracted_data": fallback_document.extracted_data,
                    "ocr_fallback": True,
                }
        except Exception as fallback_error:
            logger.warning("Fallback OCR failed for document %s: %s", document_id, fallback_error)
        finally:
            try:
                fallback_db.close()
            except Exception:
                pass

        # Transient network/server errors from the external OCR API get a
        # real Celery retry with backoff instead of failing permanently.
        transient = isinstance(
            e,
            (requests.exceptions.ConnectionError, requests.exceptions.Timeout),
        ) or (
            isinstance(e, requests.HTTPError)
            and getattr(e, "response", None) is not None
            and e.response.status_code >= 500
        )
        if transient and self.request.retries < self.max_retries:
            countdown = 30 * (2 ** self.request.retries)
            logger.warning(
                f"Transient error for document {document_id}; retry "
                f"{self.request.retries + 1}/{self.max_retries} in {countdown}s: {e}"
            )
            raise self.retry(exc=e, countdown=countdown)

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
