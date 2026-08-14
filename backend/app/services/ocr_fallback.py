"""Fallback OCR adapter for uploaded local documents.

The provider API accepts a document URL, so local files are uploaded to its
temporary file store first. The returned signed URL is then sent to OCR and
the temporary upload is deleted after processing when possible.
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests


API_BASE_URL = "https://api.mistral.ai/v1"
OCR_MODEL = "mistral-ocr-latest"


def _request_timeout(
    default_timeout: int | float,
    deadline_monotonic: float | None,
) -> int | float:
    if deadline_monotonic is None:
        return default_timeout
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("OCR fallback exceeded the document processing budget")
    return max(1, min(default_timeout, int(remaining)))


def resolve_fallback_api_key(setting: Any = None) -> tuple[str, str]:
    """Return the UI override first, then the backend environment key."""
    ui_key = str(getattr(setting, "ocr_fallback_api_key", None) or "").strip()
    if ui_key:
        return ui_key, "ui"
    env_key = os.getenv("MISTRAL_API_KEY", "").strip()
    if env_key:
        return env_key, "environment"
    return "", "none"


def fallback_configuration_error(setting: Any = None, enabled: bool = False) -> str | None:
    """Explain why the fallback cannot be used, without exposing credentials."""
    if not enabled:
        return "OCR fallback is disabled"
    key, _source = resolve_fallback_api_key(setting)
    if not key:
        return "OCR fallback is enabled but no API key is configured"
    return None


def process_fallback_ocr(
    file_path: str,
    *,
    api_key: str,
    filename: str,
    mime_type: str,
    verify_ssl: bool = True,
    request_timeout: int | float = 180,
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """OCR a local document and normalize the response for InsightDOC."""
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    uploaded_file_id: str | None = None

    try:
        with open(file_path, "rb") as file_stream:
            upload_response = requests.post(
                f"{API_BASE_URL}/files",
                headers=headers,
                data={"purpose": "ocr"},
                files={"file": (filename or os.path.basename(file_path), file_stream, mime_type)},
                timeout=_request_timeout(request_timeout, deadline_monotonic),
                verify=verify_ssl,
            )
        upload_response.raise_for_status()
        upload_payload = upload_response.json()
        uploaded_file_id = upload_payload.get("id")
        if not uploaded_file_id:
            raise ValueError("Fallback OCR upload did not return a file id")

        signed_url_response = requests.get(
            f"{API_BASE_URL}/files/{uploaded_file_id}/url",
            headers=headers,
            params={"expiry": 1},
            timeout=_request_timeout(min(30, request_timeout), deadline_monotonic),
            verify=verify_ssl,
        )
        signed_url_response.raise_for_status()
        signed_url = signed_url_response.json().get("url")
        if not signed_url:
            raise ValueError("Fallback OCR upload did not return a signed URL")

        ocr_response = requests.post(
            f"{API_BASE_URL}/ocr",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "model": OCR_MODEL,
                "document": {"type": "document_url", "document_url": signed_url},
                "table_format": "html",
            },
            timeout=_request_timeout(request_timeout, deadline_monotonic),
            verify=verify_ssl,
        )
        ocr_response.raise_for_status()
        payload = ocr_response.json()
        pages = payload.get("pages")
        if not isinstance(pages, list) or not pages:
            raise ValueError("Fallback OCR returned no pages")

        normalized_pages = []
        for index, page in enumerate(pages, start=1):
            if not isinstance(page, dict):
                continue
            markdown = page.get("markdown") or ""
            page_index = page.get("index")
            page_number = page_index + 1 if isinstance(page_index, int) else index
            normalized_pages.append({
                "page_number": page_number,
                "ocr_text": markdown,
                "ai_processing": {"success": True, "content": markdown},
                "fallback_provider": "document_ocr",
            })

        if not normalized_pages:
            raise ValueError("Fallback OCR returned no readable pages")

        return {
            "results": {"pages": normalized_pages},
            "model": payload.get("model", OCR_MODEL),
            "fallback_provider": "document_ocr",
            "usage_info": payload.get("usage_info"),
        }
    finally:
        if uploaded_file_id:
            try:
                requests.delete(
                    f"{API_BASE_URL}/files/{uploaded_file_id}",
                    headers=headers,
                    timeout=_request_timeout(min(30, request_timeout), deadline_monotonic),
                    verify=verify_ssl,
                )
            except (requests.RequestException, TimeoutError):
                pass
