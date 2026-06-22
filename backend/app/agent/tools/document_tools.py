from datetime import datetime, timezone
from app.agent.tools.registry import ToolDef, tool_registry
from app.models.document import Document
from app.utils.activity_logger import log_activity


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
    return {
        "id": str(doc.id), "filename": doc.filename, "status": doc.status,
        "page_count": doc.page_count,
        "ocr_text": doc.ocr_text[:5000] if doc.ocr_text else None,
        "extracted_data": doc.extracted_data, "reviewed_data": doc.reviewed_data,
        "extraction_confidence": doc.extraction_confidence,
        "review_decision": doc.review_decision,
    }


async def _search_documents_handler(args: dict, context) -> dict:
    query = args.get("query", "").lower()
    docs = context.db.query(Document).filter(Document.job_id == context.job_id).all()
    results = []
    for d in docs:
        score = 0
        if query and d.filename and query in d.filename.lower():
            score = 3
        if query and d.extracted_data and query in str(d.extracted_data).lower():
            score = max(score, 2)
        if query and d.ocr_text and query in d.ocr_text.lower():
            score = max(score, 1)
        if score > 0 or not query:
            results.append({"id": str(d.id), "filename": d.filename, "score": score, "status": d.status})
    results.sort(key=lambda x: x["score"], reverse=True)
    return {"query": query, "count": len(results), "documents": results[:10]}


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

    d1 = _normalize(doc1.reviewed_data or doc1.extracted_data or {})
    d2 = _normalize(doc2.reviewed_data or doc2.extracted_data or {})
    diff = {}
    for k in set(d1.keys()) | set(d2.keys()):
        if k not in d1:
            diff[k] = {"doc1": None, "doc2": d2[k], "status": "added"}
        elif k not in d2:
            diff[k] = {"doc1": d1[k], "doc2": None, "status": "removed"}
        elif d1[k] != d2[k]:
            diff[k] = {"doc1": d1[k], "doc2": d2[k], "status": "changed"}
    return {"doc1": doc1.filename, "doc2": doc2.filename, "differences": diff}


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
    description="Get full details of a document including OCR text and extracted/reviewed data.",
    parameters_schema={"type": "object", "properties": {"doc_id": {"type": "string", "description": "Document UUID"}}, "required": ["doc_id"]},
    handler=_get_document_detail_handler,
))

tool_registry.register(ToolDef(
    name="search_documents", category="document",
    description="Search documents by keyword in filename, OCR text, or extracted data.",
    parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
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