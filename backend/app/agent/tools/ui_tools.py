from __future__ import annotations

import uuid

from app.agent.a2ui import (
    ACTION_EVENTS, CATALOG, MAX_CHART_POINTS, MAX_CHART_SERIES, MAX_COMPONENTS, MAX_DOCUMENTS, MAX_RISK_ITEMS,
    MAX_TABLE_COLUMNS, MAX_TABLE_ROWS, CitedDocument, SurfaceError, analytics_summary, parse_surface,
    resolve_citations, resolve_documents, resolve_pointer, surface_messages,
)
from app.agent.tools.document_tools import DocIdError, job_documents, parse_doc_ids
from app.agent.tools.registry import ToolDef, tool_registry


async def _render_ui_handler(args: dict, context) -> dict:
    try:
        surface = parse_surface(args.get("components"), args.get("data"))
        listed_ids, cited_ids = surface.document_ids(), surface.cited_document_ids()
        docs = {d.id: d for d in job_documents(context.db, context.job_id, parse_doc_ids(listed_ids + cited_ids))}
        known = {raw: docs[uuid.UUID(raw)] for raw in listed_ids + cited_ids if uuid.UUID(raw) in docs}
        rows = {raw: {"document_id": str(d.id), "filename": d.filename, "status": d.status}
                for raw, d in known.items() if raw in listed_ids}
        data, dropped = resolve_documents(surface, rows)
        data = resolve_citations(surface, data, {raw: CitedDocument(str(d.id), d.ocr_text) for raw, d in known.items()})
    except DocIdError as error:
        return {"ok": False, "error": f"render_ui was not shown: {error}"}
    except SurfaceError as error:
        return {"ok": False, "error": str(error)}
    surface_id = f"jobs-{uuid.uuid4().hex[:12]}"
    # The model sees everything but "a2ui" (see tool_content_for_llm); the chat renders "a2ui".
    result: dict = {"ok": True, "surface_id": surface_id, "document_count": sum(len(resolve_pointer(data, path)) for path, _ in surface.document_lists),
                    **analytics_summary(surface.components, data),
                    "a2ui": surface_messages(surface_id, surface.components, data)}
    if dropped:
        result["dropped_document_ids"] = dropped
        result["note"] = "These ids are not documents of this job and were not shown."
    return result


tool_registry.register(ToolDef(
    name="render_ui", category="document",
    description=(
        "Show a panel in the chat (A2UI): documents the user may act on, or analytics (headline numbers, "
        "comparison tables, charts, risk analysis). Still give a short text answer; do not repeat the panel in "
        "text. Buttons only send a message: approving or rejecting still goes through bulk_approve / "
        "bulk_reject. Compute numbers with tools (execute_python, document fields), never guess.\n"
        f"Components ({', '.join(CATALOG)}) form a flat list; one must have id \"root\" (usually a Column). "
        "Lists of rows/points/items live in data and are bound with {path}.\n"
        "- Column / Row {children: [ids]} (Row: side by side, e.g. Metrics)\n"
        "- Text {text: string | {path}, variant?: body|caption|heading}\n"
        "- DocumentList {documents: {path: \"/documents\"}, selectable?: bool, selection?: \"/selected\"}; "
        "rows {document_id, note?}, the system fills in filename and status\n"
        f"- Button {{label, variant?: primary|secondary, action: {{event: {{name: {'|'.join(ACTION_EVENTS)}, "
        "context: {document_ids: {path: \"/selected\"}}}}}}\n"
        "- Metric {label, value: number | {path}, unit?, format?: number|currency|percent, delta?: {value, "
        "direction: up|down|flat, sentiment: good|bad|neutral, label?}} (cost up = up + bad; percent = 12.5 for 12.5%)\n"
        "- DataTable {columns: [{key, label, type: text|number|currency|percent|date|delta|risk, align?}], "
        "rows: {path}, caption?}; a row holds column keys (date \"YYYY-MM-DD\", delta like Metric.delta, risk = "
        "level) and an optional document_id\n"
        "- Chart {type: bar (categories) | line (over time), title?, x: key, series: [{key, label}], data: {path}, "
        "unit?, format?}; points {<x>: label, <series key>: number}\n"
        "- RiskList {items: {path}, title?}; item {title, level: critical|high|medium|low, category?, description, "
        "quote?, document_id?, page?, recommendation?}. quote must be copied verbatim from the document's text and "
        "needs document_id; the system checks it and marks quote_verified (do not send that field).\n"
        "- RiskBadge {level}\n"
        f"Limits: {MAX_COMPONENTS} components, {MAX_DOCUMENTS} documents, {MAX_TABLE_ROWS} rows x "
        f"{MAX_TABLE_COLUMNS} columns, {MAX_CHART_SERIES} series x {MAX_CHART_POINTS} points, "
        f"{MAX_RISK_ITEMS} risks. The result reports unverified_quotes: tell the user about them."
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
            "data": {"type": "object", "description": "The surface data model: only what components bind to"},
        },
        "required": ["components", "data"],
    },
    handler=_render_ui_handler,
))
