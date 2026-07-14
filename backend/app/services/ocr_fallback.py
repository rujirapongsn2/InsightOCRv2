"""Fallback OCR adapter for uploaded local documents.

The provider API accepts a document URL, so local files are uploaded to its
temporary file store first. The returned signed URL is then sent to OCR and
the temporary upload is deleted after processing when possible.
"""
from __future__ import annotations

import os
from typing import Any

import requests


API_BASE_URL = "https://api.mistral.ai/v1"
OCR_MODEL = "mistral-ocr-latest"


def resolve_fallback_api_key(setting: Any = None) -> tuple[str, str]:
    """Return the UI override first, then the backend environment key."""
    ui_key = str(getattr(setting, "ocr_fallback_api_key", None) or "").strip()
    if ui_key:
        return ui_key, "ui"
    env_key = os.getenv("MISTRAL_API_KEY", "").strip()
    if env_key:
        return env_key, "environment"
    return "", "none"


def process_fallback_ocr(
    file_path: str,
    *,
    api_key: str,
    filename: str,
    mime_type: str,
    verify_ssl: bool = True,
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
                timeout=180,
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
            timeout=30,
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
            timeout=300,
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
                    timeout=30,
                    verify=verify_ssl,
                )
            except requests.RequestException:
                pass
