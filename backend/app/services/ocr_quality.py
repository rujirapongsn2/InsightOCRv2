"""Judge OCR text quality so poor pages can be re-read by a better OCR.

Layer 0 (free, every Tesseract page): word confidence from Tesseract's TSV
plus the broken-Thai detector decide ``good`` / ``poor`` / ``uncertain``.
Layer 1 (optional): for ``uncertain`` pages only, TypeSafe Jev answers one
Noul question ("is this readable, correctly encoded text?") when configured.

Text is never rewritten here except by ``normalize_thai``, which only fixes
encoding artefacts whose correct form is unambiguous. No model edits text.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

JEV_READABLE_QUESTION = (
    "This is OCR text from one page of a business document (Thai and/or English). "
    "Is it readable text with correctly spelled, correctly encoded words, rather than garbled OCR "
    "(broken Thai characters, random symbols, words split into letters, Latin letters inside Thai words)? "
    "Judge readability only; do not judge the document's content."
)


JEV_MIN_SECONDS = 2.0


def routing_enabled(setting: Any) -> bool:
    """Admin setting when saved, otherwise the environment default."""
    value = getattr(setting, "ocr_quality_routing", None)
    return settings.OCR_QUALITY_ROUTING if value is None else bool(value)


def jev_enabled(setting: Any) -> bool:
    value = getattr(setting, "ocr_quality_jev", None)
    return settings.OCR_QUALITY_JEV if value is None else bool(value)


def tesseract_confidence(words: list[dict[str, Any]]) -> dict[str, Any]:
    """Character-weighted mean confidence and the share of characters in low-confidence words."""
    total = low = 0
    weighted = 0.0
    for word in words:
        conf = word.get("conf")
        text = str(word.get("text") or "")
        if not isinstance(conf, (int, float)) or conf < 0 or not text.strip():
            continue
        size = len(text)
        total += size
        weighted += conf * size
        if conf < settings.OCR_QUALITY_LOW_WORD_CONFIDENCE:
            low += size
    return {
        # Counted like the mean: words with a confidence and visible text.
        "word_count": sum(1 for word in words if isinstance(word.get("conf"), (int, float)) and word["conf"] >= 0
                          and str(word.get("text") or "").strip()),
        "mean_confidence": round(weighted / total, 1) if total else None,
        "low_confidence_share": round(low / total, 3) if total else None,
    }


def assess_tesseract_page(words: list[dict[str, Any]], thai_suspect: bool) -> dict[str, Any]:
    """Layer 0 verdict for one Tesseract page."""
    stats = {**tesseract_confidence(words), **low_confidence_lines(words)}
    mean = stats["mean_confidence"]
    if thai_suspect:
        verdict, reason = "poor", "thai_font_mapping"
    elif mean is None or stats["word_count"] < settings.OCR_QUALITY_MIN_WORDS:
        # Too little text to judge (blank page, a page number): leave it alone.
        verdict, reason = "good", "too_few_words"
    elif mean < settings.OCR_QUALITY_POOR_CONFIDENCE:
        verdict, reason = "poor", "low_confidence"
    elif stats["low_confidence_lines"] >= settings.OCR_QUALITY_MAX_LOW_LINES:
        verdict, reason = "poor", "low_confidence_lines"
    elif mean >= settings.OCR_QUALITY_GOOD_CONFIDENCE:
        verdict, reason = "good", "confident"
    else:
        verdict, reason = "uncertain", "borderline_confidence"
    return {**stats, "verdict": verdict, "reason": reason}


def jev_readable(text: str, setting: Any, timeout: float) -> Optional[dict[str, Any]]:
    """Layer 1: Jev Noul on an uncertain page. ``None`` when Jev is off or not configured."""
    from app.services.typesafe import resolve_typesafe_config, typesafe_is_configured, typesafe_noul

    if not jev_enabled(setting) or not typesafe_is_configured(setting):
        return None
    if timeout < JEV_MIN_SECONDS:
        return {"error": "no_time_left"}  # the document's time budget is spent; do not overrun it
    try:
        result = typesafe_noul(resolve_typesafe_config(setting),
                               {"input": text[:settings.OCR_QUALITY_JEV_MAX_CHARS]},
                               question=JEV_READABLE_QUESTION, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — a failed check keeps the page as it is
        logger.warning("Jev readability check failed: %s", type(exc).__name__)
        return {"error": type(exc).__name__}
    noul = result.get("noul")
    if not isinstance(noul, (int, float)):
        return {"error": "no_answer"}
    return {"noul": round(float(noul), 3), "threshold": settings.OCR_QUALITY_JEV_THRESHOLD,
            "readable": float(noul) >= settings.OCR_QUALITY_JEV_THRESHOLD, "model": result.get("model")}


# Thai combining marks (above/below vowels, tone marks) never follow whitespace in
# correctly encoded text; broken font maps emit "บร ิษัท", "ข ้อมูล".
_DETACHED_MARK = re.compile(r"(?<=[ก-๏])[ \t]+(?=[ัิ-ฺ็-๎])")
# NIKHAHIT + SARA AA is the decomposed spelling of SARA AM ("จํากัด" → "จำกัด").
_DECOMPOSED_SARA_AM = re.compile(r"ํา")


def normalize_thai(text: str) -> tuple[str, int]:
    """Fix Thai encoding artefacts with exactly one correct form; returns (text, changes).

    Deliberately does not guess tone marks that broken fonts replace with Latin
    letters ("เพิMม"): the right mark depends on the font, and a wrong guess
    changes the word. Those pages go to OCR instead (TEXT_LAYER_THAI_REPAIR).
    """
    if not text or not settings.THAI_TEXT_NORMALIZE:
        return text, 0
    text, detached = _DETACHED_MARK.subn("", text)
    text, sara_am = _DECOMPOSED_SARA_AM.subn("ำ", text)
    return text, detached + sara_am


# ---------------------------------------------------------------------------
# Line-level page check and field-level checks
# ---------------------------------------------------------------------------

def low_confidence_lines(words: list[dict[str, Any]]) -> dict[str, Any]:
    """Lines containing a very uncertain word, or with a low mean.

    Errors cluster in a few places, so a high page mean can hide them: a Thai
    scan read as "6นร1๐ทา66" still averaged 89.7. Counting bad lines catches that.
    """
    lines: dict[Any, list[dict[str, Any]]] = {}
    for word in words:
        conf = word.get("conf")
        if isinstance(conf, (int, float)) and conf >= 0 and str(word.get("text") or "").strip():
            lines.setdefault(word.get("line", round(float(word.get("y") or 0))), []).append(word)
    low = 0
    for line_words in lines.values():
        weights = [len(str(word["text"])) for word in line_words]
        mean = sum(word["conf"] * weight for word, weight in zip(line_words, weights)) / sum(weights)
        if mean < settings.OCR_QUALITY_LOW_WORD_CONFIDENCE or min(word["conf"] for word in line_words) < settings.OCR_QUALITY_VERY_LOW_WORD_CONFIDENCE:
            low += 1
    return {"line_count": len(lines), "low_confidence_lines": low}


def _search_form(text: str) -> str:
    """One spelling for matching: SARA AM decomposed, as OCR words often keep it ("จํากัด")."""
    return text.replace("\u0E33", "\u0E4D\u0E32").casefold()


def _compact(text: str) -> str:
    return _search_form(re.sub(r"\s+", "", text))


def value_search_texts(value: Any) -> list[str]:
    """Ways a mapped value may be printed (mirrors the frontend's evidence search)."""
    if value is None or isinstance(value, (bool, dict, list)):
        return []
    raw = str(value).strip()
    texts = [raw] if raw else []
    number: Optional[float] = None
    if isinstance(value, (int, float)):
        number = float(value)
    if number is not None:
        texts += [f"{number:,.2f}", f"{number:,.0f}" if number == int(number) else f"{number:,}", f"{number:.2f}"]
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if iso:
        year, month, day = iso.groups()
        for y in (year, str(int(year) + 543)):
            texts += [f"{day}/{month}/{y}", f"{int(day)}/{int(month)}/{y}"]
    return [text for index, text in enumerate(texts) if len(_compact(text)) >= 2 and text not in texts[:index]]


def value_word_confidence(value: Any, pages: Any) -> Optional[dict[str, Any]]:
    """Lowest OCR confidence among the words the value was read from.

    Uses the best-read occurrence when the value appears more than once. ``None``
    when the value is not found in OCR words (text-layer pages have none).
    """
    texts = [_compact(text) for text in value_search_texts(value)]
    best: Optional[dict[str, Any]] = None
    for page in pages if isinstance(pages, list) else []:
        words = [word for word in (page.get("words") or []) if isinstance(word, dict)] if isinstance(page, dict) else []
        if not words:
            continue
        joined, owner = "", []
        for index, word in enumerate(words):
            for char in _search_form(str(word.get("text") or "")):
                if not char.isspace():
                    joined += char
                    owner.append(index)
        for needle in texts:
            start = joined.find(needle)
            while start >= 0:
                span = words[owner[start]:owner[start + len(needle) - 1] + 1]
                confs = [word["conf"] for word in span if isinstance(word.get("conf"), (int, float)) and word["conf"] >= 0]
                if confs and (best is None or min(confs) > best["min_confidence"]):
                    best = {"min_confidence": round(min(confs), 1), "page": page.get("page_number"),
                            "words": [word.get("text") for word in span][:12]}
                start = joined.find(needle, start + 1)
    return best


_THAI_ID_HINTS = re.compile(r"tax|citizen|national|id_?card|ผู้เสียภาษี|ประจำตัว|บัตรประชาชน", re.IGNORECASE)


def thai_id_checksum_ok(value: str) -> bool:
    digits = [int(char) for char in value]
    return (11 - sum(digit * (13 - index) for index, digit in enumerate(digits[:12])) % 11) % 10 == digits[12]


def review_uncertain_values(values: dict[str, Any], report: dict[str, Any], pages: Any,
                            fields: list[dict[str, Any]]) -> None:
    """Send values to review when OCR was unsure of their characters or a Thai ID fails its checksum.

    These catch misreads that look normal ("8" read as "3") and so pass every
    type and format check downstream. Values are never changed.
    """
    evidence = report.setdefault("fields", {})
    flagged: list[str] = []
    for field in fields:
        name = field.get("name")
        value = values.get(name) if name else None
        if value is None or isinstance(value, (bool, dict, list)):
            continue
        hint = f"{name} {field.get('description') or ''}"
        digits = re.sub(r"[\s-]", "", str(value))
        if re.fullmatch(r"\d{13}", digits) and _THAI_ID_HINTS.search(hint) and not thai_id_checksum_ok(digits):
            evidence.setdefault(name, {}).update(status="needs_review", check="thai_id_checksum",
                        reason="This 13-digit ID fails the Thai ID checksum; a digit was probably misread")
            flagged.append(name)
            continue
        confidence = value_word_confidence(value, pages)
        if confidence is None:
            continue
        item = evidence.setdefault(name, {})
        item["ocr_confidence"] = confidence
        if confidence["min_confidence"] < settings.OCR_FIELD_MIN_CONFIDENCE:
            item.update(status="needs_review", check="ocr_confidence",
                        reason=f"OCR was unsure of part of this value (confidence {confidence['min_confidence']}); check it against the page")
            flagged.append(name)
    if flagged:
        review = list(report.get("review_fields") or [])
        report["review_fields"] = review + [name for name in flagged if name not in review]


def auto_review_blockers(document: Any) -> list[str]:
    """Why a document must wait for a person instead of being auto-confirmed.

    Auto-confirm is for documents the pipeline is sure about; fields it flagged
    for review, missing required fields or poor OCR pages need human eyes.
    """
    metadata = document.extraction_metadata if isinstance(getattr(document, "extraction_metadata", None), dict) else {}
    mapping = metadata.get("mapping") if isinstance(metadata.get("mapping"), dict) else {}
    reasons: list[str] = []
    if mapping.get("review_fields"):
        reasons.append("fields need review: " + ", ".join(map(str, mapping["review_fields"])))
    if mapping.get("unresolved_fields"):
        reasons.append("fields not found: " + ", ".join(map(str, mapping["unresolved_fields"])))
    if metadata.get("ocr_low_quality_pages"):
        reasons.append("low-quality OCR on page(s) " + ", ".join(map(str, metadata["ocr_low_quality_pages"])))
    return reasons
