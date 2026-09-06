from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import unicodedata

from app.agent.tools.registry import ToolDef, tool_registry
from app.models.document import Document
from app.utils.activity_logger import log_activity


_THAI_DIGIT_TRANSLATION = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def normalize_search_text(value: object) -> str:
    """Normalize Thai/Arabic digits and whitespace for document search."""
    text = unicodedata.normalize("NFKC", str(value or "")).translate(_THAI_DIGIT_TRANSLATION)
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _compact_search_text(value: object) -> str:
    return re.sub(r"\s+", "", normalize_search_text(value))


def _search_snippets(text: str | None, normalized_query: str, limit: int = 3) -> list[str]:
    if not text or not normalized_query:
        return []
    compact_query = _compact_search_text(normalized_query)
    snippets: list[str] = []
    normalized_chars = []
    positions = []
    for position, char in enumerate(str(text)):
        for normalized_char in _compact_search_text(char):
            normalized_chars.append(normalized_char)
            positions.append(position)
    compact_text = "".join(normalized_chars)
    cursor = 0
    while len(snippets) < limit:
        match = compact_text.find(compact_query, cursor)
        if match < 0:
            break
        start = positions[match]
        end = positions[match + len(compact_query) - 1] + 1
        snippets.append(" ".join(text[max(0, start - 150):end + 350].split()))
        cursor = match + len(compact_query)
    return snippets


async def _list_documents_handler(args: dict, context) -> dict:
    status_filter = args.get("status_filter", "all")
    q = context.db.query(Document).filter(Document.job_id == context.job_id)
    if status_filter != "all":
        q = q.filter(Document.status == status_filter)
    docs = q.all()
    result = [
        {"id": str(d.id), "filename": d.filename, "status": d.status,
         "page_count": d.page_count, "extraction_confidence": d.extraction_confidence,
         "has_extracted_data": d.extracted_data is not None,
         "has_reviewed_data": d.reviewed_data is not None,
         "has_ocr_text": bool(d.ocr_text), "ocr_text_chars": len(d.ocr_text or ""),
         "review_decision": d.review_decision}
        for d in docs
    ]
    return {"count": len(result), "documents": result}


async def _get_document_detail_handler(args: dict, context) -> dict:
    doc = context.db.query(Document).filter(
        Document.id == args["doc_id"], Document.job_id == context.job_id
    ).first()
    if not doc:
        return {"error": f"Document {args['doc_id']} not found"}
    text = doc.ocr_text or ""
    offset = min(len(text), max(0, int(args.get("offset", 0))))
    limit = min(6000, max(1, int(args.get("limit", 4000))))
    end = min(len(text), offset + limit)
    # Put coverage before data so model-facing truncation cannot hide it.
    result = {
        "id": str(doc.id), "filename": doc.filename, "status": doc.status,
        "page_count": doc.page_count,
        "text_range": {"start": offset, "end": end, "total_chars": len(text)},
        "next_offset": end if end < len(text) else None,
        "text_complete": offset == 0 and end == len(text),
        "ocr_text": text[offset:end] if text else None,
        "extraction_confidence": doc.extraction_confidence,
        "review_decision": doc.review_decision,
    }
    data = doc.reviewed_data if doc.reviewed_data is not None else doc.extracted_data
    source = "reviewed_data" if doc.reviewed_data is not None else "extracted_data"
    result["preferred_data_source"] = source
    # Large structured payloads have a separate cursor; never silently drop rows.
    serialized = json.dumps(data, ensure_ascii=False, default=str)
    data_offset = max(0, int(args.get("data_offset", 0)))
    if len(serialized) <= 3000:
        result[source] = data
        other_source = "extracted_data" if source == "reviewed_data" else "reviewed_data"
        other_data = getattr(doc, other_source)
        if len(json.dumps(other_data, ensure_ascii=False, default=str)) <= 1000:
            result[other_source] = other_data
        result["next_data_offset"] = None
    else:
        data_offset = min(len(serialized), data_offset)
        data_end = min(len(serialized), data_offset + 3000)
        result["structured_data_json_excerpt"] = serialized[data_offset:data_end]
        result["structured_data_range"] = {"start": data_offset, "end": data_end, "total_chars": len(serialized)}
        result["next_data_offset"] = data_end if data_end < len(serialized) else None
    return result


async def _search_documents_handler(args: dict, context) -> dict:
    query = normalize_search_text(args.get("query", ""))
    compact_query = _compact_search_text(query)
    docs = context.db.query(Document).filter(Document.job_id == context.job_id).all()
    results = []
    for d in docs:
        score = 0
        matched_sources: list[str] = []
        snippets = _search_snippets(d.ocr_text, query)
        filename_match = bool(compact_query and compact_query in _compact_search_text(d.filename))
        extracted_match = bool(
            compact_query
            and d.extracted_data
            and compact_query in _compact_search_text(d.extracted_data)
        )
        reviewed_match = bool(
            compact_query and isinstance(d.reviewed_data, (dict, list, str))
            and compact_query in _compact_search_text(d.reviewed_data)
        )
        ocr_match = bool(snippets)
        if filename_match:
            score = 3
            matched_sources.append("filename")
        if extracted_match:
            score = max(score, 2)
            matched_sources.append("extracted_data")
        if reviewed_match:
            score = max(score, 2)
            matched_sources.append("reviewed_data")
        if ocr_match:
            score = max(score, 1)
            matched_sources.append("ocr_text")
        if score > 0 or not query:
            results.append({
                "id": str(d.id), "filename": d.filename, "score": score, "status": d.status,
                "matched_sources": matched_sources, "snippets": snippets,
            })
    results.sort(key=lambda x: x["score"], reverse=True)
    offset = max(0, int(args.get("offset", 0)))
    end = min(len(results), offset + 10)
    return {"query": query, "count": len(results), "next_offset": end if end < len(results) else None, "documents": results[offset:end]}


async def _compare_documents_handler(args: dict, context) -> dict:
    doc1 = context.db.query(Document).filter(Document.id == args["doc_id_1"], Document.job_id == context.job_id).first()
    doc2 = context.db.query(Document).filter(Document.id == args["doc_id_2"], Document.job_id == context.job_id).first()
    if not doc1 or not doc2:
        return {"error": "One or both documents not found"}
    # Extracted/reviewed data may be a dict, a list (e.g. multi-record/section
    # contracts), or a scalar. Normalize to a flat dict so the key-diff below
    # works for any shape instead of assuming .keys() exists.
    def _normalize(data) -> dict:
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {f"[{i}]": v for i, v in enumerate(data)}
        return {"value": data} if data is not None else {}

    d1 = _normalize(doc1.reviewed_data if doc1.reviewed_data is not None else doc1.extracted_data)
    d2 = _normalize(doc2.reviewed_data if doc2.reviewed_data is not None else doc2.extracted_data)
    diff = {}
    for k in sorted(set(d1.keys()) | set(d2.keys())):
        if k not in d1:
            diff[k] = {"doc1": None, "doc2": d2[k], "status": "added"}
        elif k not in d2:
            diff[k] = {"doc1": d1[k], "doc2": None, "status": "removed"}
        elif d1[k] != d2[k]:
            diff[k] = {"doc1": d1[k], "doc2": d2[k], "status": "changed"}
    return {
        "doc1": doc1.filename, "doc2": doc2.filename,
        "comparison_scope": "structured_fields_only",
        "structured_data_available": {"doc1": bool(d1), "doc2": bool(d2)},
        "ocr_text_equal": (doc1.ocr_text == doc2.ocr_text) if doc1.ocr_text and doc2.ocr_text else None,
        "guidance": "An empty field diff does not establish document equivalence. Read both documents with get_document_detail and follow next_offset to compare clauses and cite character ranges.",
        "differences": diff,
    }


async def _update_document_field_handler(args: dict, context) -> dict:
    doc = context.db.query(Document).filter(Document.id == args["doc_id"], Document.job_id == context.job_id).first()
    if not doc:
        return {"error": "Document not found"}
    reviewed_data = dict(doc.reviewed_data or doc.extracted_data or {})
    reviewed_data[args["field"]] = args["value"]
    doc.reviewed_data = reviewed_data
    try:
        context.db.commit()
    except Exception as e:
        context.db.rollback()
        return {"ok": False, "error": f"DB commit failed: {type(e).__name__}: {e}"}
    context.db.refresh(doc)
    actual = (doc.reviewed_data or {}).get(args["field"])
    if actual != args["value"]:
        return {
            "ok": False,
            "error": "Read-back mismatch: field not persisted",
            "expected": args["value"],
            "actual": actual,
        }
    return {"ok": True, "verified": True, "doc_id": str(doc.id), "field": args["field"], "value": args["value"]}


async def _approve_document_handler(args: dict, context) -> dict:
    doc = context.db.query(Document).filter(Document.id == args["doc_id"], Document.job_id == context.job_id).first()
    if not doc:
        return {"error": "Document not found"}
    doc.status = "reviewed"
    doc.review_decision = "approved"
    doc.reviewed_at = datetime.now(timezone.utc)
    doc.reviewed_by = context.user_id
    if not doc.reviewed_data:
        doc.reviewed_data = dict(doc.extracted_data or {})
    try:
        context.db.commit()
    except Exception as e:
        context.db.rollback()
        return {"ok": False, "error": f"DB commit failed: {type(e).__name__}: {e}"}
    context.db.refresh(doc)
    if doc.status != "reviewed" or doc.review_decision != "approved":
        return {
            "ok": False,
            "error": "Read-back mismatch: review state not persisted",
            "status": doc.status,
            "decision": doc.review_decision,
        }
    log_activity(context.db, user_id=context.user_id, action="review_document",
                 resource_type="document", resource_id=str(doc.id),
                 details={"decision": "approved", "agent_initiated": True, "note": args.get("note")})
    return {"ok": True, "verified": True, "doc_id": str(doc.id), "filename": doc.filename, "status": "reviewed"}


async def _reject_document_handler(args: dict, context) -> dict:
    doc = context.db.query(Document).filter(Document.id == args["doc_id"], Document.job_id == context.job_id).first()
    if not doc:
        return {"error": "Document not found"}
    doc.status = "reviewed"
    doc.review_decision = "rejected"
    doc.reviewed_at = datetime.now(timezone.utc)
    doc.reviewed_by = context.user_id
    try:
        context.db.commit()
    except Exception as e:
        context.db.rollback()
        return {"ok": False, "error": f"DB commit failed: {type(e).__name__}: {e}"}
    context.db.refresh(doc)
    if doc.status != "reviewed" or doc.review_decision != "rejected":
        return {
            "ok": False,
            "error": "Read-back mismatch: review state not persisted",
            "status": doc.status,
            "decision": doc.review_decision,
        }
    log_activity(context.db, user_id=context.user_id, action="review_document",
                 resource_type="document", resource_id=str(doc.id),
                 details={"decision": "rejected", "agent_initiated": True})
    return {"ok": True, "verified": True, "doc_id": str(doc.id), "filename": doc.filename, "status": "reviewed"}


async def _bulk_approve_handler(args: dict, context) -> dict:
    q = context.db.query(Document).filter(Document.job_id == context.job_id, Document.status == "extraction_completed")
    if args.get("min_confidence"):
        q = q.filter(Document.extraction_confidence >= args["min_confidence"])
    docs = q.all()
    target_ids = [str(d.id) for d in docs]
    for d in docs:
        d.status = "reviewed"
        d.review_decision = "approved"
        d.reviewed_at = datetime.now(timezone.utc)
        d.reviewed_by = context.user_id
        if not d.reviewed_data:
            d.reviewed_data = dict(d.extracted_data or {})
    try:
        context.db.commit()
    except Exception as e:
        context.db.rollback()
        return {"ok": False, "error": f"DB commit failed: {type(e).__name__}: {e}"}
    context.db.expire_all()
    persisted = context.db.query(Document).filter(
        Document.id.in_(target_ids), Document.status == "reviewed"
    ).count()
    if persisted != len(target_ids):
        return {
            "ok": False,
            "error": "Read-back mismatch: not all documents persisted as reviewed",
            "expected": len(target_ids),
            "actual": persisted,
        }
    return {"ok": True, "verified": True, "approved_count": persisted}


# ── Tool Registrations ──

tool_registry.register(ToolDef(
    name="list_documents", category="document",
    description="List all documents in the current job with status, confidence, and review state.",
    parameters_schema={"type": "object", "properties": {"status_filter": {"type": "string", "enum": ["uploaded", "ocr_completed", "extraction_completed", "reviewed", "all"], "default": "all"}}, "required": []},
    handler=_list_documents_handler,
))

tool_registry.register(ToolDef(
    name="get_document_detail", category="document",
    description="Read a document with explicit coverage and continuation cursors. Follow next_offset for remaining OCR text and next_data_offset for large structured JSON. Prefer reviewed data; cite filename and text_range. Never treat a partial read as the full document.",
    parameters_schema={"type": "object", "properties": {
        "doc_id": {"type": "string", "description": "Document UUID"},
        "offset": {"type": "integer", "minimum": 0, "default": 0},
        "limit": {"type": "integer", "minimum": 1, "maximum": 6000, "default": 4000},
        "data_offset": {"type": "integer", "minimum": 0, "default": 0},
    }, "required": ["doc_id"]},
    handler=_get_document_detail_handler,
))

tool_registry.register(ToolDef(
    name="search_documents", category="document",
    description="Search documents by keyword in filename, OCR text, or extracted data. Use one focused query per concept; do not repeat equivalent searches when a useful result is already available.",
    parameters_schema={"type": "object", "properties": {"query": {"type": "string"}, "offset": {"type": "integer", "minimum": 0, "default": 0}}, "required": ["query"]},
    handler=_search_documents_handler,
))

tool_registry.register(ToolDef(
    name="compare_documents", category="document",
    description="Compare extracted_data of two documents and return differences.",
    parameters_schema={"type": "object", "properties": {"doc_id_1": {"type": "string"}, "doc_id_2": {"type": "string"}}, "required": ["doc_id_1", "doc_id_2"]},
    handler=_compare_documents_handler,
))

tool_registry.register(ToolDef(
    name="update_document_field", category="document",
    description="Update a single field in a document's reviewed_data.",
    parameters_schema={"type": "object", "properties": {"doc_id": {"type": "string"}, "field": {"type": "string"}, "value": {}}, "required": ["doc_id", "field", "value"]},
    handler=_update_document_field_handler,
    requires_confirmation=True,
))

tool_registry.register(ToolDef(
    name="approve_document", category="document",
    description="Approve a document — sets status to 'reviewed' with decision 'approved'.",
    parameters_schema={"type": "object", "properties": {"doc_id": {"type": "string"}, "note": {"type": "string"}}, "required": ["doc_id"]},
    handler=_approve_document_handler,
    requires_confirmation=True,
))

tool_registry.register(ToolDef(
    name="reject_document", category="document",
    description="Reject a document — sets status to 'reviewed' with decision 'rejected'.",
    parameters_schema={"type": "object", "properties": {"doc_id": {"type": "string"}}, "required": ["doc_id"]},
    handler=_reject_document_handler,
    requires_confirmation=True,
))

tool_registry.register(ToolDef(
    name="bulk_approve", category="document",
    description="Approve all extraction_completed documents in the job, optionally filtered by min confidence.",
    parameters_schema={"type": "object", "properties": {"min_confidence": {"type": "number", "minimum": 0, "maximum": 1}}, "required": []},
    handler=_bulk_approve_handler,
    requires_confirmation=True,
))
