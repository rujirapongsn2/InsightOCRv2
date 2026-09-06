"""Canonical readable text from Softnix v3 and normalized fallback results."""
from typing import Any


def validate_ocr_result(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("OCR result is not a JSON object")
    if str(payload.get("status", "")).lower() in {"failed", "error", "cancelled", "canceled"}:
        raise ValueError("OCR provider reported a failed result")
    results = payload.get("results")
    results = results if isinstance(results, dict) else payload
    if results.get("failed_pages"):
        raise ValueError("OCR provider reported failed pages; the document is incomplete")
    processed = results.get("processed_pages")
    successful = results.get("successful_pages")
    if isinstance(processed, int) and isinstance(successful, int) and successful < processed:
        raise ValueError("OCR provider did not successfully process every requested page")
    if not extract_ocr_text(payload):
        raise ValueError("OCR provider returned no readable text")


def extract_ocr_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    if str(payload.get("status", "")).lower() in {"failed", "error", "cancelled", "canceled"}:
        return ""

    def page_text(page: dict) -> str:
        ai = page.get("ai_processing")
        if isinstance(ai, str) and ai.strip():
            return ai.strip()
        if isinstance(ai, dict) and ai.get("success") is not False:
            for key in ("content", "text", "output", "result"):
                value = ai.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        value = page.get("ocr_text")
        return value.strip() if isinstance(value, str) else ""

    results = payload.get("results")
    results = results if isinstance(results, dict) else payload
    pages = results.get("pages")
    if isinstance(pages, list):
        # Preserve repeated text on distinct pages; never append raw and AI text twice.
        texts = [page_text(page) for page in pages if isinstance(page, dict)]
        if any(texts):
            return "\n\n".join(text for text in texts if text)
    combined = results.get("combined_markdown")
    if isinstance(combined, str) and combined.strip():
        return combined.strip()
    return page_text(payload)
