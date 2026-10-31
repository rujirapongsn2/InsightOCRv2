"""A2UI v0.9 surfaces for the Jobs agent: catalog, boundary validation and messages.

The agent's `render_ui` arguments are parsed once here. Everything downstream
(document resolution, message building, the frontend renderer) trusts the
shape this module guarantees. Error messages are written for the model, so it
can fix its call and retry.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable

A2UI_VERSION = "v0.9"
CATALOG_ID = "https://insightdoc.app/a2ui/catalogs/jobs/v1"
MAX_COMPONENTS = 50
MAX_DOCUMENTS = 200
MAX_TEXT_CHARS = 2000
MAX_LABEL_CHARS = 60
MAX_NOTE_CHARS = 300
ACTION_EVENTS = ("approve_documents", "reject_documents", "ask_agent")
TEXT_VARIANTS = ("body", "caption", "heading")
BUTTON_VARIANTS = ("primary", "secondary")


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


def _check_column(comp: dict) -> list[str]:
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
    if is_binding(comp.get("documents")) and selection == comp["documents"]["path"]:
        errors.append('"selection" must be a different pointer from "documents"')
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


CATALOG: dict[str, Callable[[dict], list[str]]] = {
    "Column": _check_column,
    "Text": _check_text,
    "DocumentList": _check_document_list,
    "Button": _check_button,
}


@dataclass(frozen=True)
class Surface:
    components: list[dict]
    data: dict
    # (documents pointer, the agent's rows at that pointer) for each DocumentList
    document_lists: list[tuple[str, list[dict]]]

    def document_ids(self) -> list[str]:
        return [row["document_id"] for _, rows in self.document_lists for row in rows]


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
    return Surface(components=components, data=data, document_lists=document_lists)


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
            if doc_id in seen:
                continue
            seen.add(doc_id)
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
