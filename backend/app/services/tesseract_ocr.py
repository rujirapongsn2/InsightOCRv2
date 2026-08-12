"""Local Tesseract OCR adapter used before external OCR providers."""
from __future__ import annotations

import os
import subprocess


class TesseractOcrError(RuntimeError):
    """Raised when local Tesseract cannot return usable text."""


def process_tesseract_ocr(
    file_path: str,
    *,
    language: str = "tha+eng",
    timeout: int | float = 30,
) -> str:
    """Extract text locally without exposing the document to an external API."""
    if not os.path.isfile(file_path):
        raise TesseractOcrError("TesseractOCR input file was not found")

    try:
        result = subprocess.run(
            ["tesseract", file_path, "stdout", "-l", language],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1, timeout),
        )
    except FileNotFoundError as exc:
        raise TesseractOcrError("TesseractOCR is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise TesseractOcrError("TesseractOCR timed out") from exc
    except OSError as exc:
        raise TesseractOcrError(f"TesseractOCR could not start: {exc}") from exc

    text = result.stdout.strip()
    if result.returncode != 0:
        raise TesseractOcrError("TesseractOCR failed to process the page")
    if not text:
        raise TesseractOcrError("TesseractOCR returned no text")
    return text
