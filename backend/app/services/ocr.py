from __future__ import annotations

import requests
import os
import logging
import time
from urllib.parse import quote, urlsplit, urljoin
from sqlalchemy.orm import Session
from app.models.setting import Setting
from app.core.config import settings
from app.services.tls import get_verify_ssl
from pypdf import PdfReader
from app.services.ocr_result import extract_ocr_text, validate_ocr_result

logger = logging.getLogger(__name__)


_PROCESSING_STATUSES = {"queued", "queueing", "pending", "processing", "running"}
_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled"}


def _result_url(ocr_api_url: str, result_path: str) -> str:
    """Resolve the provider's relative result path against the API origin."""
    endpoint = urlsplit(ocr_api_url)
    if not endpoint.scheme or not endpoint.netloc:
        raise ValueError("OCR endpoint must be an absolute URL")
    resolved = urljoin(f"{endpoint.scheme}://{endpoint.netloc}/", result_path)
    target = urlsplit(resolved)
    if (target.scheme, target.netloc) != (endpoint.scheme, endpoint.netloc) or target.username:
        raise ValueError("OCR result URL must use the configured provider origin")
    return resolved


def _has_ocr_payload(result: object) -> bool:
    return bool(extract_ocr_text(result))


def _wait_for_ocr_result(
    submitted_result: dict,
    *,
    ocr_api_url: str,
    headers: dict[str, str],
    verify_ssl: bool,
    timeout: int | float,
) -> dict:
    """Wait for an asynchronous Softnix OCR job and return its final payload.

    The provider acknowledges uploads immediately and exposes the final result
    at ``get_result``. Returning that acknowledgement as OCR output caused the
    caller to see an empty extraction and unnecessarily advance to fallback.
    """
    status = str(submitted_result.get("status") or "").lower()
    if status in _FAILED_STATUSES:
        raise RuntimeError("Softnix OCR submission failed")
    if status not in _PROCESSING_STATUSES and _has_ocr_payload(submitted_result):
        return submitted_result

    result_path = submitted_result.get("get_result")
    if not result_path and submitted_result.get("job_id"):
        result_path = f"{ocr_api_url.rstrip('/')}/{quote(str(submitted_result['job_id']), safe='')}/result"
    if not isinstance(result_path, str) or not result_path.strip():
        raise ValueError("OCR submit response contains neither readable text nor a result reference")

    result_url = _result_url(ocr_api_url, result_path)
    status_path = submitted_result.get("check_status")
    status_url = _result_url(ocr_api_url, status_path) if isinstance(status_path, str) and status_path else None
    deadline = time.monotonic() + max(0, timeout)
    poll_interval = max(1, settings.OCR_STATUS_POLL_INTERVAL_SECONDS)
    request_timeout = max(1, settings.OCR_STATUS_REQUEST_TIMEOUT_SECONDS)
    job_id = submitted_result.get("job_id")

    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()))
        try:
            response = requests.get(
                status_url or result_url,
                headers=headers,
                verify=verify_ssl,
                timeout=min(request_timeout, remaining),
                allow_redirects=False,
            )
        except (requests.Timeout, requests.ConnectionError):
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
            continue
        if response.status_code in {429, 502, 503, 504}:
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
            continue
        if 300 <= response.status_code < 400:
            raise ValueError("OCR result redirects are not supported")
        if response.status_code == 202:
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
            continue

        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("OCR result response is not a JSON object")

        status = str(result.get("status") or "").lower()
        if status in _FAILED_STATUSES:
            raise RuntimeError(f"Softnix OCR job {job_id or 'unknown'} failed")
        if status in _PROCESSING_STATUSES:
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
            continue
        if status_url:
            if status not in {"completed", "success", "done"}:
                raise ValueError("Softnix OCR returned an unrecognized job status")
            status_url = None
            continue
        if not _has_ocr_payload(result):
            raise ValueError("Softnix OCR completed without readable text")
        return result

    raise TimeoutError(
        f"Softnix OCR job {job_id or 'unknown'} did not complete within {timeout} seconds"
    )

def count_pdf_pages(file_path: str) -> int:
    """
    Count the number of pages in a PDF file.

    Args:
        file_path: Path to the PDF file.

    Returns:
        Number of pages in the PDF.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If file is not a valid PDF.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File '{file_path}' not found.")

    try:
        reader = PdfReader(file_path)
        return len(reader.pages)
    except Exception as e:
        raise ValueError(f"Failed to read PDF: {str(e)}")

def process_ocr(
    file_path: str,
    db: Session | None,
    page_number: int = 1,
    filename: str = None,
    mime_type: str = None,
    timeout: int | float = 180,
    setting_override: Setting | None = None,
) -> dict:
    """
    Process a specific page of a file using the external OCR service.

    Args:
        file_path: Path to the file to process.
        db: Database session to fetch settings.
        page_number: Specific page number to process (default: 1).
        filename: Original filename (used to determine content type if mime_type not provided).
        mime_type: MIME type of the file (overrides filename-based detection).

    Returns:
        A dictionary containing the OCR result for the specified page.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File '{file_path}' not found.")

    # Fetch settings from database
    setting = setting_override if setting_override is not None else db.query(Setting).first()
    if not setting:
        raise ValueError(
            "API Settings not configured. Please configure the following in /settings page:\n"
            "- OCR Endpoint\n"
            "- API Token\n"
            "- OCR Engine (optional)\n"
            "- Model (optional)"
        )

    # Use ocr_endpoint, fallback to legacy api_endpoint if not set
    ocr_api_url = setting.ocr_endpoint or setting.api_endpoint

    if not ocr_api_url or not setting.api_token:
        raise ValueError(
            "OCR Endpoint and API Token are required. Please configure them in /settings page."
        )
    api_key = setting.api_token
    verify_ssl = get_verify_ssl(setting, "OCR provider requests")

    # If 'default', send empty string to let External API use its own default
    ocr_engine = '' if not setting.ocr_engine or setting.ocr_engine == 'default' else setting.ocr_engine
    model = '' if not setting.model or setting.model == 'default' else setting.model

    headers = {
        'accept': 'application/json',
        'Authorization': f'Bearer {api_key}',
    }

    data = {
        'pages': str(page_number),  # Process specific page number
        'prompt': '',
        'ocr_engine': ocr_engine,
        'model': model
    }
    if urlsplit(ocr_api_url).path.rstrip('/').endswith('/v3/ai-process-file'):
        data['disable_structure'] = 'true'

    try:
        # Determine file content type
        # Priority: mime_type > filename > temp file path
        if mime_type:
            content_type = mime_type
        elif filename:
            file_ext = os.path.splitext(filename)[1].lower()
            content_type = 'application/pdf' if file_ext == '.pdf' else f'image/{file_ext[1:]}'
        else:
            # Fallback to checking temp file path (may not have extension)
            file_ext = os.path.splitext(file_path)[1].lower()
            content_type = 'application/pdf' if file_ext == '.pdf' else f'image/{file_ext[1:]}' if file_ext else 'application/octet-stream'

        upload_filename = filename if filename else os.path.basename(file_path)
        logger.info("Submitting OCR request for %s (%s)", upload_filename, content_type)

        with open(file_path, 'rb') as f:
            # Use original filename if available, otherwise use temp file path
            upload_filename = filename if filename else os.path.basename(file_path)

            files = {
                'file': (upload_filename, f, content_type)
            }

            deadline = time.monotonic() + max(0, timeout)
            response = requests.post(
                ocr_api_url,
                headers=headers,
                data=data,
                files=files,
                verify=verify_ssl,
                timeout=max(0.001, timeout),
                allow_redirects=False,
            )
            if 300 <= response.status_code < 400:
                raise ValueError("OCR submit redirects are not supported")
            response.raise_for_status()
            submitted_result = response.json()
            if not isinstance(submitted_result, dict):
                raise ValueError("OCR submit response is not a JSON object")

            result = _wait_for_ocr_result(
                submitted_result,
                ocr_api_url=ocr_api_url,
                headers=headers,
                verify_ssl=verify_ssl,
                timeout=max(0, deadline - time.monotonic()),
            )
            logger.info("OCR request completed for %s (status=%s)", upload_filename, result.get("status"))
            validate_ocr_result(result)
            return result
            
    except TimeoutError as e:
        logger.warning("Softnix OCR did not complete: %s", e)
        raise
    except requests.exceptions.RequestException as e:
        logger.warning("OCR API request failed: %s", e)
        raise
    except Exception as e:
        logger.exception("OCR processing failed: %s", e)
        raise
