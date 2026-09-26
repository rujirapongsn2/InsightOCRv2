"""How well a schema's mapping matches what reviewers confirmed.

Compares each reviewed document's ``extracted_data`` (what the engines
returned) with ``reviewed_data`` (what a person confirmed), per field, per
schema version and per provider. The same comparison drives suggestions for
schema changes: labels that would have found the confirmed value, format
rules that rejected confirmed values, and required flags reviewers keep
leaving empty. Everything here is deterministic; no AI is called.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Iterable, Optional

from app.models.document import Document
from app.models.schema import DocumentSchema, SchemaVersion
from app.services.schema_studio import values_match

REVIEW_LIMIT = 1000
# Suggestions read every line of each document, so they look at fewer, newer ones.
SUGGESTION_LIMIT = 300
EXAMPLES_PER_FIELD = 5
MIN_LABEL_SUPPORT = 2
MIN_OPTIONAL_DOCUMENTS = 3
MAX_LABEL_LENGTH = 60
MAX_GENERATED_PATTERN = 200
OUTCOMES = ("correct", "corrected", "missed", "cleared")

# A line "label : value" whose label has at least one letter (Thai or Latin).
_LABEL_LINE = re.compile(r"^\s*(?P<label>[^:：\n]{1,%d}?)\s*[:：]\s*(?P<value>.+?)\s*$" % MAX_LABEL_LENGTH)
_HAS_LETTER = re.compile(r"[A-Za-z฀-๿]")


def is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or value == [] or value == {}


def classify(extracted: Any, reviewed: Any) -> Optional[str]:
    """``None`` when both are empty: nothing to find and nothing was found."""
    if is_empty(extracted) and is_empty(reviewed):
        return None
    if is_empty(extracted):
        return "missed"
    if is_empty(reviewed):
        return "cleared"
    return "correct" if values_match(reviewed, extracted) else "corrected"


def provider_group(evidence: Any) -> str:
    """``llm:OpenAI:gpt-4o`` → ``llm``; documents mapped before providers were recorded → ``unknown``."""
    evidence = evidence if isinstance(evidence, dict) else {}
    provider = evidence.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        # Older fixed-position evidence has a bbox but no provider name.
        return "bbox" if isinstance(evidence.get("bbox"), dict) else "unknown"
    return provider.split(":", 1)[0].strip().lower() or "unknown"


def _rate(correct: int, checked: int) -> Optional[float]:
    return round(correct / checked, 4) if checked else None


def reviewed_documents(db: Any, schema_id: Any, days: Optional[int] = None,
                       limit: int = REVIEW_LIMIT, with_text: bool = False) -> list[Any]:
    """Documents a person confirmed, newest first.

    Auto-confirmed documents (no reviewer) copy the extracted values and would
    count every field as correct, so they are left out.
    """
    columns = [Document.id, Document.filename, Document.extracted_data, Document.reviewed_data,
               Document.reviewed_at, Document.schema_version_id,
               Document.extraction_metadata["field_evidence"].label("field_evidence")]
    if with_text:
        columns.append(Document.ocr_text)
    query = db.query(*columns).filter(
        Document.schema_id == schema_id,
        Document.review_decision == "confirmed",
        Document.reviewed_by.isnot(None),
        Document.reviewed_data.isnot(None),
    )
    if days:
        query = query.filter(Document.reviewed_at >= datetime.now(timezone.utc) - timedelta(days=days))
    rows = query.order_by(Document.reviewed_at.desc()).limit(limit + 1).all()
    documents = []
    for row in rows:
        document = SimpleNamespace(**row._asdict())
        document.reviewed_data = _as_record(document.reviewed_data)
        document.extracted_data = _as_record(document.extracted_data)
        if isinstance(document.extracted_data, dict) and isinstance(document.reviewed_data, dict):
            documents.append(document)
    return documents


def _as_record(data: Any) -> Any:
    """The document review page saves one record as a one-item list."""
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        return data[0]
    return data


def _version_numbers(db: Any, schema_id: Any) -> dict[Any, int]:
    return {row.id: row.version for row in
            db.query(SchemaVersion.id, SchemaVersion.version).filter(SchemaVersion.schema_id == schema_id).all()}


def _counter() -> dict[str, int]:
    return {"checked": 0, "correct": 0}


def schema_accuracy(db: Any, schema: DocumentSchema, days: Optional[int] = None,
                    limit: int = REVIEW_LIMIT) -> dict[str, Any]:
    rows = reviewed_documents(db, schema.id, days, limit)
    truncated = len(rows) > limit
    rows = rows[:limit]
    versions = _version_numbers(db, schema.id)
    fields = [field for field in schema.fields or [] if field.get("name")]

    per_field: dict[str, dict[str, Any]] = {}
    for field in fields:
        per_field[field["name"]] = {
            "name": field["name"], "type": field.get("type"), "required": bool(field.get("required")),
            **{outcome: 0 for outcome in OUTCOMES}, "checked": 0,
            "by_provider": defaultdict(_counter), "by_version": defaultdict(_counter), "examples": [],
        }
    overall = _counter()
    by_version: dict[Any, dict[str, Any]] = defaultdict(lambda: {"documents": 0, **_counter()})

    for row in rows:
        version = versions.get(row.schema_version_id)
        by_version[version]["documents"] += 1
        evidence = row.field_evidence if isinstance(row.field_evidence, dict) else {}
        for name, stats in per_field.items():
            extracted, reviewed = row.extracted_data.get(name), row.reviewed_data.get(name)
            outcome = classify(extracted, reviewed)
            if outcome is None:
                continue
            correct = outcome == "correct"
            stats[outcome] += 1
            stats["checked"] += 1
            provider = provider_group(evidence.get(name)) if not is_empty(extracted) else "not_found"
            for bucket in (stats["by_provider"][provider], stats["by_version"][version], overall, by_version[version]):
                bucket["checked"] += 1
                bucket["correct"] += int(correct)
            if not correct and len(stats["examples"]) < EXAMPLES_PER_FIELD:
                stats["examples"].append({
                    "document_id": str(row.id), "filename": row.filename, "outcome": outcome,
                    "extracted": extracted, "reviewed": reviewed, "reviewed_at": row.reviewed_at,
                    "version": version,
                })

    field_list = []
    for stats in per_field.values():
        stats["accuracy"] = _rate(stats["correct"], stats["checked"])
        stats["by_provider"] = [{"provider": key, **value, "accuracy": _rate(value["correct"], value["checked"])}
                                for key, value in sorted(stats["by_provider"].items(), key=lambda item: -item[1]["checked"])]
        stats["by_version"] = [{"version": key, **value, "accuracy": _rate(value["correct"], value["checked"])}
                               for key, value in sorted(stats["by_version"].items(), key=lambda item: item[0] or 0, reverse=True)]
        field_list.append(stats)

    return {
        "schema_id": str(schema.id),
        "current_version": schema.current_version,
        "days": days,
        "reviewed_documents": len(rows),
        "limit": limit,
        "truncated": truncated,
        "overall": {**overall, "accuracy": _rate(overall["correct"], overall["checked"])},
        "versions": [{"version": key, **value, "accuracy": _rate(value["correct"], value["checked"])}
                     for key, value in sorted(by_version.items(), key=lambda item: item[0] or 0, reverse=True)],
        "fields": field_list,
    }


# ---------------------------------------------------------------------------
# Suggestions from reviewer corrections
# ---------------------------------------------------------------------------

class _FieldValues:
    """Per-field helpers for suggestions: the schema property is built once and
    label-pass outcomes are cached, because they run for every line of many documents."""

    def __init__(self, field: dict[str, Any]):
        from app.services.field_mapping import field_property

        self.field = field
        self.prop = field_property(field)
        self.is_date = self.prop.get("format") == "date"
        self._outcomes: dict[tuple[Any, tuple[str, ...]], str] = {}

    def normalize(self, raw: Any) -> Any:
        from app.services.field_mapping import normalize_field_value

        return normalize_field_value(raw, self.field, self.prop)

    def may_contain(self, line: str, reviewed: Any) -> bool:
        """Cheap check before normalising: the line must contain the confirmed value's
        characters (digits of the whole part for numbers). Dates can be reformatted, so they always pass."""
        if self.is_date:
            return True
        if isinstance(reviewed, (int, float)) and not isinstance(reviewed, bool):
            return str(int(abs(reviewed))) in re.sub(r"\D", "", line)
        needle = re.sub(r"[\W_]", "", str(reviewed).casefold())
        return not needle or needle in re.sub(r"[\W_]", "", line.casefold())

    def label_outcome(self, row: Any, labels: list[str], reviewed: Any) -> str:
        """What the label pass would do on this document: ``correct``, ``wrong`` or ``none``."""
        key = (row.id, tuple(labels))
        if key not in self._outcomes:
            self._outcomes[key] = self._label_outcome(row.ocr_text or "", labels, reviewed)
        return self._outcomes[key]

    def _label_outcome(self, text: str, labels: list[str], reviewed: Any) -> str:
        from app.services.field_mapping import label_value

        raw = label_value(text, labels)
        if raw is None:
            return "none"
        try:
            value = self.normalize(raw)
        except (ValueError, TypeError):
            return "none"  # rejected values are not accepted, so the label pass simply does not fire
        if is_empty(value):
            return "none"
        return "correct" if values_match(reviewed, value) else "wrong"

    def label_candidates(self, text: str, reviewed: Any) -> Iterable[tuple[str, str]]:
        """Labels on lines whose value (after ``:``) is the confirmed value."""
        seen: set[str] = set()
        for line in (text or "").splitlines():
            if ":" not in line and "：" not in line:
                continue
            match = _LABEL_LINE.match(line)
            if not match or not self.may_contain(match.group("value"), reviewed):
                continue
            label = " ".join(match.group("label").split()).strip(" *#|-–")
            if not label or not _HAS_LETTER.search(label) or label.casefold() in seen:
                continue
            try:
                value = self.normalize(match.group("value"))
            except (ValueError, TypeError):
                continue
            if not is_empty(value) and values_match(reviewed, value):
                seen.add(label.casefold())
                yield label, line.strip()


def _run_shape(value: str) -> list[tuple[str, str]]:
    """Split into runs: digits, Latin letters, Thai letters, or single other characters."""
    runs: list[tuple[str, str]] = []
    for match in re.finditer(r"\d+|[A-Za-z]+|[฀-๿]+|.", value, flags=re.DOTALL):
        token = match.group(0)
        kind = "d" if token[0].isdigit() else "l" if token[0].isascii() and token[0].isalpha() else \
            "t" if "฀" <= token[0] <= "๿" else "o"
        runs.append((kind, token))
    return runs


def generalize_pattern(values: list[str]) -> Optional[str]:
    """A format rule every confirmed value matches, or ``None`` when they differ in shape."""
    values = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    if not values:
        return None
    shapes = [_run_shape(value) for value in values]
    signature = [(kind, token if kind == "o" else "") for kind, token in shapes[0]]
    if any([(kind, token if kind == "o" else "") for kind, token in shape] != signature for shape in shapes[1:]):
        return None
    parts: list[str] = []
    for position, (kind, token) in enumerate(shapes[0]):
        tokens = [shape[position][1] for shape in shapes]
        lengths = sorted({len(item) for item in tokens})
        count = f"{{{lengths[0]}}}" if len(lengths) == 1 else f"{{{lengths[0]},{lengths[-1]}}}"
        if kind == "o":
            parts.append(re.escape(token))
        elif kind == "d":
            parts.append(r"\d" + count)
        elif len(set(tokens)) == 1:
            parts.append(re.escape(token))
        elif kind == "l":
            parts.append("[A-Za-z]" + count)
        else:
            parts.append("[฀-๿]+")
    pattern = "".join(parts)
    if len(pattern) > MAX_GENERATED_PATTERN or not all(re.fullmatch(pattern, value) for value in values):
        return None
    return pattern


def suggest_improvements(db: Any, schema: DocumentSchema, days: Optional[int] = None,
                         limit: int = REVIEW_LIMIT) -> dict[str, Any]:
    limit = min(limit, SUGGESTION_LIMIT)
    rows = reviewed_documents(db, schema.id, days, limit, with_text=True)[:limit]
    version_fields = {row.id: {field.get("name") for field in row.fields or []} for row in
                      db.query(SchemaVersion.id, SchemaVersion.fields).filter(SchemaVersion.schema_id == schema.id).all()}
    suggestions: list[dict[str, Any]] = []
    for field in schema.fields or []:
        name = field.get("name")
        if not name or field.get("locator"):
            continue  # fixed-position fields read the page image, not text labels
        rules = field.get("validation_rules") or {}
        labels = [label for label in rules.get("source_labels") or [] if isinstance(label, str) and label.strip()]
        observed = [(row, row.reviewed_data.get(name), classify(row.extracted_data.get(name), row.reviewed_data.get(name)))
                    for row in rows]
        # Documents processed before the field existed are empty for it without any
        # reviewer deciding so; only the version a document used says whether it had the field.
        had_field = [item for item in observed if name in version_fields.get(item[0].schema_version_id, ())
                     or (item[0].schema_version_id not in version_fields and name in item[0].reviewed_data)]

        if field.get("type") != "array":
            suggestion = _suggest_labels(_FieldValues(field), labels, observed)
            if suggestion:
                suggestions.append(suggestion)
        suggestion = _suggest_pattern(field, rules, observed)
        if suggestion:
            suggestions.append(suggestion)
        suggestion = _suggest_optional(field, had_field)
        if suggestion:
            suggestions.append(suggestion)

    return {"schema_id": str(schema.id), "reviewed_documents": len(rows), "suggestions": suggestions}


def _suggest_labels(helper: _FieldValues, labels: list[str],
                    observed: list[tuple[Any, Any, Optional[str]]]) -> Optional[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for row, reviewed, outcome in observed:
        if outcome not in {"missed", "corrected"} or is_empty(reviewed) or isinstance(reviewed, (list, dict)):
            continue
        for label, line in helper.label_candidates(row.ocr_text, reviewed):
            if label.casefold() in {existing.casefold() for existing in labels}:
                continue
            entry = candidates.setdefault(label.casefold(), {"label": label, "examples": []})
            if len(entry["examples"]) < 3:
                entry["examples"].append({"document_id": str(row.id), "filename": row.filename, "line": line[:200]})

    chosen: list[str] = []
    best: Optional[dict[str, Any]] = None
    for entry in candidates.values():
        trial = labels + chosen + [entry["label"]]
        fixed = broken = 0
        for row, reviewed, outcome in observed:
            if is_empty(reviewed) or isinstance(reviewed, (list, dict)) or not row.ocr_text:
                continue
            before = helper.label_outcome(row, labels + chosen, reviewed)
            after = helper.label_outcome(row, trial, reviewed)
            if before == "correct" and after != "correct":
                broken += 1
            elif after == "correct" and before != "correct" and outcome != "correct":
                fixed += 1
            elif after == "wrong" and before != "wrong":
                broken += 1
        if fixed >= MIN_LABEL_SUPPORT and broken == 0:
            chosen.append(entry["label"])
            best = best or {"examples": []}
            best["examples"].extend(entry["examples"])
            best.setdefault("fixed", 0)
            best["fixed"] += fixed
    if not chosen:
        return None
    return {
        "field": helper.field["name"], "kind": "add_labels", "labels": chosen,
        "documents_fixed": best["fixed"],
        "reason": "Reviewers entered these values next to labels the schema does not list yet.",
        "examples": best["examples"][:5],
    }


def _suggest_pattern(field: dict[str, Any], rules: dict[str, Any],
                     observed: list[tuple[Any, Any, Optional[str]]]) -> Optional[dict[str, Any]]:
    pattern = rules.get("pattern")
    if not pattern or field.get("type") not in (None, "text", "string"):
        return None
    confirmed = [(row, reviewed) for row, reviewed, _outcome in observed if isinstance(reviewed, str) and reviewed.strip()]
    try:
        rejected = [(row, reviewed) for row, reviewed in confirmed if not re.fullmatch(str(pattern), reviewed.strip())]
    except re.error:
        rejected = list(confirmed)
    if not rejected:
        return None
    examples = [{"document_id": str(row.id), "filename": row.filename, "value": value} for row, value in rejected[:5]]
    replacement = generalize_pattern([value for _row, value in confirmed])
    if replacement:
        return {"field": field["name"], "kind": "replace_pattern", "pattern": replacement, "current_pattern": pattern,
                "documents_rejected": len(rejected), "documents_checked": len(confirmed),
                "reason": "The format rule rejects values reviewers confirmed, so the engine drops them.",
                "examples": examples}
    return {"field": field["name"], "kind": "remove_pattern", "current_pattern": pattern,
            "documents_rejected": len(rejected), "documents_checked": len(confirmed),
            "reason": "The format rule rejects values reviewers confirmed, and those values have different shapes.",
            "examples": examples}


def _suggest_optional(field: dict[str, Any],
                      observed: list[tuple[Any, Any, Optional[str]]]) -> Optional[dict[str, Any]]:
    if not field.get("required") or len(observed) < MIN_OPTIONAL_DOCUMENTS:
        return None
    empty = sum(1 for _row, reviewed, _outcome in observed if is_empty(reviewed))
    if empty * 2 < len(observed):
        return None
    return {"field": field["name"], "kind": "make_optional", "documents_empty": empty,
            "documents_checked": len(observed),
            "reason": "Reviewers left this required field empty in most documents, so it often blocks completion.",
            "examples": []}


def apply_improvements(fields: list[dict[str, Any]], changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of ``fields`` with the accepted suggestions applied."""
    import copy

    updated = copy.deepcopy(fields or [])
    by_name = {field.get("name"): field for field in updated}
    for change in changes:
        field = by_name.get(change.get("field"))
        if field is None:
            raise ValueError(f'Field "{change.get("field")}" is no longer in the schema')
        rules = dict(field.get("validation_rules") or {})
        kind = change.get("kind")
        if kind == "add_labels":
            labels = [" ".join(str(label).split()) for label in change.get("labels") or []]
            labels = [label for label in labels if label and len(label) <= MAX_LABEL_LENGTH]
            if not labels:
                raise ValueError(f'No labels to add to "{field["name"]}"')
            existing = [label for label in rules.get("source_labels") or [] if isinstance(label, str)]
            known = {label.casefold() for label in existing}
            for label in labels:
                if label.casefold() not in known:
                    known.add(label.casefold())
                    existing.append(label)
            rules["source_labels"] = existing
        elif kind == "replace_pattern":
            pattern = str(change.get("pattern") or "")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f'The format rule for "{field["name"]}" is not valid') from exc
            if not pattern:
                raise ValueError(f'The format rule for "{field["name"]}" is empty')
            rules["pattern"] = pattern
        elif kind == "remove_pattern":
            rules.pop("pattern", None)
        elif kind == "make_optional":
            field["required"] = False
        else:
            raise ValueError(f"Unknown change: {kind}")
        field["validation_rules"] = rules or None
    return updated


def describe_changes(changes: list[dict[str, Any]]) -> str:
    counts = Counter(change.get("kind") for change in changes)
    names = sorted({change.get("field") for change in changes})
    return f"Applied {sum(counts.values())} review suggestion(s) to {', '.join(names)}"[:250]
