"""A2UI v0.9 panels for the Jobs agent, catalog v2.

The model calls one task-level tool per panel (show_documents, show_metrics,
show_table, show_chart, show_risks) with typed values. Each tool's arguments
are a Pydantic model below: the same model generates the tool's JSON schema
and validates the call, so the schema and the checks cannot drift apart.

The model never sends a formatted value, a delta or a verification result.
Values carry a kind; the system computes comparisons, resolves documents and
checks quotes; the frontend is the only formatter. Error messages are written
for the model, so it can fix its call and retry.
"""
from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Discriminator, Field, StringConstraints, Tag, ValidationError, model_validator

from app.utils.search_text import compact_search_text

A2UI_VERSION = "v0.9"
CATALOG_ID = "https://insightdoc.app/a2ui/catalogs/jobs/v2"
PANEL_TOOLS = ("show_documents", "show_metrics", "show_table", "show_chart", "show_risks")
# The whole surface is persisted with the tool result and replayed into the chat.
MAX_DATA_CHARS = 100_000
MAX_SOURCES = 200
MAX_PROBLEMS_SHOWN = 12

ValueKind = Literal["text", "count", "number", "money", "percent", "date", "month", "document"]
NumericKind = Literal["count", "number", "money", "percent"]
NUMERIC_KINDS: tuple[str, ...] = ("count", "number", "money", "percent")
HigherIs = Literal["good", "bad", "neutral"]
RiskLevel = Literal["critical", "high", "medium", "low"]
DEFAULT_CURRENCY = "THB"


def _text(limit: int) -> Any:
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=limit)]


Label = _text(60)
Title = _text(120)
Note = _text(300)
Paragraph = _text(1000)
Quote = _text(500)
Key = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,39}$")]
Currency = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$"), Field(description="ISO 4217 code, e.g. THB")]
DocumentId = Annotated[str, StringConstraints(min_length=1, max_length=64),
                       Field(description='A document "id" from list_documents')]
Number = Annotated[float, Field(allow_inf_nan=False)]
Cell = Union[Annotated[str, StringConstraints(max_length=300)], Number, None]
Sources = Annotated[list[DocumentId], Field(min_length=1, max_length=MAX_SOURCES,
                                            description="Every document the numbers were computed from")]


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _problem_list(problems: list[str]) -> None:
    if problems:
        raise ValueError("; ".join(problems[:MAX_PROBLEMS_SHOWN])
                         + (f" (and {len(problems) - MAX_PROBLEMS_SHOWN} more)" if len(problems) > MAX_PROBLEMS_SHOWN else ""))


def _is_integral(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and float(value).is_integer()


def _iso_problem(kind: str, value: Any, where: str) -> str | None:
    pattern = r"\d{4}-\d{2}-\d{2}" if kind == "date" else r"\d{4}-\d{2}"
    if isinstance(value, str) and re.fullmatch(pattern, value):
        try:
            date.fromisoformat(value if kind == "date" else f"{value}-01")
            return None
        except ValueError:
            pass
    example = '"2026-01-31"' if kind == "date" else '"2026-01"'
    return f"{where} must be an ISO {kind} like {example}, got {value!r}"


def value_problem(kind: str, value: Any, where: str) -> str | None:
    """Why value is not a raw value of kind, or None. null is always allowed (shown as a dash)."""
    if value is None:
        return None
    if kind in NUMERIC_KINDS:
        if isinstance(value, str):
            return f"{where} must be a number (not a string) for a {kind} column, got {value!r}"
        if kind == "count" and not _is_integral(value):
            return f"{where} must be a whole number for a count, got {value!r}"
        return None
    if kind in ("date", "month"):
        return _iso_problem(kind, value, where)
    if not isinstance(value, str) or not value.strip():
        return f"{where} must be a non-empty string for a {kind} column"
    return None


def _currency_problem(kind: str, currency: str | None, where: str) -> str | None:
    return f'{where}: "currency" is only for kind "money"' if currency and kind != "money" else None


def _unique_problem(keys: list[str], what: str) -> str | None:
    return f"{what} must be unique" if len(keys) != len(set(keys)) else None


# ── Tool arguments ─────────────────────────────────────────────────────────

class DocumentItem(_Args):
    document_id: DocumentId
    note: Note | None = None


class ShowDocuments(_Args):
    title: Title | None = None
    documents: list[DocumentItem] = Field(min_length=1, max_length=200)
    actions: list[Literal["approve", "reject"]] = Field(
        default=[], max_length=2, description="Buttons that act on the documents the user selects")

    @model_validator(mode="after")
    def _check(self) -> ShowDocuments:
        _problem_list([p for p in [_unique_problem(self.actions, "actions")] if p])
        return self


class Metric(_Args):
    label: Label
    kind: NumericKind
    currency: Currency | None = None
    value: Number
    previous: Number | None = Field(default=None, description="The value to compare with; the system computes the change")
    previous_label: Label | None = Field(default=None, description='What previous is, e.g. "ธ.ค. 2568"')
    higher_is: HigherIs = Field(default="neutral", description="Whether a higher value is good or bad for the user")

    @model_validator(mode="after")
    def _check(self) -> Metric:
        problems = [_currency_problem(self.kind, self.currency, "metric"),
                    value_problem(self.kind, self.value, "value"),
                    value_problem(self.kind, self.previous, "previous"),
                    '"previous_label" needs "previous"' if self.previous_label and self.previous is None else None]
        _problem_list([p for p in problems if p])
        return self


class ShowMetrics(_Args):
    title: Title | None = None
    metrics: list[Metric] = Field(min_length=1, max_length=6)
    sources: Sources


class ValueColumn(_Args):
    key: Key
    label: Label
    kind: ValueKind
    currency: Currency | None = None


class ChangeColumn(_Args):
    key: Key
    label: Label
    kind: Literal["change"]
    of: Key = Field(description="The column with the current value")
    vs: Key = Field(description="The column with the value to compare with (same kind)")
    higher_is: HigherIs = "neutral"


def _column_tag(value: Any) -> str:
    kind = value.get("kind") if isinstance(value, dict) else getattr(value, "kind", None)
    return "change" if kind == "change" else "value"


Column = Annotated[Union[Annotated[ValueColumn, Tag("value")], Annotated[ChangeColumn, Tag("change")]],
                   Discriminator(_column_tag)]


class ShowTable(_Args):
    title: Title | None = None
    columns: list[Column] = Field(min_length=1, max_length=12)
    rows: list[dict[str, Cell]] = Field(min_length=1, max_length=500,
                                        description="Objects mapping value column keys to raw values")
    sources: Sources

    @model_validator(mode="after")
    def _check(self) -> ShowTable:
        values = {c.key: c for c in self.columns if isinstance(c, ValueColumn)}
        changes = [c for c in self.columns if isinstance(c, ChangeColumn)]
        problems = [_unique_problem([c.key for c in self.columns], "column keys")]
        problems += [_currency_problem(c.kind, c.currency, f'column "{c.key}"') for c in values.values()]
        for change in changes:
            of, vs = values.get(change.of), values.get(change.vs)
            if of is None or vs is None or of.key == vs.key:
                problems.append(f'change column "{change.key}": "of" and "vs" must name two different value columns')
            elif of.kind not in NUMERIC_KINDS or of.kind != vs.kind or (of.currency or None) != (vs.currency or None):
                problems.append(f'change column "{change.key}": "{of.key}" and "{vs.key}" must be numeric columns '
                                "of the same kind (and currency)")
        for index, row in enumerate(self.rows):
            if computed := sorted(set(row) & {c.key for c in changes}):
                problems.append(f"rows[{index}] has {computed}: change columns are computed by the system; remove them")
            if extra := sorted(set(row) - set(values) - {c.key for c in changes}):
                problems.append(f"rows[{index}] has keys {extra} that are not columns; allowed: {sorted(values)}")
            problems += [value_problem(column.kind, row.get(key), f"rows[{index}].{key}") for key, column in values.items()]
        _problem_list([p for p in problems if p])
        return self


class ChartX(_Args):
    key: Key
    label: Label
    kind: Literal["text", "date", "month"]


class ChartSeries(_Args):
    key: Key
    label: Label


class ShowChart(_Args):
    title: Title
    type: Literal["bar", "line"] = Field(description="bar: categories; line: a trend over dates or months")
    x: ChartX
    series: list[ChartSeries] = Field(min_length=1, max_length=8, description='Fold the rest into one "อื่นๆ" series')
    value_kind: NumericKind
    currency: Currency | None = None
    points: list[dict[str, Cell]] = Field(min_length=1, max_length=200,
                                          description="Objects with the x key and one raw number per series key")
    sources: Sources

    @model_validator(mode="after")
    def _check(self) -> ShowChart:
        keys = [s.key for s in self.series]
        problems = [_unique_problem([self.x.key, *keys], "the x key and series keys"),
                    _currency_problem(self.value_kind, self.currency, "chart"),
                    f'a line chart needs x kind "date" or "month", not "{self.x.kind}"; use a bar chart for categories'
                    if self.type == "line" and self.x.kind == "text" else None]
        labels = [point.get(self.x.key) for point in self.points]
        for index, point in enumerate(self.points):
            if extra := sorted(set(point) - {self.x.key, *keys}):
                problems.append(f'points[{index}] has keys {extra}; a point holds only "{self.x.key}" and {keys}')
            label = point.get(self.x.key)
            problems.append(f"points[{index}].{self.x.key} is required" if label is None
                            else value_problem(self.x.kind, label, f"points[{index}].{self.x.key}"))
            problems += [value_problem(self.value_kind, point.get(key), f"points[{index}].{key}") for key in keys]
        problems.append(_unique_problem([str(label) for label in labels], f'"{self.x.key}" values'))
        if all(point.get(key) is None for point in self.points for key in keys):
            problems.append("the chart has no values")
        _problem_list([p for p in problems if p])
        return self


class RiskInput(_Args):
    title: Title
    level: RiskLevel
    category: Label
    description: Paragraph
    quote: Quote = Field(description="Copied verbatim from the document's text; the system checks it")
    page: Annotated[int, Field(ge=1, le=10_000)] | None = None
    recommendation: Paragraph


class ShowRisks(_Args):
    document_id: DocumentId
    title: Title | None = None
    risks: list[RiskInput] = Field(min_length=1, max_length=30)


# ── Tool schemas ───────────────────────────────────────────────────────────

def tool_parameters(model: type[BaseModel]) -> dict:
    """The model's JSON schema as a tool parameters schema.

    Some providers reject $ref/$defs in tool schemas, so definitions are
    inlined; title annotations are dropped and an optional field is its plain
    type (left out of "required") instead of anyOf [type, null].
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = walk(copy.deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]]))
            return {**target, **{k: walk(v) for k, v in node.items() if k != "$ref"}}
        out: dict = {}
        for key, value in node.items():
            if key == "title" or key == "discriminator":
                continue
            if key == "properties":
                out[key] = {name: walk(prop) for name, prop in value.items()}
            elif key == "oneOf":
                out["anyOf"] = walk(value)
            else:
                out[key] = walk(value)
        branches = out.get("anyOf")
        if branches and len(branches) == 2 and {"type": "null"} in branches and out.get("default", 0) is None:
            other = next(branch for branch in branches if branch != {"type": "null"})
            out = {**other, **{k: v for k, v in out.items() if k not in ("anyOf", "default")}}
        return out

    return walk(schema)


class PanelError(ValueError):
    """A panel tool call the model must correct. The message says how."""


def parse_args(tool: str, model: type[_Args], args: Any) -> Any:
    try:
        return model.model_validate(args)
    except ValidationError as error:
        problems = []
        for item in error.errors(include_url=False):
            where = ".".join(str(part) for part in item["loc"] if not str(part).startswith("function-"))
            message = item["msg"].removeprefix("Value error, ")
            problems.append(f"{where}: {message}" if where else message)
        raise PanelError(f"{tool} was not shown. Fix these problems and call {tool} again: "
                         + "; ".join(problems[:MAX_PROBLEMS_SHOWN])) from None


# ── Computed values ────────────────────────────────────────────────────────

def compare(value: float, previous: float, kind: str, higher_is: str) -> dict:
    """The change from previous to value: the only place a direction or sentiment is decided.

    delta is in the value's own unit (percentage points for a percent);
    percent is the relative change, absent for a percent value or a zero previous.
    """
    delta = round(value - previous, 6)
    direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
    if direction == "flat" or higher_is == "neutral":
        sentiment = "neutral"
    else:
        sentiment = "good" if (direction == "up") == (higher_is == "good") else "bad"
    percent = None if kind == "percent" or previous == 0 else round(delta / abs(previous) * 100, 1)
    return {"delta": delta, "percent": percent, "direction": direction, "sentiment": sentiment}


def quote_found(quote: str, document_text: str | None) -> bool:
    """Whether quote occurs in the document text under the same normalization as document search.

    That ignores whitespace (OCR of Thai text puts spaces inside words and line
    breaks inside clauses), case, and Thai versus Arabic digits; every other
    character must match.
    """
    needle = compact_search_text(quote)
    return bool(needle) and needle in compact_search_text(document_text)


# ── Surfaces ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DocumentRef:
    document_id: str
    filename: str

    def data(self) -> dict:
        return {"document_id": self.document_id, "filename": self.filename}


@dataclass(frozen=True)
class Panel:
    """A composed surface: the A2UI messages for the chat and the summary for the model.

    actions are the buttons ({component_id, name}) and document_ids the
    documents a click may name; the server checks a click against both.
    """
    components: list[dict]
    data: dict
    summary: dict
    actions: tuple[dict, ...] = ()
    document_ids: tuple[str, ...] = ()


def _currency(kind: str, currency: str | None) -> dict:
    return {"currency": currency or DEFAULT_CURRENCY} if kind == "money" else {}


def _column(*children: str) -> dict:
    return {"id": "root", "component": "Column", "children": list(children)}


def _heading(title: str | None) -> list[dict]:
    return [{"id": "title", "component": "Text", "text": title, "variant": "heading"}] if title else []


def _framed(title: str | None, *body: dict, sources: bool = True) -> list[dict]:
    """root → [title?, *body, sources?]."""
    extra = [{"id": "sources", "component": "Sources", "documents": {"path": "/sources"}}] if sources else []
    parts = [*_heading(title), *body, *extra]
    return [_column(*(c["id"] for c in parts)), *parts]


def _check_size(data: dict) -> None:
    size = len(json.dumps(data, ensure_ascii=False))
    if size > MAX_DATA_CHARS:
        raise PanelError(f"the panel data is {size} characters; the limit is {MAX_DATA_CHARS}. Aggregate or filter first.")


def documents_panel(args: ShowDocuments, rows: list[dict]) -> Panel:
    """rows: this job's documents in the model's order, {document_id, filename, status, note?}."""
    selectable = bool(args.actions)
    buttons = [{"id": action, "component": "Button", "label": label, "variant": variant,
                "action": {"event": {"name": f"{action}_documents", "context": {"document_ids": {"path": "/selected"}}}}}
               for action, label, variant in (("approve", "อนุมัติที่เลือก", "primary"), ("reject", "ปฏิเสธที่เลือก", "secondary"))
               if action in args.actions]
    body = [{"id": "list", "component": "DocumentList", "documents": {"path": "/documents"}, "selectable": selectable,
             **({"selection": "/selected"} if selectable else {})}]
    if buttons:
        body.append({"id": "actions", "component": "Row", "children": [b["id"] for b in buttons]})
    components = _framed(args.title, *body, sources=False) + buttons
    data = {"documents": rows, **({"selected": []} if selectable else {})}
    shown = [row["document_id"] for row in rows]
    actions = tuple({"component_id": b["id"], "name": b["action"]["event"]["name"]} for b in buttons)
    return Panel(components, data, {"shown": shown}, actions, tuple(shown) if actions else ())


def metrics_panel(args: ShowMetrics, sources: list[DocumentRef]) -> Panel:
    tiles, values, summary = [], [], []
    for index, metric in enumerate(args.metrics):
        tiles.append({"id": f"metric{index}", "component": "Metric", "label": metric.label, "kind": metric.kind,
                      **_currency(metric.kind, metric.currency),
                      **({"previous_label": metric.previous_label} if metric.previous_label else {}),
                      "data": {"path": f"/metrics/{index}"}})
        change = None if metric.previous is None else compare(metric.value, metric.previous, metric.kind, metric.higher_is)
        values.append({"value": metric.value, **({"previous": metric.previous, "change": change} if change else {})})
        summary.append({"label": metric.label, **({"change": change} if change else {})})
    row = {"id": "metrics", "component": "Row", "children": [t["id"] for t in tiles]}
    data = {"metrics": values, "sources": [s.data() for s in sources]}
    _check_size(data)
    return Panel(_framed(args.title, row) + tiles, data, {"metrics": summary, "sources": len(sources)})


def table_panel(args: ShowTable, sources: list[DocumentRef], documents: dict[str, DocumentRef]) -> Panel:
    """documents maps every id in a document column, as the model wrote it, to this job's document."""
    values = {c.key: c for c in args.columns if isinstance(c, ValueColumn)}
    columns = []
    for column in args.columns:
        if isinstance(column, ChangeColumn):
            of = values[column.of]
            columns.append({**column.model_dump(), "value_kind": of.kind, **_currency(of.kind, of.currency)})
        else:
            columns.append({**column.model_dump(exclude={"currency"}), **_currency(column.kind, column.currency)})
    rows = []
    for row in args.rows:
        out: dict[str, Any] = {}
        for column in args.columns:
            if isinstance(column, ChangeColumn):
                current, base = row.get(column.of), row.get(column.vs)
                out[column.key] = (None if current is None or base is None
                                   else compare(current, base, values[column.of].kind, column.higher_is))
            elif column.kind == "document" and row.get(column.key) is not None:
                out[column.key] = documents[row[column.key]].data()
            else:
                out[column.key] = row.get(column.key)
        rows.append(out)
    table = {"id": "table", "component": "DataTable", "columns": columns, "rows": {"path": "/rows"}}
    data = {"rows": rows, "sources": [s.data() for s in sources]}
    _check_size(data)
    return Panel(_framed(args.title, table), data,
                 {"rows": len(rows), "columns": len(columns), "sources": len(sources)})


def chart_panel(args: ShowChart, sources: list[DocumentRef]) -> Panel:
    points = [{args.x.key: point[args.x.key], **{s.key: point.get(s.key) for s in args.series}} for point in args.points]
    if args.type == "line":
        points.sort(key=lambda point: point[args.x.key])
    chart = {"id": "chart", "component": "Chart", "type": args.type, "title": args.title,
             "x": args.x.model_dump(), "series": [s.model_dump() for s in args.series],
             "value_kind": args.value_kind, **_currency(args.value_kind, args.currency), "points": {"path": "/points"}}
    data = {"points": points, "sources": [s.data() for s in sources]}
    _check_size(data)
    return Panel(_framed(None, chart), data, {"points": len(points), "series": len(args.series), "sources": len(sources)})


def risks_panel(args: ShowRisks, document: DocumentRef, text: str | None) -> Panel:
    items = [{"id": f"r{index}", **risk.model_dump(exclude_none=True), "quote_verified": quote_found(risk.quote, text)}
             for index, risk in enumerate(args.risks, start=1)]
    risk_list = {"id": "risks", "component": "RiskList", "document": {"path": "/document"}, "items": {"path": "/risks"}}
    data = {"document": document.data(), "risks": items}
    _check_size(data)
    summary = {"document": document.filename,
               "quotes_found": sum(item["quote_verified"] for item in items), "quotes_total": len(items),
               "risks": [{"id": item["id"], "title": item["title"], "level": item["level"],
                          "quote": "found" if item["quote_verified"] else "not_found"} for item in items]}
    return Panel(_framed(args.title, risk_list, sources=False), data, summary)


def surface_messages(surface_id: str, panel: Panel) -> list[dict]:
    return [
        {"version": A2UI_VERSION, "createSurface": {"surfaceId": surface_id, "catalogId": CATALOG_ID}},
        {"version": A2UI_VERSION, "updateComponents": {"surfaceId": surface_id, "components": panel.components}},
        {"version": A2UI_VERSION, "updateDataModel": {"surfaceId": surface_id, "path": "/", "value": panel.data}},
    ]
