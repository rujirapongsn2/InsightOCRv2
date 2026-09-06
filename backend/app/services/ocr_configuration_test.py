from __future__ import annotations

import re
import tempfile
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
import requests

from app.services.ocr import process_ocr
from app.services.ocr_fallback import (
    fallback_configuration_error,
    process_fallback_ocr,
    resolve_fallback_api_key,
)
from app.services.tls import get_verify_ssl


OCR_TEST_MARKER = "INSIGHTDOC OCR TEST 4827"


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def create_ocr_test_image(directory: str) -> str:
    """Create a deterministic document without retaining customer data."""
    image = Image.new("RGB", (1400, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 70), OCR_TEST_MARKER, fill="black", font=_font(72))
    draw.text((70, 210), "Configuration verification document", fill="black", font=_font(42))
    path = Path(directory) / "insightdoc-ocr-test.png"
    image.save(path, format="PNG")
    return str(path)


def extract_ocr_text(payload: Any) -> str:
    from app.services.ocr_result import extract_ocr_text as canonical_text
    return canonical_text(payload)




def _contains_marker(text: str) -> bool:
    normalized = re.sub(r"[^A-Z0-9]", "", text.upper())
    return "INSIGHTDOCOCRTEST4827" in normalized


def _failure_message(provider: str, error: Exception) -> str:
    if isinstance(error, (TimeoutError, requests.Timeout)):
        return f"{provider} timed out before returning OCR output"
    if isinstance(error, requests.HTTPError) and error.response is not None:
        code = error.response.status_code
        return f"{provider} returned HTTP {code}; check API permissions, configuration, and provider availability"
    return f"{provider} could not read the verification document ({type(error).__name__})"


def _run_check(check_id: str, label: str, operation: Any) -> dict[str, Any]:
    started = time.monotonic()
    try:
        payload = operation()
        text = extract_ocr_text(payload)
        latency_ms = round((time.monotonic() - started) * 1000)
        if not text.strip():
            return {
                "id": check_id,
                "label": label,
                "status": "failed",
                "latency_ms": latency_ms,
                "message": f"{label} returned no readable text",
                "text_length": 0,
            }
        if not _contains_marker(text):
            return {
                "id": check_id,
                "label": label,
                "status": "failed",
                "latency_ms": latency_ms,
                "message": f"{label} returned text but did not preserve the verification marker",
                "text_length": len(text),
            }
        return {
            "id": check_id,
            "label": label,
            "status": "passed",
            "latency_ms": latency_ms,
            "message": "Read and verified the test document successfully",
            "text_length": len(text),
        }
    except Exception as error:
        return {
            "id": check_id,
            "label": label,
            "status": "failed",
            "latency_ms": round((time.monotonic() - started) * 1000),
            "message": _failure_message(label, error),
            "text_length": 0,
        }


def run_ocr_configuration_test(setting: Any) -> dict[str, Any]:
    """Exercise the real primary and fallback OCR file-processing paths."""
    with tempfile.TemporaryDirectory(prefix="insightdoc-ocr-test-") as directory:
        image_path = create_ocr_test_image(directory)
        checks = [
            _run_check(
                "softnix_ai_process_file",
                "Softnix OCR /v3/ai-process-file",
                lambda: process_ocr(
                    image_path,
                    None,
                    setting_override=setting,
                    filename="insightdoc-ocr-test.png",
                    mime_type="image/png",
                    timeout=60,
                ),
            )
        ]

        fallback_error = fallback_configuration_error(
            setting,
            bool(getattr(setting, "ocr_fallback_enabled", False)),
        )
        if fallback_error:
            checks.append({
                "id": "ocr_fallback",
                "label": "OCR fallback",
                "status": "skipped",
                "latency_ms": 0,
                "message": fallback_error,
                "text_length": 0,
            })
        else:
            fallback_key, fallback_source = resolve_fallback_api_key(setting)
            fallback_check = _run_check(
                "ocr_fallback",
                "OCR fallback",
                lambda: process_fallback_ocr(
                    image_path,
                    api_key=fallback_key,
                    filename="insightdoc-ocr-test.png",
                    mime_type="image/png",
                    verify_ssl=get_verify_ssl(setting, "OCR fallback test requests"),
                    request_timeout=90,
                    deadline_monotonic=time.monotonic() + 90,
                ),
            )
            fallback_check["key_source"] = fallback_source
            checks.append(fallback_check)

    statuses = {check["status"] for check in checks}
    overall_status = "failed" if "failed" in statuses else "partial" if "skipped" in statuses else "passed"
    return {
        "overall_status": overall_status,
        "marker": OCR_TEST_MARKER,
        "checks": checks,
    }
