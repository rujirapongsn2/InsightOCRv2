"""AnyDoc-backed document normalization and OCR routing.

Task orchestration applies Schema mapping after this module returns canonical,
reviewable Markdown text.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import DocumentSchema, Setting
from app.services.ocr import process_ocr
from app.services.ocr_fallback import (
    fallback_configuration_error,
    process_fallback_ocr,
    resolve_fallback_api_key,
)
from app.services.tesseract_ocr import TesseractOcrError, process_tesseract_ocr
from app.services.tls import get_verify_ssl

logger = logging.getLogger(__name__)

ANYDOC_REF = "82e23481480d5b54a4f4e0b3d99950f09108685c"

_IMAGE_MIME_TYPES = {
    "BMP": "image/bmp",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "TIFF": "image/tiff",
    "WEBP": "image/webp",
}


class AnydocFallbackToLegacy(Exception):
    """The document cannot enter the pilot and should use the legacy flow."""


class AnydocTerminalError(Exception):
    """The pilot completed its attempts but no trustworthy extraction exists."""


@dataclass
class AnydocExtractionResult:
    markdown: str
    pages: list[dict[str, Any]]
    extracted_data: Any
    metadata: dict[str, Any]


def _load_anydoc() -> Any:
    try:
        import anydoc  # type: ignore[import-not-found]
    except ImportError as exc:
        raise AnydocFallbackToLegacy("AnyDoc parser is not installed") from exc
    return anydoc


def _detect_pdf_format(anydoc: Any, file_bytes: bytes) -> str:
    """Detect the input format without letting parser errors bypass fallback."""
    try:
        detected_format = anydoc.format_from_bytes(file_bytes)
    except Exception as exc:
        raise AnydocFallbackToLegacy(
            f"AnyDoc could not detect the document format: {exc}"
        ) from exc

    if detected_format != "pdf":
        raise AnydocFallbackToLegacy(
            f"AnyDoc detected unsupported pilot format: {detected_format or 'unknown'}"
        )
    return detected_format


def extract_anydoc_markdown(file_bytes: bytes) -> str:
    """Return text-layer Markdown for schema suggestions without invoking OCR.

    The wizard has no selected schema yet, so OCR routing is intentionally left
    to its established provider fallback when this lightweight pass is empty.
    """
    anydoc = _load_anydoc()
    encrypted_error = getattr(anydoc, "EncryptedError", None)
    detected_format = _detect_pdf_format(anydoc, file_bytes)
    try:
        markdown = anydoc.to_markdown_bytes(file_bytes, detected_format).strip()
    except Exception as exc:
        if encrypted_error and isinstance(exc, encrypted_error):
            raise AnydocFallbackToLegacy("PDF is encrypted") from exc
        raise AnydocFallbackToLegacy(f"AnyDoc could not parse the PDF: {exc}") from exc
    if not markdown:
        raise AnydocFallbackToLegacy("AnyDoc returned no text-layer Markdown")
    return markdown


def _pdf_text_pages(file_path: str) -> list[dict[str, Any]]:
    try:
        reader = PdfReader(file_path)
        if reader.is_encrypted:
            raise AnydocTerminalError("PDF is encrypted and cannot be extracted")
        if len(reader.pages) > settings.ANYDOC_MAX_PAGES:
            raise AnydocTerminalError(
                f"PDF has more than {settings.ANYDOC_MAX_PAGES} pages"
            )
        return [
            {"page_number": index, "ocr_text": (page.extract_text() or "").strip()}
            for index, page in enumerate(reader.pages, start=1)
        ]
    except AnydocTerminalError:
        raise
    except Exception as exc:
        raise AnydocFallbackToLegacy(f"Unable to inspect PDF pages: {exc}") from exc


def _extract_text(result: dict[str, Any]) -> str:
    parts: list[str] = []

    def append(value: Any) -> None:
        if isinstance(value, str) and value.strip() and value.strip() not in parts:
            parts.append(value.strip())

    append(result.get("ocr_text"))
    ai_processing = result.get("ai_processing")
    if isinstance(ai_processing, dict):
        for key in ("content", "text", "output", "result"):
            append(ai_processing.get(key))
    elif isinstance(ai_processing, str):
        append(ai_processing)

    pages = result.get("results", {}).get("pages") if isinstance(result.get("results"), dict) else None
    if not isinstance(pages, list):
        pages = result.get("pages")
    if isinstance(pages, list):
        for page in pages:
            if not isinstance(page, dict):
                continue
            append(page.get("ocr_text"))
            page_ai = page.get("ai_processing")
            if isinstance(page_ai, dict):
                for key in ("content", "text", "output", "result"):
                    append(page_ai.get(key))
            elif isinstance(page_ai, str):
                append(page_ai)
    return "\n\n".join(parts).strip()


def _merge_page_texts(
    text_pages: list[dict[str, Any]], ocr_pages: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for page in text_pages:
        page_number = int(page["page_number"])
        ocr_page = ocr_pages.get(page_number)
        if ocr_page:
            pages.append(ocr_page)
        else:
            pages.append({
                "page_number": page_number,
                "ocr_text": page.get("ocr_text", ""),
                "provider": "text_layer",
            })
    return pages


def _remaining_timeout(deadline_monotonic: float, maximum: int | float) -> int:
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise AnydocTerminalError("AnyDoc processing exceeded the document time budget")
    return max(1, min(int(maximum), int(remaining)))


def _ocr_page_with_providers(
    image_path: str,
    page_number: int,
    db: Session,
    setting: Setting,
    deadline_monotonic: float,
    *,
    allow_softnix_ocr: bool = True,
) -> dict[str, Any]:
    """Run the configured OCR chain for one rendered PDF page or image.

    TesseractOCR is deliberately first because it stays inside the deployment.
    Softnix OCR and the configured cloud fallback are used only when it cannot
    return text for the page. Schema samples deliberately skip Softnix OCR so
    schema design remains independent from the legacy external OCR endpoint.
    """
    try:
        text = process_tesseract_ocr(
            image_path,
            language=settings.TESSERACT_OCR_LANGUAGE,
            timeout=_remaining_timeout(
                deadline_monotonic,
                settings.TESSERACT_OCR_TIMEOUT_SECONDS,
            ),
        )
        if text:
            return {
                "page_number": page_number,
                "ocr_text": text,
                "provider": "tesseract_ocr",
            }
    except TesseractOcrError as error:
        logger.info("TesseractOCR did not produce text for page %s: %s", page_number, error)
    except Exception as error:
        # A local runtime fault must not prevent the remaining OCR providers
        # from attempting this page.
        logger.warning("TesseractOCR failed for page %s: %s", page_number, error)

    if allow_softnix_ocr:
        try:
            softnix_result = process_ocr(
                image_path,
                db,
                page_number=1,
                filename=f"page-{page_number}.png",
                mime_type="image/png",
                timeout=_remaining_timeout(
                    deadline_monotonic,
                    settings.ANYDOC_PRIMARY_OCR_TIMEOUT_SECONDS,
                ),
            )
            text = _extract_text(softnix_result)
            if text:
                return {
                    "page_number": page_number,
                    "ocr_text": text,
                    "provider": "softnix_ocr",
                }
        except Exception as error:
            logger.warning("Softnix OCR failed for page %s: %s", page_number, error)

    fallback_key, fallback_source = resolve_fallback_api_key(setting)
    fallback_failure: str | None = fallback_configuration_error(
        setting,
        bool(setting.ocr_fallback_enabled),
    )
    if fallback_failure is None:
        try:
            fallback_result = process_fallback_ocr(
                image_path,
                api_key=fallback_key,
                filename=f"page-{page_number}.png",
                mime_type="image/png",
                verify_ssl=get_verify_ssl(setting, "OCR fallback requests"),
                request_timeout=settings.ANYDOC_FALLBACK_REQUEST_TIMEOUT_SECONDS,
                deadline_monotonic=deadline_monotonic,
            )
            text = _extract_text(fallback_result)
            if text:
                return {
                    "page_number": page_number,
                    "ocr_text": text,
                    "provider": "ocr_fallback",
                    "key_source": fallback_source,
                }
            fallback_failure = "OCR fallback returned no readable text"
        except Exception as error:
            fallback_failure = "OCR fallback request failed"
            logger.warning("OCR fallback failed for page %s: %s", page_number, error)

    attempted_providers = "TesseractOCR, Softnix OCR, and OCR fallback" if allow_softnix_ocr else "TesseractOCR and OCR fallback"
    raise AnydocTerminalError(
        f"{attempted_providers} returned no text for page {page_number}; {fallback_failure}"
    )


def _provider_pages(pages: list[dict[str, Any]], provider: str) -> list[int]:
    return [
        page["page_number"]
        for page in pages
        if page.get("provider") == provider and isinstance(page.get("page_number"), int)
    ]


def _provider_counts(pages: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "tesseract_ocr": len(_provider_pages(pages, "tesseract_ocr")),
        "softnix_ocr": len(_provider_pages(pages, "softnix_ocr")),
        "ocr_fallback": len(_provider_pages(pages, "ocr_fallback")),
    }


def _extract_anydoc_pdf_document(
    file_path: str,
    db: Session,
    schema: DocumentSchema | None,
    *,
    allow_softnix_ocr: bool = True,
    pipeline_name: str = "anydoc_hybrid",
) -> AnydocExtractionResult:
    """Normalize a PDF and retain an optional Schema as extraction context."""
    anydoc = _load_anydoc()
    encrypted_error = getattr(anydoc, "EncryptedError", None)
    try:
        with open(file_path, "rb") as source:
            file_bytes = source.read()
    except OSError as exc:
        raise AnydocFallbackToLegacy(
            f"AnyDoc could not read the document: {exc}"
        ) from exc

    text_pages = _pdf_text_pages(file_path)
    # Let pypdf classify encrypted PDFs as terminal failures before AnyDoc's
    # format detector runs. Parser format errors remain safe legacy fallbacks.
    detected_format = _detect_pdf_format(anydoc, file_bytes)
    setting = db.query(Setting).first()
    if not setting:
        raise AnydocTerminalError("OCR settings are not configured")

    ocr_pages: dict[int, dict[str, Any]] = {}
    deadline_monotonic = time.monotonic() + max(60, settings.ANYDOC_DOCUMENT_TIMEOUT_SECONDS)

    def recognize(image: bytes, page_number: int) -> str:
        _remaining_timeout(deadline_monotonic, settings.ANYDOC_PRIMARY_OCR_TIMEOUT_SECONDS)
        if len(ocr_pages) >= settings.ANYDOC_MAX_OCR_PAGES:
            raise AnydocTerminalError(
                f"PDF requires more than {settings.ANYDOC_MAX_OCR_PAGES} OCR pages"
            )
        image_path = ""
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
                image_file.write(image)
                image_path = image_file.name
            page = _ocr_page_with_providers(
                image_path,
                page_number,
                db,
                setting,
                deadline_monotonic,
                allow_softnix_ocr=allow_softnix_ocr,
            )
            ocr_pages[page_number] = page
            return page["ocr_text"]
        finally:
            if image_path:
                try:
                    os.unlink(image_path)
                except OSError:
                    logger.warning("Unable to remove temporary AnyDoc page image")

    try:
        markdown = anydoc.to_markdown_with_ocr(file_bytes, "pdf", recognize).strip()
    except AnydocTerminalError:
        raise
    except Exception as exc:
        if encrypted_error and isinstance(exc, encrypted_error):
            raise AnydocTerminalError("PDF is encrypted and cannot be extracted") from exc
        raise AnydocFallbackToLegacy(f"AnyDoc could not parse the PDF: {exc}") from exc

    if not markdown:
        raise AnydocTerminalError("AnyDoc and OCR providers returned no text")

    pages = _merge_page_texts(text_pages, ocr_pages)
    metadata = {
        "pipeline": pipeline_name,
        "parser": "anydoc",
        "parser_ref": ANYDOC_REF,
        "format": detected_format,
        "page_count": len(pages),
        "text_layer_pages": [
            page["page_number"] for page in pages if page.get("provider") == "text_layer"
        ],
        "ocr_pages": sorted(ocr_pages),
        "tesseract_pages": _provider_pages(pages, "tesseract_ocr"),
        "softnix_ocr_pages": _provider_pages(pages, "softnix_ocr"),
        "fallback_pages": _provider_pages(pages, "ocr_fallback"),
        "page_sources": [
            {"page": page["page_number"], "provider": page.get("provider", "unknown")}
            for page in pages
        ],
        "provider_counts": _provider_counts(pages),
        # Mapping is applied by the task only after canonical Markdown has been
        # produced, so all OCR routes share one Schema validation path.
        "mapping": "pending" if schema else "not_requested",
        "schema_context": schema.name if schema else None,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    return AnydocExtractionResult(markdown, pages, None, metadata)


def _prepare_image_for_ocr(file_path: str) -> tuple[str, str, dict[str, Any]]:
    """Validate and normalize a supported image before it reaches an OCR provider."""
    normalized_path = ""
    try:
        with Image.open(file_path) as source:
            image_format = str(source.format or "").upper()
            mime_type = _IMAGE_MIME_TYPES.get(image_format)
            if not mime_type:
                raise AnydocFallbackToLegacy(
                    f"Unsupported image format for AnyDoc pipeline: {image_format or 'unknown'}"
                )
            width, height = source.size
            if width <= 0 or height <= 0:
                raise AnydocTerminalError("Image has invalid dimensions")
            if width > settings.ANYDOC_MAX_IMAGE_DIMENSION or height > settings.ANYDOC_MAX_IMAGE_DIMENSION:
                raise AnydocTerminalError(
                    f"Image dimensions exceed {settings.ANYDOC_MAX_IMAGE_DIMENSION}px"
                )
            if width * height > settings.ANYDOC_MAX_IMAGE_PIXELS:
                raise AnydocTerminalError(
                    f"Image exceeds {settings.ANYDOC_MAX_IMAGE_PIXELS} pixels"
                )

            # Check integrity only after the header-level dimension guard. This
            # prevents a highly compressed image from being fully decoded before
            # its pixel count is rejected.
            source.verify()

        with Image.open(file_path) as source:
            image = ImageOps.exif_transpose(source)
            image.load()

            # OCR providers receive a normalized PNG, avoiding EXIF orientation
            # and palette/transparency inconsistencies across uploaded images.
            if image.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", image.size, "white")
                alpha = image.getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as target:
                normalized_path = target.name
            image.save(normalized_path, format="PNG", optimize=True)
            return normalized_path, "image/png", {
                "format": image_format.lower(),
                "width": width,
                "height": height,
            }
    except (UnidentifiedImageError, OSError) as exc:
        raise AnydocFallbackToLegacy(f"Unable to read image for AnyDoc OCR: {exc}") from exc
    except Image.DecompressionBombError as exc:
        raise AnydocTerminalError("Image is too large to process safely") from exc
    except Exception:
        if normalized_path:
            try:
                os.unlink(normalized_path)
            except OSError:
                logger.warning("Unable to remove temporary normalized image")
        raise


def _extract_anydoc_image_document(
    file_path: str,
    db: Session,
    schema: DocumentSchema | None,
    *,
    allow_softnix_ocr: bool = True,
    pipeline_name: str = "anydoc_hybrid",
) -> AnydocExtractionResult:
    """Run the AnyDoc hybrid policy for an image through configured OCR providers."""
    setting = db.query(Setting).first()
    if not setting:
        raise AnydocTerminalError("OCR settings are not configured")

    normalized_path = ""
    deadline_monotonic = time.monotonic() + max(60, settings.ANYDOC_DOCUMENT_TIMEOUT_SECONDS)
    try:
        normalized_path, normalized_mime_type, image_metadata = _prepare_image_for_ocr(file_path)
        page = _ocr_page_with_providers(
            normalized_path,
            1,
            db,
            setting,
            deadline_monotonic,
            allow_softnix_ocr=allow_softnix_ocr,
        )
        text = page["ocr_text"]

        markdown = text.strip()
        pages = [page]
        metadata = {
            "pipeline": pipeline_name,
            "parser": "image_ocr",
            "parser_ref": ANYDOC_REF,
            "source": "image",
            "format": image_metadata["format"],
            "image": image_metadata,
            "page_count": 1,
            "text_layer_pages": [],
            "ocr_pages": [1],
            "tesseract_pages": _provider_pages(pages, "tesseract_ocr"),
            "softnix_ocr_pages": _provider_pages(pages, "softnix_ocr"),
            "fallback_pages": [1] if page.get("provider") == "ocr_fallback" else [],
            "page_sources": [{"page": 1, "provider": page["provider"]}],
            "provider_counts": _provider_counts(pages),
            "mapping": "pending" if schema else "not_requested",
            "schema_context": schema.name if schema else None,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        return AnydocExtractionResult(markdown, pages, None, metadata)
    finally:
        if normalized_path:
            try:
                os.unlink(normalized_path)
            except OSError:
                logger.warning("Unable to remove temporary normalized image")


def extract_anydoc_document(
    file_path: str,
    db: Session,
    schema: DocumentSchema | None,
) -> AnydocExtractionResult:
    """Extract a PDF through AnyDoc or a supported image through OCR normalization."""
    try:
        with open(file_path, "rb") as source:
            is_pdf = source.read(5) == b"%PDF-"
    except OSError as exc:
        raise AnydocFallbackToLegacy(f"AnyDoc could not read the document: {exc}") from exc
    if is_pdf:
        return _extract_anydoc_pdf_document(file_path, db, schema)
    return _extract_anydoc_image_document(file_path, db, schema)


def extract_schema_sample(file_path: str, db: Session) -> AnydocExtractionResult:
    """Extract a schema-design sample without using Softnix OCR.

    The Schema wizard needs reliable source text, not a legacy structured
    extraction result. It therefore prefers AnyDoc's text layer, then routes
    scanned PDF pages and images through TesseractOCR and the configured OCR
    fallback only.
    """
    try:
        with open(file_path, "rb") as source:
            is_pdf = source.read(5) == b"%PDF-"
    except OSError as exc:
        raise AnydocTerminalError(f"Unable to read schema sample: {exc}") from exc

    if is_pdf:
        return _extract_anydoc_pdf_document(
            file_path,
            db,
            None,
            allow_softnix_ocr=False,
            pipeline_name="schema_sample",
        )
    return _extract_anydoc_image_document(
        file_path,
        db,
        None,
        allow_softnix_ocr=False,
        pipeline_name="schema_sample",
    )
