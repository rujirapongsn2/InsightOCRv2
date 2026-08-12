"""Local Tesseract OCR adapter used before external OCR providers."""
from __future__ import annotations

import os
import subprocess
import csv
from io import StringIO
from typing import Any


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


def process_tesseract_ocr_tsv(
    file_path: str,
    *,
    language: str = "tha+eng",
    timeout: int | float = 30,
) -> list[dict[str, Any]]:
    """Return recognised words with image coordinates for fixed-position fields.

    Tesseract's TSV output is the local OCR equivalent of a BBox locator.  It
    deliberately keeps only word-level entries because grouping can be done
    against a user-selected rectangle without losing the source coordinates.
    """
    if not os.path.isfile(file_path):
        raise TesseractOcrError("TesseractOCR input file was not found")

    try:
        result = subprocess.run(
            ["tesseract", file_path, "stdout", "-l", language, "tsv"],
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

    if result.returncode != 0:
        raise TesseractOcrError("TesseractOCR failed to process the page")

    words: list[dict[str, Any]] = []
    for row in csv.DictReader(StringIO(result.stdout), delimiter="\t"):
        text = (row.get("text") or "").strip()
        if not text or row.get("level") != "5":
            continue
        try:
            words.append(
                {
                    "text": text,
                    "x": float(row["left"]),
                    "y": float(row["top"]),
                    "width": float(row["width"]),
                    "height": float(row["height"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue

    if not words:
        raise TesseractOcrError("TesseractOCR returned no positioned text")
    return words
