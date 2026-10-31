from __future__ import annotations

import uuid

from app.agent.a2ui import (
    ACTION_EVENTS, CATALOG, MAX_COMPONENTS, MAX_DOCUMENTS, SurfaceError,
    parse_surface, resolve_documents, surface_messages,
)
from app.agent.tools.registry import ToolDef, tool_registry
from app.models.document import Document


def job_document_rows(db, job_id, document_ids: list[str]) -> dict[str, dict]:
    """{id: {document_id, filename, status}} for the ids that belong to this job."""
    wanted = set()
    for raw in document_ids:
        try:
            wanted.add(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    if not wanted or job_id is None:
        return {}
    docs = db.query(Document).filter(Document.job_id == job_id, Document.id.in_(wanted)).all()
    return {str(d.id): {"document_id": str(d.id), "filename": d.filename, "status": d.status} for d in docs}


async def _render_ui_handler(args: dict, context) -> dict:
    try:
        surface = parse_surface(args.get("components"), args.get("data"))
        rows = job_document_rows(context.db, context.job_id, surface.document_ids())
        data, dropped = resolve_documents(surface, rows)
    except SurfaceError as error:
        return {"ok": False, "error": str(error)}
    surface_id = f"jobs-{uuid.uuid4().hex[:12]}"
    result: dict = {"ok": True, "surface_id": surface_id, "a2ui": surface_messages(surface_id, surface.components, data)}
    if dropped:
        result["dropped_document_ids"] = dropped
        result["note"] = "These ids are not documents of this job and were not shown."
    return result


tool_registry.register(ToolDef(
    name="render_ui", category="document",
    description=(
        "Show an interactive panel in the chat (A2UI). Use it when presenting a set of documents the user may "
        "act on, e.g. documents awaiting approval or with problems. Still give a short text answer; do not "
        "repeat the full list in text. The panel only displays: approving or rejecting still happens through "
        "bulk_approve / approve_document / reject_document after the user clicks a button.\n"
        f"Components ({', '.join(CATALOG)}) form a flat list; one must have id \"root\" (usually a Column).\n"
        "- Column {children: [ids]}\n"
        "- Text {text: string | {path}, variant?: body|caption|heading}\n"
        "- DocumentList {documents: {path: \"/documents\"}, selectable?: bool, selection?: \"/selected\"}\n"
        f"- Button {{label, variant?: primary|secondary, action: {{event: {{name: {'|'.join(ACTION_EVENTS)}, "
        "context: {document_ids: {path: \"/selected\"}}}}}}\n"
        "data holds only document ids and an optional short note per row, e.g. "
        "{\"documents\": [{\"document_id\": \"<id from list_documents>\", \"note\": \"ยอดไม่ตรง\"}]}; "
        "the system fills in filename and status. "
        f"Limits: {MAX_COMPONENTS} components, {MAX_DOCUMENTS} documents."
    ),
    parameters_schema={
        "type": "object",
        "properties": {
            "components": {
                "type": "array", "maxItems": MAX_COMPONENTS,
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "component": {"type": "string", "enum": list(CATALOG)}},
                    "required": ["id", "component"],
                },
            },
            "data": {"type": "object", "description": "The surface data model; document rows carry only document_id and note"},
        },
        "required": ["components", "data"],
    },
    handler=_render_ui_handler,
))
