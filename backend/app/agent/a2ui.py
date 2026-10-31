"""A2UI v0.9 surfaces for the Jobs agent: catalog, boundary validation and messages.

The agent's `render_ui` arguments are parsed once here. Everything downstream
(document resolution, message building, the frontend renderer) trusts the
shape this module guarantees. Error messages are written for the model, so it
can fix its call and retry.
"""
from __future__ import annotations

import copy
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from app.utils.search_text import compact_search_text

A2UI_VERSION = "v0.9"
CATALOG_ID = "https://insightdoc.app/a2ui/catalogs/jobs/v1"
MAX_COMPONENTS = 50
MAX_DOCUMENTS = 200
MAX_TEXT_CHARS = 2000
MAX_LABEL_CHARS = 60
MAX_NOTE_CHARS = 300
# Also bounds the analytics data (500 table rows fit only when they are short):
# the whole surface is persisted with the tool result and replayed into the chat.
MAX_DATA_CHARS = 100_000
ACTION_EVENTS = ("approve_documents", "reject_documents", "ask_agent")
TEXT_VARIANTS = ("body", "caption", "heading")
BUTTON_VARIANTS = ("primary", "secondary")

MAX_TABLE_ROWS = 500
MAX_TABLE_COLUMNS = 12
MAX_CHART_SERIES = 8
MAX_CHART_POINTS = 200
MAX_RISK_ITEMS = 50
MAX_KEY_CHARS = 40
MAX_UNIT_CHARS = 20
MAX_TITLE_CHARS = 120
MAX_CELL_CHARS = 300
MAX_QUOTE_CHARS = 500
MAX_DESCRIPTION_CHARS = 1000
MAX_PAGE = 10_000
NUMBER_FORMATS = ("number", "currency", "percent")
COLUMN_TYPES = ("text", "number", "currency", "percent", "date", "delta", "risk")
NUMERIC_COLUMN_TYPES = ("number", "currency", "percent")
COLUMN_ALIGNS = ("left", "center", "right")
CHART_TYPES = ("bar", "line")
DIRECTIONS = ("up", "down", "flat")
SENTIMENTS = ("good", "bad", "neutral")
RISK_LEVELS = ("critical", "high", "medium", "low")
RISK_ITEM_KEYS = ("title", "level", "category", "description", "quote", "document_id", "page", "recommendation")
ANALYTIC_COMPONENTS = ("Metric", "DataTable", "Chart", "RiskList", "RiskBadge")


class SurfaceError(ValueError):
    """A render_ui call the model must correct. The message says how."""


def is_binding(value: Any) -> bool:
    return (
        isinstance(value, dict) and set(value) == {"path"}
        and isinstance(value["path"], str) and value["path"].startswith("/")
    )


def _pointer_tokens(path: str) -> list[str]:
    return [t.replace("~1", "/").replace("~0", "~") for t in path.split("/")[1:]] if path != "/" else []


def resolve_pointer(data: Any, path: str) -> Any:
    """RFC 6901 lookup; None when any segment is missing."""
    node = data
    for token in _pointer_tokens(path):
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
            node = node[int(token)]
        else:
            return None
    return node


def _set_pointer(data: dict, path: str, value: Any) -> None:
    tokens = _pointer_tokens(path)
    node = data
    for token in tokens[:-1]:
        node = node.setdefault(token, {})
    node[tokens[-1]] = value


# ── Catalog: one validator per component type ──────────────────────────────
# Each validator returns the problems with one component's props.

def _unknown_props(comp: dict, allowed: set[str]) -> list[str]:
    extra = sorted(set(comp) - allowed - {"id", "component"})
    return [f"unknown prop(s) {extra}; allowed: {sorted(allowed)}"] if extra else []


def _check_children(comp: dict) -> list[str]:
    errors = _unknown_props(comp, {"children"})
    children = comp.get("children")
    if not isinstance(children, list) or not children or not all(isinstance(c, str) for c in children):
        errors.append('"children" must be a non-empty array of component ids')
    return errors


def _check_text(comp: dict) -> list[str]:
    errors = _unknown_props(comp, {"text", "variant"})
    text = comp.get("text")
    if not (isinstance(text, str) and text.strip()) and not is_binding(text):
        errors.append('"text" must be a non-empty string or {"path": "/pointer"}')
    elif isinstance(text, str) and len(text) > MAX_TEXT_CHARS:
        errors.append(f'"text" is longer than {MAX_TEXT_CHARS} characters')
    if "variant" in comp and comp["variant"] not in TEXT_VARIANTS:
        errors.append(f'"variant" must be one of {list(TEXT_VARIANTS)}')
    return errors


def _check_document_list(comp: dict) -> list[str]:
    errors = _unknown_props(comp, {"documents", "selectable", "selection"})
    if not is_binding(comp.get("documents")):
        errors.append('"documents" must be a binding like {"path": "/documents"}')
    selectable = comp.get("selectable", False)
    if not isinstance(selectable, bool):
        errors.append('"selectable" must be true or false')
    selection = comp.get("selection")
    if selectable and not (isinstance(selection, str) and selection.startswith("/") and selection != "/"):
        errors.append('a selectable DocumentList needs "selection", a JSON pointer such as "/selected"')
    if selection is not None and not selectable:
        errors.append('"selection" is only valid with "selectable": true')
    return errors


def _check_button(comp: dict) -> list[str]:
    errors = _unknown_props(comp, {"label", "variant", "action"})
    label = comp.get("label")
    if not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL_CHARS:
        errors.append(f'"label" must be a non-empty string of at most {MAX_LABEL_CHARS} characters')
    if "variant" in comp and comp["variant"] not in BUTTON_VARIANTS:
        errors.append(f'"variant" must be one of {list(BUTTON_VARIANTS)}')
    event = comp.get("action", {}).get("event") if isinstance(comp.get("action"), dict) else None
    if not isinstance(event, dict):
        errors.append('"action" must be {"event": {"name": ..., "context": {...}}}')
        return errors
    if event.get("name") not in ACTION_EVENTS:
        errors.append(f'action event name {event.get("name")!r} is not allowed; use one of {list(ACTION_EVENTS)}')
    context = event.get("context", {})
    if not isinstance(context, dict):
        errors.append('action "context" must be an object')
    else:
        for key, value in context.items():
            if not (is_binding(value) or isinstance(value, (str, int, float, bool)) or value is None):
                errors.append(f'action context "{key}" must be a literal or {{"path": "/pointer"}}')
    return errors


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _string_problem(value: Any, where: str, limit: int, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        return f"{where} must be a non-empty string of at most {limit} characters"
    return None


def _enum_problem(value: Any, where: str, allowed: tuple[str, ...], *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    return None if value in allowed else f"{where} must be one of {list(allowed)}"


def _key_problem(key: Any, where: str) -> str | None:
    if not isinstance(key, str) or not key or len(key) > MAX_KEY_CHARS or "/" in key or "~" in key:
        return f'{where} must be a string of at most {MAX_KEY_CHARS} characters without "/" or "~"'
    return None


def _problems(*problems: str | None) -> list[str]:
    return [p for p in problems if p]


def _delta_problems(delta: Any, where: str) -> list[str]:
    if not isinstance(delta, dict) or set(delta) - {"value", "direction", "sentiment", "label"}:
        return [f'{where} must be {{"value": number, "direction": {"|".join(DIRECTIONS)}, '
                f'"sentiment": {"|".join(SENTIMENTS)}, "label"?: string}}']
    value, direction = delta.get("value"), delta.get("direction")
    errors = _problems(
        None if _is_number(value) else f"{where}.value must be a finite number",
        _enum_problem(direction, f"{where}.direction", DIRECTIONS),
        _enum_problem(delta.get("sentiment"), f"{where}.sentiment", SENTIMENTS),
        _string_problem(delta.get("label"), f"{where}.label", MAX_LABEL_CHARS, required=False),
    )
    # "flat" means no change at all: a rounded-away change is still up or down, so flat needs exactly 0.
    if _is_number(value) and ((direction == "up" and value < 0) or (direction == "down" and value > 0)
                              or (direction == "flat" and value != 0)):
        errors.append(f'{where}: direction "{direction}" contradicts value {value}; '
                      'use a value >= 0 for "up", <= 0 for "down", and exactly 0 for "flat"')
    return errors


def _check_metric(comp: dict) -> list[str]:
    errors = _unknown_props(comp, {"label", "value", "unit", "format", "delta"})
    value = comp.get("value")
    errors.extend(_problems(
        None if _is_number(value) or is_binding(value) else '"value" must be a finite number or {"path": "/pointer"}',
        _string_problem(comp.get("label"), '"label"', MAX_LABEL_CHARS),
        _string_problem(comp.get("unit"), '"unit"', MAX_UNIT_CHARS, required=False),
        _enum_problem(comp.get("format"), '"format"', NUMBER_FORMATS, required=False),
    ))
    if "delta" in comp:
        errors.extend(_delta_problems(comp["delta"], '"delta"'))
    return errors


def _check_data_table(comp: dict) -> list[str]:
    errors = _unknown_props(comp, {"columns", "rows", "caption"})
    columns = comp.get("columns")
    if not isinstance(columns, list) or not 1 <= len(columns) <= MAX_TABLE_COLUMNS:
        errors.append(f'"columns" must be an array of 1 to {MAX_TABLE_COLUMNS} columns')
        columns = []
    keys: list[str] = []
    for index, column in enumerate(columns):
        where = f'"columns"[{index}]'
        if not isinstance(column, dict) or set(column) - {"key", "label", "type", "align"}:
            errors.append(f'{where} must be {{"key", "label", "type", "align"?}}')
            continue
        keys.append(str(column.get("key")))
        errors.extend(_problems(
            _key_problem(column.get("key"), f"{where}.key"),
            _string_problem(column.get("label"), f"{where}.label", MAX_LABEL_CHARS),
            _enum_problem(column.get("type"), f"{where}.type", COLUMN_TYPES),
            _enum_problem(column.get("align"), f"{where}.align", COLUMN_ALIGNS, required=False),
        ))
        if column.get("key") == "document_id":
            errors.append(f'{where}: "document_id" is not a column; put it on each row and the table '
                          "shows an open link for that document")
    if len(keys) != len(set(keys)):
        errors.append('"columns" keys must be unique')
    errors.extend(_problems(
        None if is_binding(comp.get("rows")) else '"rows" must be a binding like {"path": "/rows"}',
        _string_problem(comp.get("caption"), '"caption"', MAX_TITLE_CHARS, required=False),
    ))
    return errors


def _check_chart(comp: dict) -> list[str]:
    errors = _unknown_props(comp, {"type", "title", "x", "series", "data", "unit", "format"})
    errors.extend(_problems(
        _enum_problem(comp.get("type"), '"type"', CHART_TYPES),
        _string_problem(comp.get("title"), '"title"', MAX_TITLE_CHARS, required=False),
        _key_problem(comp.get("x"), '"x"'),
        _string_problem(comp.get("unit"), '"unit"', MAX_UNIT_CHARS, required=False),
        _enum_problem(comp.get("format"), '"format"', NUMBER_FORMATS, required=False),
        None if is_binding(comp.get("data")) else '"data" must be a binding like {"path": "/points"}',
    ))
    series = comp.get("series")
    if not isinstance(series, list) or not 1 <= len(series) <= MAX_CHART_SERIES:
        errors.append(f'"series" must be an array of 1 to {MAX_CHART_SERIES} series; fold the rest into one "อื่นๆ" series')
        series = []
    keys = [str(comp.get("x"))]
    for index, item in enumerate(series):
        where = f'"series"[{index}]'
        if not isinstance(item, dict) or set(item) != {"key", "label"}:
            errors.append(f'{where} must be {{"key", "label"}}')
            continue
        keys.append(str(item["key"]))
        errors.extend(_problems(_key_problem(item["key"], f"{where}.key"),
                                _string_problem(item["label"], f"{where}.label", MAX_LABEL_CHARS)))
    if len(keys) != len(set(keys)):
        errors.append('"x" and the "series" keys must all be different')
    return errors


def _check_risk_list(comp: dict) -> list[str]:
    return _unknown_props(comp, {"items", "title"}) + _problems(
        None if is_binding(comp.get("items")) else '"items" must be a binding like {"path": "/risks"}',
        _string_problem(comp.get("title"), '"title"', MAX_TITLE_CHARS, required=False),
    )


def _check_risk_badge(comp: dict) -> list[str]:
    return _unknown_props(comp, {"level"}) + _problems(_enum_problem(comp.get("level"), '"level"', RISK_LEVELS))


CATALOG: dict[str, Callable[[dict], list[str]]] = {
    "Column": _check_children,
    "Row": _check_children,
    "Text": _check_text,
    "DocumentList": _check_document_list,
    "Button": _check_button,
    "Metric": _check_metric,
    "DataTable": _check_data_table,
    "Chart": _check_chart,
    "RiskList": _check_risk_list,
    "RiskBadge": _check_risk_badge,
}


# ── Bound values: what each component reads from data, and the shape it needs ──
# A check gets the pointer and the value there and returns its problems.

ValueCheck = Callable[[str, Any], list[str]]


def _text_value(path: str, value: Any) -> list[str]:
    if isinstance(value, str) and len(value) <= MAX_TEXT_CHARS:
        return []
    return [f'data "{path}" is shown by a Text and must be a string of at most {MAX_TEXT_CHARS} characters']


def _number_value(path: str, value: Any) -> list[str]:
    return [] if _is_number(value) else [f'data "{path}" is shown by a Metric and must be a finite number']


def _date_problem(value: Any, where: str) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            date.fromisoformat(value)
            return None
        except ValueError:
            pass
    return f'{where} must be a date "YYYY-MM-DD"'


def _cell_problems(column_type: str, value: Any, where: str) -> list[str]:
    if value is None:
        return []
    if column_type in NUMERIC_COLUMN_TYPES:
        return [] if _is_number(value) else [f"{where} must be a finite number (or null)"]
    if column_type == "date":
        return _problems(_date_problem(value, where))
    if column_type == "delta":
        return _delta_problems(value, where)
    if column_type == "risk":
        return _problems(_enum_problem(value, where, RISK_LEVELS))
    return _problems(_string_problem(value, where, MAX_CELL_CHARS))


def _array_problem(path: str, value: Any, limit: int, what: str) -> str | None:
    if not isinstance(value, list):
        return f'data "{path}" must be an array of {what}'
    if len(value) > limit:
        return f'data "{path}" has {len(value)} {what}; the limit is {limit}. Aggregate or filter first'
    return None


def _at(path: str, index: int) -> Callable[..., str]:
    """Names a row, or a key in it, in an error: at() -> data "/rows/3", at("x") -> data "/rows/3/x"."""
    return lambda *keys: 'data "' + "/".join((path, str(index), *keys)) + '"'


def _document_id_problem(row: dict, at: Callable[..., str]) -> str | None:
    if "document_id" in row and not isinstance(row["document_id"], str):
        return f'{at("document_id")} must be a document "id" string from list_documents'
    return None


def _table_rows(columns: list[dict]) -> ValueCheck:
    types = {c["key"]: c["type"] for c in columns}

    def check(path: str, rows: Any) -> list[str]:
        if problem := _array_problem(path, rows, MAX_TABLE_ROWS, "rows"):
            return [problem]
        errors: list[str] = []
        for index, row in enumerate(rows):
            at = _at(path, index)
            if not isinstance(row, dict):
                errors.append(f"{at()} must be an object keyed by column key")
                continue
            if extra := sorted(set(row) - set(types) - {"document_id"}):
                errors.append(f'{at()} has keys {extra} that are not columns; allowed: {sorted(types)} and "document_id"')
            errors.extend(_problems(_document_id_problem(row, at)))
            for key, column_type in types.items():
                errors.extend(_cell_problems(column_type, row.get(key), at(key)))
        return errors
    return check


def _chart_points(comp: dict) -> ValueCheck:
    x, keys = comp["x"], [s["key"] for s in comp["series"]]

    def check(path: str, points: Any) -> list[str]:
        if problem := _array_problem(path, points, MAX_CHART_POINTS, "points"):
            return [problem]
        if not points:
            return [f'data "{path}" has no points']
        errors: list[str] = []
        for index, point in enumerate(points):
            at = _at(path, index)
            if not isinstance(point, dict):
                errors.append(f'{at()} must be an object like {{"{x}": ..., "{keys[0]}": number}}')
                continue
            if extra := sorted(set(point) - {x, *keys}):
                errors.append(f'{at()} has keys {extra}; a point holds only "{x}" and the series keys {keys}')
            label = point.get(x)
            if not (_is_number(label) or (isinstance(label, str) and label.strip() and len(label) <= MAX_LABEL_CHARS)):
                errors.append(f"{at(x)} must be a number or a string of at most {MAX_LABEL_CHARS} characters")
            errors.extend(f"{at(key)} must be a finite number (or null)"
                          for key in keys if point.get(key) is not None and not _is_number(point.get(key)))
        return errors
    return check


def _risk_items(path: str, items: Any) -> list[str]:
    if problem := _array_problem(path, items, MAX_RISK_ITEMS, "risk items"):
        return [problem]
    errors: list[str] = []
    for index, item in enumerate(items):
        at = _at(path, index)
        if not isinstance(item, dict):
            errors.append(f"{at()} must be an object with {list(RISK_ITEM_KEYS)}")
            continue
        if "quote_verified" in item:
            errors.append(f"{at('quote_verified')} is set by the system after checking the quote against the "
                          "document; remove it")
        if extra := sorted(set(item) - set(RISK_ITEM_KEYS) - {"quote_verified"}):
            errors.append(f"{at()} has unknown keys {extra}; allowed: {list(RISK_ITEM_KEYS)}")
        page = item.get("page")
        errors.extend(_problems(
            _string_problem(item.get("title"), at("title"), MAX_TITLE_CHARS),
            _enum_problem(item.get("level"), at("level"), RISK_LEVELS),
            _string_problem(item.get("category"), at("category"), MAX_LABEL_CHARS, required=False),
            _string_problem(item.get("description"), at("description"), MAX_DESCRIPTION_CHARS),
            _string_problem(item.get("quote"), at("quote"), MAX_QUOTE_CHARS, required=False),
            _string_problem(item.get("recommendation"), at("recommendation"), MAX_DESCRIPTION_CHARS, required=False),
            _document_id_problem(item, at),
            None if page is None or (isinstance(page, int) and not isinstance(page, bool) and 1 <= page <= MAX_PAGE)
            else f"{at('page')} must be a page number from 1",
            f"{at()} has a quote but no document_id; cite the document the quote comes from"
            if "quote" in item and "document_id" not in item else None,
        ))
    return errors


BOUND_VALUES: dict[str, Callable[[dict], list[tuple[str, ValueCheck]]]] = {
    "Text": lambda c: [(c["text"]["path"], _text_value)] if is_binding(c["text"]) else [],
    "Metric": lambda c: [(c["value"]["path"], _number_value)] if is_binding(c["value"]) else [],
    "DataTable": lambda c: [(c["rows"]["path"], _table_rows(c["columns"]))],
    "Chart": lambda c: [(c["data"]["path"], _chart_points(c))],
    "RiskList": lambda c: [(c["items"]["path"], _risk_items)],
}

# Components whose rows may cite documents; the handler checks those ids and quotes.
CITING_BINDINGS: dict[str, str] = {"DataTable": "rows", "RiskList": "items"}


@dataclass(frozen=True)
class Surface:
    components: list[dict]
    data: dict
    # (documents pointer, the agent's rows at that pointer) for each DocumentList
    document_lists: list[tuple[str, list[dict]]]
    # (pointer, rows) for each DataTable / RiskList; rows may cite a document_id
    cited_rows: list[tuple[str, list[dict]]]

    def document_ids(self) -> list[str]:
        return [row["document_id"] for _, rows in self.document_lists for row in rows]

    def cited_document_ids(self) -> list[str]:
        return [row["document_id"] for _, rows in self.cited_rows for row in rows if "document_id" in row]


def _check_tree(by_id: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    parents: dict[str, str] = {}
    for comp_id, comp in by_id.items():
        for child in comp.get("children") or []:
            if child not in by_id:
                errors.append(f'component "{comp_id}" references child "{child}", which is not defined')
            elif child in parents:
                errors.append(f'component "{child}" has two parents ("{parents[child]}" and "{comp_id}"); each component may appear once')
            else:
                parents[child] = comp_id
    if errors:
        return errors
    if "root" not in by_id:
        return ['no component has id "root"; the top-level component must use id "root"']
    if "root" in parents:
        return [f'"root" cannot be a child (it is listed under "{parents["root"]}")']
    # With single parents and a parentless root, a cycle is any component whose
    # parent chain never reaches root.
    for comp_id in by_id:
        seen = {comp_id}
        node = comp_id
        while node in parents:
            node = parents[node]
            if node in seen:
                return [f'components form a cycle through "{comp_id}"; children must form a tree under "root"']
            seen.add(node)
    return []


def _check_document_rows(path: str, rows: Any) -> list[str]:
    if not isinstance(rows, list):
        return [f'data at "{path}" must be an array like [{{"document_id": "..."}}]']
    errors: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("document_id"), str):
            errors.append(f'data "{path}/{index}" must be an object with a string "document_id"')
        elif set(row) - {"document_id", "note"}:
            errors.append(f'data "{path}/{index}" may only contain "document_id" and "note"; '
                          "filename and status are filled in by the system")
        elif "note" in row and not (isinstance(row["note"], str) and len(row["note"]) <= MAX_NOTE_CHARS):
            errors.append(f'data "{path}/{index}/note" must be a string of at most {MAX_NOTE_CHARS} characters')
    return errors


def _escape(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _object_path_problem(data: dict, path: str) -> str | None:
    """Why a pointer the system writes through is not a plain object path in data, or None.

    Missing parents are fine (they are created as objects); a list or a value on
    the way is not, because writing there would fail or replace it.
    """
    node = data
    for token in _pointer_tokens(path)[:-1]:
        if token not in node:
            return None
        node = node[token]
        if not isinstance(node, dict):
            kind = "an array" if isinstance(node, list) else "not an object"
            return (f'pointer "{path}" must lead through objects only, but "{token}" is {kind}; '
                    'use a plain path such as "/documents" or "/selected"')
    return None


def _overlaps(path: str, other: str) -> bool:
    return path == other or path.startswith(other + "/") or other.startswith(path + "/")


def _unused_data(node: dict, prefix: str, used: set[str]) -> list[str]:
    errors: list[str] = []
    for key, value in node.items():
        path = f"{prefix}/{_escape(str(key))}"
        if path in used:
            continue
        if isinstance(value, dict) and any(u.startswith(path + "/") for u in used):
            errors.extend(_unused_data(value, path, used))
        else:
            errors.append(f'data "{path}" is not used by any component; remove it')
    return errors


def _check_data(by_id: dict[str, dict], data: dict) -> list[str]:
    """Data may hold only what components bind to, in the shapes they render."""
    lists = [c for c in by_id.values() if c["component"] == "DocumentList"]
    documents = [c["documents"]["path"] for c in lists]
    selections = [c["selection"] for c in lists if c.get("selection")]
    reads = [read for c in by_id.values() for read in BOUND_VALUES.get(c["component"], lambda _: [])(c)]
    read_paths = [path for path, _ in reads]
    errors = [p for p in (_object_path_problem(data, path) for path in documents + selections + read_paths) if p]
    errors.extend(f'data "{path}" is bound by another component but overlaps the DocumentList documents at "{doc}", '
                  'whose rows the system replaces; bind it to a separate key such as "/rows"'
                  for doc in documents for path in read_paths if _overlaps(path, doc))
    for selection in selections:
        errors.extend(f'"selection" "{selection}" overlaps the documents at "{doc}"; use a separate key such as "/selected"'
                      for doc in documents if _overlaps(selection, doc))
        value = resolve_pointer(data, selection)
        if value is not None and not (isinstance(value, list) and len(value) <= MAX_DOCUMENTS
                                      and all(isinstance(v, str) for v in value)):
            errors.append(f'data "{selection}" is a selection and must be an array of document ids (or left out)')
    for path, check in reads:
        errors.extend(check(path, resolve_pointer(data, path)))
    for comp in by_id.values():
        if comp["component"] != "Button":
            continue
        for key, value in comp["action"]["event"].get("context", {}).items():
            if is_binding(value) and value["path"] not in selections:
                errors.append(f'component "{comp["id"]}" (Button): action context "{key}" may only bind to a '
                              'DocumentList "selection" pointer; use a literal otherwise')
    errors.extend(_unused_data(data, "", set(documents + selections + read_paths)))
    size = len(json.dumps(data, ensure_ascii=False, default=str))
    if size > MAX_DATA_CHARS:
        errors.append(f'"data" is {size} characters; the limit is {MAX_DATA_CHARS}')
    return errors


def parse_surface(components: Any, data: Any) -> Surface:
    """Validate render_ui arguments. Raises SurfaceError listing every problem."""
    if not isinstance(components, list) or not components:
        raise SurfaceError('"components" must be a non-empty array of {"id", "component", ...props}')
    if len(components) > MAX_COMPONENTS:
        raise SurfaceError(f"too many components ({len(components)}); the limit is {MAX_COMPONENTS}")
    data = {} if data is None else data
    if not isinstance(data, dict):
        raise SurfaceError('"data" must be an object')

    errors: list[str] = []
    by_id: dict[str, dict] = {}
    for index, comp in enumerate(components):
        if not isinstance(comp, dict) or not isinstance(comp.get("id"), str) or not comp["id"]:
            errors.append(f"components[{index}] needs a string \"id\"")
            continue
        comp_id = comp["id"]
        if comp_id in by_id:
            errors.append(f'component id "{comp_id}" is used twice; ids must be unique')
            continue
        by_id[comp_id] = comp
        check = CATALOG.get(comp.get("component"))
        if check is None:
            errors.append(f'component "{comp_id}" has unknown type {comp.get("component")!r}; '
                          f"use one of {list(CATALOG)}")
            continue
        errors.extend(f'component "{comp_id}" ({comp["component"]}): {problem}' for problem in check(comp))
    if not errors:
        errors.extend(_check_tree(by_id))
    if not errors:
        errors.extend(_check_data(by_id, data))

    document_lists: list[tuple[str, list[dict]]] = []
    for comp in by_id.values():
        if comp.get("component") != "DocumentList" or not is_binding(comp.get("documents")):
            continue
        path = comp["documents"]["path"]
        rows = resolve_pointer(data, path)
        problems = _check_document_rows(path, rows)
        errors.extend(problems)
        if not problems:
            document_lists.append((path, rows))
    total = sum(len(rows) for _, rows in document_lists)
    if total > MAX_DOCUMENTS:
        errors.append(f"too many documents ({total}); the limit is {MAX_DOCUMENTS}")

    if errors:
        shown = errors[:12]
        more = f" (and {len(errors) - len(shown)} more)" if len(errors) > len(shown) else ""
        raise SurfaceError("render_ui was not shown. Fix these problems and call render_ui again: "
                           + "; ".join(shown) + more)
    cited_paths = dict.fromkeys(comp[CITING_BINDINGS[comp["component"]]]["path"]
                                for comp in by_id.values() if comp["component"] in CITING_BINDINGS)
    cited_rows = [(path, resolve_pointer(data, path)) for path in cited_paths]
    return Surface(components=components, data=data, document_lists=document_lists, cited_rows=cited_rows)


def quote_found(quote: str, document_text: str | None) -> bool:
    """Whether quote occurs in the document text under the same normalization as document search.

    That ignores whitespace (OCR of Thai text puts spaces inside words and line
    breaks inside clauses), case, and Thai versus Arabic digits; every other
    character must match.
    """
    needle = compact_search_text(quote)
    return bool(needle) and needle in compact_search_text(document_text)


@dataclass(frozen=True)
class CitedDocument:
    document_id: str
    text: str | None


def resolve_citations(surface: Surface, data: dict, documents: dict[str, CitedDocument]) -> dict:
    """Canonicalise cited document ids and set quote_verified from the documents' text.

    documents maps each id as the model wrote it to this job's document. An id
    missing from it is a corrective error: an analysis row must not silently
    lose its source.
    """
    unknown = sorted({raw for raw in surface.cited_document_ids() if raw not in documents})
    if unknown:
        raise SurfaceError(f"render_ui was not shown: these document_id values in table rows or risk items are not "
                           f"documents of this job: {unknown[:5]}. Use the \"id\" values from list_documents and "
                           "call render_ui again.")
    data = copy.deepcopy(data)
    for path, rows in surface.cited_rows:
        resolved = []
        for row in rows:
            row = dict(row)
            cited = documents.get(row.get("document_id", ""))
            if cited:
                row["document_id"] = cited.document_id
            if "quote" in row:
                row["quote_verified"] = bool(cited) and quote_found(row["quote"], cited.text)
            resolved.append(row)
        _set_pointer(data, path, resolved)
    return data


def analytics_summary(components: list[dict], data: dict) -> dict:
    """What the model is told about the analytics it rendered: counts, not values."""
    counts = Counter(c["component"] for c in components if c["component"] in ANALYTIC_COMPONENTS)
    if not counts:
        return {}
    summary: dict[str, Any] = {"components": dict(counts)}
    risk_paths = dict.fromkeys(c["items"]["path"] for c in components if c["component"] == "RiskList")
    items = [item for path in risk_paths for item in resolve_pointer(data, path)]
    if risk_paths:
        levels = Counter(item["level"] for item in items)
        summary["risks"] = {level: levels[level] for level in RISK_LEVELS}
        summary["quotes"] = sum("quote" in item for item in items)
        summary["unverified_quotes"] = sum(item.get("quote_verified") is False for item in items)
    return summary


def resolve_documents(surface: Surface, rows_by_id: dict[str, dict]) -> tuple[dict, list[str]]:
    """Replace each DocumentList's rows with system rows; drop ids not in rows_by_id.

    rows_by_id must come from the database, scoped to the current job, so a
    displayed filename or status can never come from the model.
    """
    data = copy.deepcopy(surface.data)
    dropped: list[str] = []
    for path, rows in surface.document_lists:
        resolved: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            doc_id = row["document_id"]
            known = rows_by_id.get(doc_id)
            if known is None:
                dropped.append(doc_id)
                continue
            if known["document_id"] in seen:
                continue
            seen.add(known["document_id"])
            resolved.append({**known, **({"note": row["note"]} if "note" in row else {})})
        if rows and not resolved:
            raise SurfaceError(f'none of the document ids at "{path}" belong to this job. '
                               "Call list_documents and use its \"id\" values, then call render_ui again.")
        _set_pointer(data, path, resolved)
    for comp in surface.components:
        selection = comp.get("selection") if comp.get("component") == "DocumentList" else None
        if selection and resolve_pointer(data, selection) is None:
            _set_pointer(data, selection, [])
    return data, dropped


def surface_messages(surface_id: str, components: list[dict], data: dict) -> list[dict]:
    return [
        {"version": A2UI_VERSION, "createSurface": {"surfaceId": surface_id, "catalogId": CATALOG_ID}},
        {"version": A2UI_VERSION, "updateComponents": {"surfaceId": surface_id, "components": components}},
        {"version": A2UI_VERSION, "updateDataModel": {"surfaceId": surface_id, "path": "/", "value": data}},
    ]
