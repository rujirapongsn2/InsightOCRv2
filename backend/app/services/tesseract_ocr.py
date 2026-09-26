"""Local Tesseract OCR adapter used before external OCR providers."""
from __future__ import annotations

import os
import subprocess
import csv
import tempfile
from io import StringIO
from typing import Any


class TesseractOcrError(RuntimeError):
    """Raised when local Tesseract cannot return usable text."""


MAX_WORDS_PER_PAGE = 4000


def process_tesseract_ocr(
    file_path: str,
    *,
    language: str = "tha+eng",
    timeout: int | float = 30,
    words_out: list[dict[str, Any]] | None = None,
) -> str:
    """Extract text locally without exposing the document to an external API.

    With ``words_out``, the same Tesseract pass also writes word positions
    (percent of the image) into that list, so reviewers can see where a value
    sits on a scanned page. Positions are best-effort: text is returned even
    when they cannot be read.
    """
    if not os.path.isfile(file_path):
        raise TesseractOcrError("TesseractOCR input file was not found")

    with tempfile.TemporaryDirectory(prefix="tesseract-") as workdir:
        base = os.path.join(workdir, "page")
        command = ["tesseract", file_path, "stdout", "-l", language]
        if words_out is not None:
            # One recognition pass, two outputs: page.txt and page.tsv.
            command = ["tesseract", file_path, base, "-l", language, "txt", "tsv"]
        try:
            result = subprocess.run(
                command,
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
        if words_out is None:
            text = result.stdout.strip()
        else:
            text = _read(base + ".txt").strip()
            words_out.extend(_percent_words(_read(base + ".tsv"), file_path))
    if not text:
        raise TesseractOcrError("TesseractOCR returned no text")
    return text


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def _percent_words(tsv: str, image_path: str) -> list[dict[str, Any]]:
    """Word boxes as percent of the image, which is the whole rendered page."""
    try:
        from PIL import Image

        with Image.open(image_path) as image:
            width, height = image.size
    except Exception:  # noqa: BLE001 — positions are optional
        return []
    if not width or not height:
        return []
    words: list[dict[str, Any]] = []
    for word in _tsv_words(tsv)[:MAX_WORDS_PER_PAGE]:
        words.append({
            "text": word["text"],
            "x": round(word["x"] / width * 100, 2),
            "y": round(word["y"] / height * 100, 2),
            "width": round(word["width"] / width * 100, 2),
            "height": round(word["height"] / height * 100, 2),
        })
    return words


def _tsv_words(tsv: str) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for row in csv.DictReader(StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        if not text or row.get("level") != "5":
            continue
        try:
            words.append({"text": text, "x": float(row["left"]), "y": float(row["top"]),
                          "width": float(row["width"]), "height": float(row["height"])})
        except (KeyError, TypeError, ValueError):
            continue
    return words


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

    words = _tsv_words(result.stdout)
    if not words:
        raise TesseractOcrError("TesseractOCR returned no positioned text")
    return words
