from __future__ import annotations

import uuid

from app.agent.a2ui import (
    ACTION_EVENTS, CATALOG, MAX_COMPONENTS, MAX_DOCUMENTS, SurfaceError,
    parse_surface, resolve_documents, resolve_pointer, surface_messages,
)
from app.agent.tools.document_tools import DocIdError, job_documents, parse_doc_ids
from app.agent.tools.registry import ToolDef, tool_registry


async def _render_ui_handler(args: dict, context) -> dict:
    try:
        surface = parse_surface(args.get("components"), args.get("data"))
        raw_ids = surface.document_ids()
        docs = job_documents(context.db, context.job_id, parse_doc_ids(raw_ids))
        by_id = {d.id: {"document_id": str(d.id), "filename": d.filename, "status": d.status} for d in docs}
        rows = {raw: by_id[uuid.UUID(raw)] for raw in raw_ids if uuid.UUID(raw) in by_id}
        data, dropped = resolve_documents(surface, rows)
    except DocIdError as error:
        return {"ok": False, "error": f"render_ui was not shown: {error}"}
    except SurfaceError as error:
        return {"ok": False, "error": str(error)}
    surface_id = f"jobs-{uuid.uuid4().hex[:12]}"
    # The model sees everything but "a2ui" (see tool_content_for_llm); the chat renders "a2ui".
    result: dict = {"ok": True, "surface_id": surface_id, "document_count": sum(len(resolve_pointer(data, path)) for path, _ in surface.document_lists),
                    "a2ui": surface_messages(surface_id, surface.components, data)}
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
        "bulk_approve / bulk_reject after the user clicks a button.\n"
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
