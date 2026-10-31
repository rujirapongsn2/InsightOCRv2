"""The Jobs agent's panel tools: one call shows one A2UI panel in the chat.

Arguments are parsed by the models in app.agent.a2ui; this module resolves
document ids against the current job and composes the surface. The stored
result keeps "a2ui" for the chat; tool_content_for_llm strips it, so the model
sees only the itemised summary.
"""
from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from app.agent.a2ui import (
    DocumentRef, Panel, PanelError, ShowChart, ShowDocuments, ShowMetrics, ShowRisks, ShowTable, ValueColumn,
    chart_panel, documents_panel, metrics_panel, parse_args, risks_panel, surface_messages, table_panel,
    tool_parameters,
)
from app.agent.tools.document_tools import DocIdError, parse_doc_ids
from app.agent.tools.registry import ToolDef, tool_registry
from app.models.document import Document


def new_panel_id() -> str:
    return f"jobs-{uuid.uuid4().hex[:12]}"


def _job_rows(context, raw_ids: list[str], *columns) -> dict[str, Any]:
    """This job's documents among raw_ids, keyed by the id as the model wrote it."""
    ids = parse_doc_ids(raw_ids)
    if not ids:
        return {}
    found = {row.id: row for row in context.db.query(Document.id, *columns)
             .filter(Document.job_id == context.job_id, Document.id.in_(ids))}
    return {raw: found[uuid.UUID(raw)] for raw in raw_ids if uuid.UUID(raw) in found}


def _job_documents(context, raw_ids: list[str], what: str) -> dict[str, DocumentRef]:
    """Every id must be this job's document: a number must never lose its source silently."""
    rows = _job_rows(context, raw_ids, Document.filename)
    if unknown := sorted({raw for raw in raw_ids if raw not in rows}):
        raise PanelError(f"these {what} are not documents of this job: {unknown[:5]}. "
                         'Use the "id" values from list_documents.')
    return {raw: DocumentRef(str(row.id), row.filename) for raw, row in rows.items()}


def _sources(context, raw_ids: list[str]) -> list[DocumentRef]:
    refs = _job_documents(context, raw_ids, "sources")
    return list({ref.document_id: ref for ref in (refs[raw] for raw in raw_ids)}.values())


def _show_documents(args: ShowDocuments, context) -> tuple[Panel, dict]:
    raw_ids = [item.document_id for item in args.documents]
    known = _job_rows(context, raw_ids, Document.filename, Document.status)
    rows: dict[str, dict] = {}
    for item in args.documents:
        doc = known.get(item.document_id)
        if doc is not None and str(doc.id) not in rows:
            rows[str(doc.id)] = {"document_id": str(doc.id), "filename": doc.filename, "status": doc.status,
                                 **({"note": item.note} if item.note else {})}
    if not rows:
        raise PanelError('none of these documents belong to this job. Call list_documents and use its "id" values.')
    dropped = [raw for raw in dict.fromkeys(raw_ids) if raw not in known]
    note = {"dropped": dropped, "note": "These ids are not documents of this job and were not shown."} if dropped else {}
    return documents_panel(args, list(rows.values())), note


def _show_metrics(args: ShowMetrics, context) -> tuple[Panel, dict]:
    return metrics_panel(args, _sources(context, args.sources)), {}


def _show_table(args: ShowTable, context) -> tuple[Panel, dict]:
    keys = [c.key for c in args.columns if isinstance(c, ValueColumn) and c.kind == "document"]
    cited = list(dict.fromkeys(row[key] for row in args.rows for key in keys if row.get(key) is not None))
    documents = _job_documents(context, cited, "document column values") if cited else {}
    return table_panel(args, _sources(context, args.sources), documents), {}


def _show_chart(args: ShowChart, context) -> tuple[Panel, dict]:
    return chart_panel(args, _sources(context, args.sources)), {}


def _show_risks(args: ShowRisks, context) -> tuple[Panel, dict]:
    document = _job_documents(context, [args.document_id], "document_id")[args.document_id]
    # OCR text can be large, so it is read for this one document only.
    text = _job_rows(context, [args.document_id], Document.ocr_text)[args.document_id].ocr_text
    return risks_panel(args, document, text), {}


def _handler(name: str, model: type, show: Callable[[Any, Any], tuple[Panel, dict]]) -> Callable[..., Awaitable[dict]]:
    async def handle(args: dict, context) -> dict:
        try:
            panel, extra = show(parse_args(name, model, args), context)
        except DocIdError as error:
            return {"ok": False, "error": f"{name} was not shown: {error}"}
        except PanelError as error:
            message = str(error)
            return {"ok": False, "error": message if message.startswith(name) else f"{name} was not shown: {message}"}
        panel_id = new_panel_id()
        return {"ok": True, "panel_id": panel_id, **panel.summary, **extra,
                "a2ui": surface_messages(panel_id, panel)}
    return handle


_SHOWN = ("The panel already shows its sources and, for risks, which quotes were found; do not restate or "
          "reinterpret them in text. Still write a short text answer with the conclusion.")
_COMPUTED = ("Send raw values (numbers, ISO dates \"2026-01-31\", months \"2026-01\"); the system formats them. "
             "Compute every number first with tools (execute_python, get_document_detail, compare_documents); "
             "never estimate. sources: every document the numbers come from.")

PANELS = [
    ("show_documents", ShowDocuments, _show_documents,
     "Show a list of this job's documents the user may act on, e.g. documents awaiting approval or with problems. "
     "actions adds buttons for the selected documents; a click only sends a message, and approving or rejecting "
     "still goes through bulk_approve / bulk_reject. Filenames and statuses are filled in by the system. "
     "Ids that are not documents of this job are dropped and listed in the result."),
    ("show_metrics", ShowMetrics, _show_metrics,
     "Show 1-6 headline numbers as tiles. Give previous to compare with: the system computes the change, its "
     "direction and (with higher_is) whether it is good or bad. kind money takes currency (default THB); percent "
     "values are percentage points (12.5 = 12.5%). " + _COMPUTED + " " + _SHOWN),
    ("show_table", ShowTable, _show_table,
     "Show a comparison table. Each column has a kind; rows hold raw values for the value columns. A change column "
     "{kind: \"change\", of, vs, higher_is} is computed by the system from two numeric columns of the same kind: "
     "never put it in rows. Include a document column whenever a row comes from one document; it shows the "
     "filename with an open link. " + _COMPUTED + " " + _SHOWN),
    ("show_chart", ShowChart, _show_chart,
     "Show a chart: bar for categories, line for a trend over dates or months (the system sorts the points). "
     "value_kind formats every value. " + _COMPUTED + " " + _SHOWN),
    ("show_risks", ShowRisks, _show_risks,
     "Show a contract risk analysis for one document. Read its text first (get_document_detail). Each risk needs "
     "a quote copied verbatim from that document's text; the system checks every quote and the result lists each "
     "risk's id, title and quote: found | not_found. If you mention an unverified quote, use its title from the "
     "result. " + _SHOWN),
]

for _name, _model, _show, _description in PANELS:
    tool_registry.register(ToolDef(
        name=_name, category="document", description=_description,
        parameters_schema=tool_parameters(_model), handler=_handler(_name, _model, _show),
    ))
