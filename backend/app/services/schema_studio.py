"""Evidence-backed schema suggestions from one or more sample documents.

The AI proposes fields, but every proposal has to point at text that really is
in the samples. This module verifies each proposal deterministically (the quote
exists, the value parses as the proposed type, the source labels and pattern
actually reproduce the value) and derives confidence from those checks rather
than trusting a number the model made up.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Optional

from pydantic import BaseModel, ValidationError, field_validator

from app.schemas.schema import FIELD_NAME_PATTERN

logger = logging.getLogger(__name__)

FIELD_TYPES = {"text", "number", "date", "currency", "boolean", "array"}
COLUMN_TYPES = {"text", "number", "date", "currency"}
PROMPT_TEXT_BUDGET = 40_000
# Long enough to review fields and test several samples before saving.
SAMPLE_TTL_SECONDS = 7200
MAX_PATTERN_LENGTH = 200
MAX_FIELDS = 60
# Reasoning models spend part of max_tokens thinking before they answer; a
# 4k budget left the JSON truncated or empty on a 2-page quotation.
SUGGESTION_MAX_TOKENS = 16_000

# Weights for derived confidence: evidence dominates because a value that is
# not in the document cannot be extracted from it.
WEIGHT_EVIDENCE = 0.5
WEIGHT_TYPE = 0.25
WEIGHT_HELPER = 0.15
WEIGHT_DESCRIPTION = 0.10


class ColumnProposal(BaseModel):
    name: str
    type: str = "text"


class EvidenceProposal(BaseModel):
    sample: Optional[str] = None
    line: Optional[str] = None
    quote: str = ""


class FieldProposal(BaseModel):
    name: str
    label: str = ""
    type: str = "text"
    description: str = ""
    source_labels: list[str] = []
    pattern: Optional[str] = None
    evidence: list[EvidenceProposal] = []
    columns: list[ColumnProposal] = []

    @field_validator("evidence", mode="before")
    @classmethod
    def _one_or_many(cls, value: Any) -> Any:
        if value is None:
            return []
        return [value] if isinstance(value, (dict, EvidenceProposal)) else value


RESPONSE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["fields"],
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "label", "type", "description", "source_labels", "pattern", "evidence", "columns"],
                "properties": {
                    "name": {"type": "string"},
                    "label": {"type": "string"},
                    "type": {"type": "string", "enum": sorted(FIELD_TYPES)},
                    "description": {"type": "string"},
                    "source_labels": {"type": "array", "items": {"type": "string"}},
                    "pattern": {"type": ["string", "null"]},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["sample", "line", "quote"],
                            "properties": {
                                "sample": {"type": "string"},
                                "line": {"type": ["string", "null"]},
                                "quote": {"type": "string"},
                            },
                        },
                    },
                    "columns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "type"],
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string", "enum": sorted(COLUMN_TYPES)},
                            },
                        },
                    },
                },
            },
        }
    },
}

SYSTEM_PROMPT = (
    "You design extraction schemas for an OCR document platform. You receive one or more sample documents "
    "of the same kind, named S1, S2, ... with lines numbered L1, L2, ... inside each sample. Propose the "
    "stable business fields a company would extract from every document of this kind. Rules:\n"
    "1. Only propose fields whose value is visible in at least one sample. Never invent values.\n"
    "2. evidence: one entry per sample where the field appears, with sample (\"S1\"), line (\"L12\") and "
    "quote. quote must be the value copied exactly, character for character, from that sample (the value "
    "only, without its label). Leave out samples where the field does not appear.\n"
    "3. name: English snake_case. label: the field's human name in the document's language.\n"
    "4. type: text, number, date, currency, boolean, or array. Use array for tables or repeated line items, "
    "list the table's columns in columns (name in snake_case, type text/number/date/currency), and quote one "
    "row of the table per sample as evidence. For non-array fields, columns is [].\n"
    "5. description: one sentence saying what the value is and how to recognise it; mention the label text.\n"
    "6. source_labels: the exact label text printed just before the value on the same line (for example "
    "\"Invoice No\" in \"Invoice No: INV-001\"). Use [] when the value has no label.\n"
    "7. pattern: a short regular expression the value always matches when the format is fixed "
    "(for example ^INV-\\d{6}$), otherwise null.\n"
    "Return JSON only, shaped as {\"fields\": [...]}."
)


def number_document(text: str, budget: int = PROMPT_TEXT_BUDGET) -> tuple[str, dict[str, int], bool]:
    """Number non-empty lines as L1..Ln for the prompt.

    Returns (numbered_text, line_id -> 1-based line number in ``text``,
    truncated). The line map lets evidence point back at the original text.
    """
    numbered: list[str] = []
    line_numbers: dict[str, int] = {}
    size = 0
    truncated = False
    counter = 0
    for index, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip():
            continue
        counter += 1
        entry = f"L{counter}: {line}"
        if size + len(entry) + 1 > budget:
            truncated = True
            break
        numbered.append(entry)
        line_numbers[f"L{counter}"] = index
        size += len(entry) + 1
    return "\n".join(numbered), line_numbers, truncated


def number_samples(samples: list[dict[str, str]], budget: int = PROMPT_TEXT_BUDGET) -> tuple[str, list[bool]]:
    """Number each sample's lines under an ``=== Sample Sn ===`` header.

    The prompt budget is split evenly so one long sample cannot crowd out the
    others. Returns (prompt_text, truncated flag per sample).
    """
    share = max(2000, budget // max(1, len(samples)))
    blocks: list[str] = []
    truncated: list[bool] = []
    for index, sample in enumerate(samples, start=1):
        numbered, _lines, cut = number_document(sample["text"], share)
        blocks.append(f"=== Sample S{index}: {sample.get('filename') or 'document'} ===\n{numbered}")
        truncated.append(cut)
    return "\n\n".join(blocks), truncated


def build_messages(numbered_text: str, document_type: Optional[str], truncated: bool) -> list[dict[str, str]]:
    note = "\n(Some samples were cut at the size limit; their later pages are not shown.)" if truncated else ""
    user = (
        f"Document type: {document_type or 'unknown'}\n\n"
        f"Samples:\n{numbered_text}{note}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _strip_fences(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
    start, end = content.find("{"), content.rfind("}")
    return content[start:end + 1] if start != -1 and end > start else content


def parse_proposals(content: str) -> tuple[list[FieldProposal], list[str]]:
    """Parse the model's JSON. Raises ValueError when the envelope is unusable;
    individually invalid fields are dropped and reported instead."""
    data = json.loads(_strip_fences(content))
    raw_fields = data.get("fields") if isinstance(data, dict) else data
    if not isinstance(raw_fields, list):
        raise ValueError("Response must contain a `fields` array")
    proposals: list[FieldProposal] = []
    dropped: list[str] = []
    for raw in raw_fields[:MAX_FIELDS]:
        try:
            proposals.append(FieldProposal.model_validate(raw))
        except ValidationError as exc:
            name = raw.get("name") if isinstance(raw, dict) else None
            dropped.append(f"{name or 'unnamed'}: invalid proposal ({exc.error_count()} errors)")
    return proposals, dropped


async def request_proposals(provider: Any, numbered_text: str, document_type: Optional[str],
                            truncated: bool) -> tuple[list[FieldProposal], dict[str, Any]]:
    """Ask the provider for field proposals.

    OpenAI-compatible providers get strict structured output first, then JSON
    mode, then a plain request — providers differ in what they accept. One
    repair round is attempted when the JSON cannot be parsed.
    """
    from openai import AsyncOpenAI, BadRequestError, UnprocessableEntityError
    from app.services.ai_suggestion_service import _normalize_openai_base_url

    messages = build_messages(numbered_text, document_type, truncated)
    response_formats: list[Optional[dict[str, Any]]] = [
        {"type": "json_schema", "json_schema": {"name": "schema_suggestion", "strict": True,
                                                  "schema": RESPONSE_JSON_SCHEMA}},
        {"type": "json_object"},
        None,
    ]
    meta: dict[str, Any] = {"structured_output": None, "repaired": False, "repair_reason": None, "dropped": []}
    async with AsyncOpenAI(api_key=provider.api_key, base_url=_normalize_openai_base_url(provider.api_url),
                           timeout=90.0, max_retries=0) as client:
        async def complete(msgs: list[dict[str, str]], response_format: Optional[dict[str, Any]]) -> str:
            kwargs: dict[str, Any] = {"model": provider.model or "gpt-4o-mini", "messages": msgs,
                                      "temperature": 0, "max_tokens": SUGGESTION_MAX_TOKENS}
            if response_format:
                kwargs["response_format"] = response_format
            response = await client.chat.completions.create(**kwargs)
            choice = response.choices[0] if response.choices else None
            content = (choice.message.content or "").strip() if choice else ""
            if choice is not None and choice.finish_reason == "length":
                raise ValueError(
                    "The AI provider ran out of output space before finishing the suggestions. "
                    "Try a shorter sample, or choose a provider with a larger output limit."
                )
            if not content:
                raise ValueError("AI provider returned an empty response")
            return content

        content = ""
        chosen_format: Optional[dict[str, Any]] = None
        for response_format in response_formats:
            try:
                content = await complete(messages, response_format)
                chosen_format = response_format
                break
            except (BadRequestError, UnprocessableEntityError):
                if response_format is None:
                    raise
                continue
        meta["structured_output"] = (chosen_format or {}).get("type", "none")
        try:
            proposals, dropped = parse_proposals(content)
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("Schema suggestion JSON invalid (%s, %d chars, ends %r); asking provider to repair",
                           exc, len(content), content[-80:])
            meta["repaired"] = True
            meta["repair_reason"] = f"{type(exc).__name__}: {str(exc)[:160]} (response {len(content)} chars)"
            repair = messages + [
                {"role": "assistant", "content": content[:8000]},
                {"role": "user", "content": f"That was not valid JSON for the required shape ({exc}). "
                                            "Return the corrected JSON only."},
            ]
            try:
                proposals, dropped = parse_proposals(await complete(repair, chosen_format))
            except (ValueError, json.JSONDecodeError) as repair_exc:
                raise ValueError(
                    "The AI provider did not return valid field suggestions. Try again, or choose another AI provider."
                ) from repair_exc
    meta["dropped"] = dropped
    return proposals, meta


async def suggest_fields(db: Any, samples: list[dict[str, str]], document_type: Optional[str]) -> dict[str, Any]:
    """Propose and verify fields for the given sample texts.

    Raises ValueError with a message fit for the user when no usable
    suggestion comes back.
    """
    from app.services.ai_suggestion_service import AISuggestionService

    texts = [sample["text"] for sample in samples]
    ai_service = AISuggestionService(db)
    provider = ai_service._get_ai_settings()
    numbered_text, truncated_flags = number_samples(samples)
    if provider.provider_type == "openai_compatible":
        proposals, meta = await request_proposals(provider, numbered_text, document_type, any(truncated_flags))
    else:
        # Legacy providers own their prompt, so proposals arrive without
        # evidence; verification still runs and marks them for review.
        legacy = await ai_service.suggest_fields_from_ocr(ocr_content=texts[0], document_type=document_type)
        proposals = proposals_from_legacy(legacy.suggested_fields)
        meta = {"structured_output": "provider_prompt", "repaired": False, "repair_reason": None, "dropped": []}
    fields, dropped = verify_proposals(proposals, texts)
    if not fields:
        raise ValueError("AI provider returned no field suggestions")
    return {
        "suggested_fields": fields,
        "summary": summarize(fields),
        "truncated": truncated_flags,
        "raw_result": {
            "source": "schema_studio",
            "provider_used": provider.display_name,
            "structured_output": meta["structured_output"],
            "repaired": meta["repaired"],
            "repair_reason": meta.get("repair_reason"),
            "dropped": meta["dropped"] + dropped,
            "document_truncated": any(truncated_flags),
        },
    }


def proposals_from_legacy(suggested_fields: list[Any]) -> list[FieldProposal]:
    """Adapt fields from providers whose prompt we don't control (no evidence)."""
    return [
        FieldProposal(name=field.name, type=field.type, description=field.description or "",
                      evidence=[EvidenceProposal(sample="S1", quote=str(field.example_value or ""))])
        for field in suggested_fields
    ]


def _snake_case(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value or "")
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    value = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").lower()
    value = re.sub(r"_+", "_", value)
    if value and not re.match(r"[A-Za-z_]", value):
        value = f"field_{value}"
    return value


# Letters/digits that make a value part of a longer token (Latin and Thai digits).
_TOKEN_CHAR = "A-Za-z0-9\u0E50-\u0E59"


def _flexible_pattern(quote: str) -> str:
    """Match the quote allowing any whitespace between words, but not inside a
    longer token: "100" must not match in "1000", "INV-1005" or "100.50".

    A digit edge only rejects neighbouring digits (so "1,250.00" is still found
    in "1,250.00THB" or "THB1,250.00"); a Latin-letter edge rejects letters and
    digits. Thai text has no spaces between words, so a Thai edge is not
    constrained.
    """
    body = r"\s+".join(re.escape(part) for part in quote.split())
    digit = "0-9\u0E50-\u0E59"
    start, end = "", ""
    if re.match(f"[{digit}]", quote):
        start = f"(?<![{digit}])(?<![{digit}][.,])"
    elif re.match(f"[{_TOKEN_CHAR}]", quote):
        start = f"(?<![{_TOKEN_CHAR}])"
    if re.search(f"[{digit}]$", quote):
        end = f"(?![{digit}])(?![.,][{digit}])"
    elif re.search(f"[{_TOKEN_CHAR}]$", quote):
        end = f"(?![{_TOKEN_CHAR}])"
    return start + body + end


def locate_quote(quote: str, text: str) -> dict[str, Any]:
    """Find a quote in the document, tolerating whitespace differences only."""
    quote = (quote or "").strip()
    if not quote:
        return {"match": "none", "count": 0}
    matches = list(re.finditer(_flexible_pattern(quote), text))
    if not matches:
        return {"match": "none", "count": 0}
    first = matches[0]
    line_start = text.rfind("\n", 0, first.start()) + 1
    line_end = text.find("\n", first.end())
    line_end = len(text) if line_end == -1 else line_end
    line = text[line_start:line_end].strip()
    return {
        "match": "once" if len(matches) == 1 else "multiple",
        "count": len(matches),
        "line_no": text.count("\n", 0, first.start()) + 1,
        "context": line[:240],
        "quote": first.group(),
    }


def _normalize_amount(text: str) -> Optional[str]:
    """Reduce a written amount to a plain number string, or None if it is not one.

    Accepts a currency sign or code (attached or spaced), %, Thai "1,250.-",
    accounting negatives "(1,250.00)" / "1,250.00-", and thousands separated by
    spaces. Anything else ("INV-001", "12/08/2026") is not a number.
    """
    value = re.sub(r"(?i)THB|USD|EUR|baht|บาท|[฿$€£¥%]", "", text or "").strip()
    negative = False
    if value.startswith("(") and value.endswith(")"):
        negative, value = True, value[1:-1].strip()
    value = re.sub(r"[.,]-$", "", value)
    if value.endswith("-") and not value.startswith("-"):
        negative, value = True, value[:-1].strip()
    value = re.sub(r"(?<=\d) (?=\d{3}(?:\D|$))", "", value)
    if not re.fullmatch(r"[-+]?\d[\d,]*(?:\.\d+)?", value):
        return None
    return f"-{value.lstrip('+-')}" if negative else value


def _type_check(quote: str, field_type: str, name: str) -> tuple[Optional[bool], str]:
    """Parse the quote with the same coercion rules mapping uses."""
    from app.tasks.document_tasks import (
        _normalise_fixed_position_value,
        _normalize_schema_value,
        map_field_type_to_json_schema,
    )

    if field_type == "boolean":
        return None, "Yes/No values are not checked automatically"
    if not quote:
        return False, "No sample value to check"
    schema = map_field_type_to_json_schema(field_type, "")
    candidate = quote
    if field_type in {"number", "currency"}:
        normalized = _normalize_amount(quote)
        if normalized is None:
            return False, f"“{quote[:60]}” does not read as {field_type}"
        candidate = normalized
    try:
        if schema.get("format") == "date":
            value = _normalise_fixed_position_value(candidate, schema, name)
        else:
            value = _normalize_schema_value(candidate, schema, name)
    except (ValueError, TypeError):
        return False, f"“{quote[:60]}” does not read as {field_type}"
    if value in (None, ""):
        return False, f"“{quote[:60]}” does not read as {field_type}"
    return True, f"Reads as {field_type}: {value}"


def _label_reproduces(label: str, quote: str, text: str) -> bool:
    """True when mapping's deterministic label rule would return exactly the quote.

    Mirrors the `source_labels` pass in field_mapping.map_fields: that pass
    trusts a label outright, so only labels that reproduce the value are kept.
    """
    label = (label or "").strip()
    if not label or not quote:
        return False
    pattern = r"^\s*(?:" + re.escape(label) + r")\s*[:：]\s*(.+?)\s*$"
    matches = list(re.finditer(pattern, text, flags=re.MULTILINE))
    return len(matches) == 1 and " ".join(matches[0].group(1).split()) == " ".join(quote.split())


def _pattern_matches(pattern: Optional[str], quote: str) -> bool:
    if not pattern or not quote or len(pattern) > MAX_PATTERN_LENGTH:
        return False
    try:
        return re.fullmatch(pattern.strip(), quote.strip()) is not None
    except re.error:
        return False


def locate_row(quote: str, text: str) -> dict[str, Any]:
    """Evidence for a table: models rarely copy a row verbatim (cell spacing,
    pipes), so accept a row when most of its cells appear on one document line."""
    exact = locate_quote(quote, text)
    if exact["match"] != "none":
        return exact
    # Cells when the quote keeps separators, otherwise words: PDF tables often
    # arrive with a whole column merged into one cell, so no row exists verbatim.
    parts = [cell.strip() for cell in re.split(r"\s*\|\s*|\t|\s{2,}", quote or "") if cell.strip()]
    if len(parts) < 2:
        parts = [word for word in (quote or "").split() if len(word) > 1 or word.isdigit()]
    if len(parts) < 2:
        return exact
    best: tuple[float, int, str] = (0.0, 0, "")
    for line_no, line in enumerate(text.splitlines(), start=1):
        share = sum(1 for part in parts if part in line) / len(parts)
        if share > best[0]:
            best = (share, line_no, line)
    if best[0] >= 0.6:
        return {"match": "multiple", "count": 1, "line_no": best[1], "context": best[2].strip()[:240],
                "quote": quote, "partial": True}
    return exact


def _sample_index(label: Optional[str], sample_count: int) -> Optional[int]:
    """'S2' -> 1. Evidence without a sample label belongs to the only sample."""
    if not label:
        return 0 if sample_count == 1 else None
    match = re.fullmatch(r"\s*S?(\d+)\s*", str(label), flags=re.IGNORECASE)
    if not match:
        return None
    index = int(match.group(1)) - 1
    return index if 0 <= index < sample_count else None


def _evidence_message(results: list[dict[str, Any]], found: int) -> str:
    total = len(results)
    primary = next((r for r in results if r["match"] != "none"), results[0])
    if found == 0:
        return "Value not found in the document" if any(r["quote"] for r in results) else "No sample value given"
    if total == 1:
        if primary.get("partial"):
            return "Most cells of the sample row were found; check the columns"
        if primary["match"] == "multiple":
            return f"Value appears {primary['count']} times; check it is the right one"
        return "Value found in the document"
    message = f"Found in {found} of {total} samples"
    if any(r.get("partial") for r in results):
        message += "; table rows only partly matched, check the columns"
    elif any(r["match"] == "multiple" for r in results):
        message += "; appears more than once in some samples"
    return message


def verify_proposals(proposals: list[FieldProposal], texts: list[str] | str) -> tuple[list[dict[str, Any]], list[str]]:
    """Turn raw proposals into schema fields plus review metadata (``studio``).

    With several samples, a field is checked in each: found in every sample it
    is proposed as required; found in some it stays optional for review.
    """
    texts = [texts] if isinstance(texts, str) else list(texts)
    sample_count = len(texts)
    fields: list[dict[str, Any]] = []
    dropped: list[str] = []
    used_names: set[str] = set()
    seen_quotes: dict[str, dict[str, Any]] = {}

    for proposal in proposals:
        name = _snake_case(proposal.name) or _snake_case(proposal.label)
        if not name or not FIELD_NAME_PATTERN.fullmatch(name):
            dropped.append(f"{proposal.name or proposal.label or 'unnamed'}: no usable field name")
            continue
        base, suffix = name, 2
        while name in used_names:
            name, suffix = f"{base}_{suffix}", suffix + 1
        field_type = proposal.type if proposal.type in FIELD_TYPES else "text"

        quotes: list[str] = [""] * sample_count
        for item in proposal.evidence:
            index = _sample_index(item.sample, sample_count)
            if index is not None and not quotes[index] and item.quote.strip():
                quotes[index] = item.quote.strip()
        locate = locate_row if field_type == "array" else locate_quote
        results = [{"sample": index, **locate(quote, texts[index]), "quote": quote}
                   for index, quote in enumerate(quotes)]
        for result, text in zip(results, texts):
            if result["match"] != "none" and not result.get("partial"):
                result["quote"] = locate_quote(result["quote"], text).get("quote", result["quote"])
        found_results = [r for r in results if r["match"] != "none"]
        found = len(found_results)
        present_quotes = [r["quote"] for r in found_results]
        evidence_score = sum({"once": 1.0, "multiple": 0.6}.get(r["match"], 0.0) for r in results) / sample_count

        checks: list[dict[str, Any]] = [{
            "key": "evidence",
            "ok": found > 0,
            "message": _evidence_message(results, found),
        }]

        array_config = None
        if field_type == "array":
            columns: list[dict[str, str]] = []
            for column in proposal.columns:
                column_name = _snake_case(column.name)
                if column_name and FIELD_NAME_PATTERN.fullmatch(column_name) and column_name not in {c["name"] for c in columns}:
                    columns.append({"name": column_name, "type": column.type if column.type in COLUMN_TYPES else "text"})
            type_ok: Optional[bool] = bool(columns)
            type_message = f"{len(columns)} table columns" if columns else "Table has no usable columns"
            if columns:
                array_config = {"item_type": "object", "row_detection": "line", "header_rows": 1, "columns": columns}
        else:
            outcomes = [_type_check(quote, field_type, name) for quote in (present_quotes or [""])]
            failed = next((outcome for outcome in outcomes if outcome[0] is False), None)
            type_ok, type_message = failed or outcomes[0]
        checks.append({"key": "type", "ok": type_ok, "message": type_message})

        # A label is trusted without AI at extraction time, so it must
        # reproduce the value in every sample where the field was found.
        working_labels = [
            label.strip() for label in proposal.source_labels
            if field_type != "array" and found_results and all(
                _label_reproduces(label, r["quote"], texts[r["sample"]]) for r in found_results)
        ]
        pattern = proposal.pattern.strip() if proposal.pattern else None
        # Mapping only checks `pattern` on text values (document_tasks._normalize_schema_value).
        pattern_ok = field_type == "text" and bool(present_quotes) and all(
            _pattern_matches(pattern, quote) for quote in present_quotes)
        if proposal.source_labels and field_type != "array":
            checks.append({
                "key": "labels",
                "ok": bool(working_labels),
                "message": ("Label finds this value: " + ", ".join(working_labels)) if working_labels
                else "Suggested labels do not find this value, so they were removed",
            })
        if pattern and field_type == "text":
            checks.append({
                "key": "pattern",
                "ok": pattern_ok,
                "message": "Format rule matches the value" if pattern_ok else "Format rule does not match the value, so it was removed",
            })

        description = proposal.description.strip()
        type_score = {True: 1.0, False: 0.0, None: 0.5}[type_ok]
        helper_score = 1.0 if working_labels else 0.5 if pattern_ok else 0.0
        description_score = 1.0 if len(description) >= 10 else 0.0
        confidence = round(
            WEIGHT_EVIDENCE * evidence_score + WEIGHT_TYPE * type_score
            + WEIGHT_HELPER * helper_score + WEIGHT_DESCRIPTION * description_score, 2)
        if found == 0:
            status = "not_found"
        elif found == sample_count and all(r["match"] == "once" for r in results) and type_ok is not False:
            status = "verified"
        else:
            status = "review"

        validation_rules: dict[str, Any] = {}
        if working_labels:
            validation_rules["source_labels"] = working_labels
        if pattern_ok:
            validation_rules["pattern"] = pattern
        primary = found_results[0] if found_results else results[0]
        field: dict[str, Any] = {
            "name": name,
            "type": field_type,
            "description": description,
            "required": sample_count > 1 and found == sample_count,
            "studio": {
                "label": proposal.label.strip(),
                "confidence": confidence,
                "status": status,
                "presence": {"found": found, "total": sample_count},
                "evidence": primary,
                "samples": results,
                "checks": checks,
            },
        }
        if validation_rules:
            field["validation_rules"] = validation_rules
        if array_config:
            field["array_config"] = array_config
        # Equal values are common and legitimate (subtotal = total without tax,
        # issue date = due date), so keep both fields but ask for a check.
        key = " ".join(primary["quote"].split()) if found and field_type != "array" else ""
        twin = seen_quotes.get(key) if key else None
        if twin is not None:
            _flag_same_value(field, twin["name"])
            _flag_same_value(twin, name)
        fields.append(field)
        used_names.add(name)
        if key and twin is None:
            seen_quotes[key] = field
    return fields, dropped


def _flag_same_value(field: dict[str, Any], other_name: str) -> None:
    studio = field["studio"]
    studio["checks"].append({
        "key": "duplicate",
        "ok": False,
        "message": f"Same value as {other_name}; confirm they are different fields",
    })
    if studio["status"] == "verified":
        studio["status"] = "review"


def summarize(fields: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"verified": 0, "review": 0, "not_found": 0}
    for field in fields:
        counts[field["studio"]["status"]] += 1
    return {"total": len(fields), **counts}


def _session_key(user_id: Any, session_id: str) -> str:
    return f"schema_sample:{user_id}:{session_id}"


def _redis_client() -> Any:
    import redis
    from app.core.config import settings

    # Short timeouts: these calls run inside request handlers.
    return redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=5)


def store_samples(user_id: Any, samples: list[dict[str, str]]) -> Optional[str]:
    """Keep the extracted texts briefly so the user can test the draft schema.

    Only text is kept here (files stay in the browser until the user chooses
    to keep them), for SAMPLE_TTL_SECONDS, under a key scoped to the uploader.
    Returns None when Redis is unavailable.
    """
    session_id = uuid.uuid4().hex
    try:
        client = _redis_client()
        try:
            client.set(_session_key(user_id, session_id),
                       json.dumps({"samples": samples, "created_at": time.time()}),
                       ex=SAMPLE_TTL_SECONDS)
        finally:
            client.close()
    except Exception:  # noqa: BLE001 — testing is optional; suggestion still succeeds
        logger.warning("Could not cache schema sample text for dry run", exc_info=True)
        return None
    return session_id


def load_samples(user_id: Any, session_id: str) -> Optional[list[dict[str, str]]]:
    if not re.fullmatch(r"[0-9a-f]{32}", session_id or ""):
        return None
    client = _redis_client()
    try:
        raw = client.get(_session_key(user_id, session_id))
    finally:
        client.close()
    if not raw:
        return None
    data = json.loads(raw)
    if "samples" in data:
        return data["samples"]
    return [{"text": data.get("text", ""), "filename": data.get("filename", "")}]


def values_match(expected: Any, actual: Any) -> bool:
    """Compare a confirmed value with a newly extracted one.

    Numbers compare numerically (to the cent), text ignores case and spacing,
    tables and objects compare as normalised JSON.
    """
    if expected is None or actual is None:
        return expected is None and actual is None

    def as_number(value: Any) -> Optional[float]:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.replace(",", "").strip())
            except ValueError:
                return None
        return None

    left, right = as_number(expected), as_number(actual)
    if left is not None and right is not None:
        return abs(left - right) < 0.005
    if isinstance(expected, str) and isinstance(actual, str):
        return " ".join(expected.split()).casefold() == " ".join(actual.split()).casefold()
    return json.dumps(expected, sort_keys=True, ensure_ascii=False) == json.dumps(actual, sort_keys=True, ensure_ascii=False)


def compare_with_expected(expected: dict[str, Any], values: dict[str, Any],
                          field_names: Optional[set[str]] = None) -> dict[str, Any]:
    """Score one sample: only fields a person confirmed are counted.

    Confirmed values for fields no longer in the schema (renamed or removed)
    are listed as ``ignored`` instead of being counted as failures.
    """
    current = {name: want for name, want in (expected or {}).items() if field_names is None or name in field_names}
    fields = {name: {"expected": want, "actual": values.get(name), "match": values_match(want, values.get(name))}
              for name, want in current.items()}
    matched = sum(1 for item in fields.values() if item["match"])
    ignored = sorted(set(expected or {}) - set(current))
    return {"checked": len(fields), "matched": matched, "fields": fields, "ignored": ignored}


def dry_run_report(values: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    """Reduce a map_fields report to what the schema designer needs to see."""
    fields: dict[str, Any] = {}
    for name, item in (report.get("fields") or {}).items():
        fields[name] = {
            "value": values.get(name),
            "status": item.get("status"),
            "provider": item.get("provider"),
            "reason": item.get("reason"),
            "quote": item.get("quote"),
        }
    return {
        "status": report.get("status"),
        "engine": report.get("engine"),
        "fields": fields,
        "attempts": report.get("attempts") or [],
        "elapsed_seconds": report.get("elapsed_seconds"),
    }
