"""Fixed-position field extraction for AnyDoc-backed document schemas.

The pinned AnyDoc Python package owns document detection and Markdown
normalisation.  Its Rust ``Locator::Bbox`` type is not exposed by that Python
binding, so this adapter supplies the same rectangle semantics from the source
text layer.  It uses Poppler's word boxes for PDF text layers and Tesseract TSV
only when a page has no text layer.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Iterable

from PIL import Image
from pypdf import PdfReader

from app.core.config import settings
from app.services.pdf_render import find_pdftoppm_page_png
from app.services.tesseract_ocr import TesseractOcrError, process_tesseract_ocr_tsv


class BboxLocatorError(ValueError):
    """A requested fixed-position locator cannot be evaluated safely."""


# These characters are printed as blank form guides rather than user-provided
# content. Keep the pattern deliberately narrow: hyphens, digits, Thai text,
# and ordinary punctuation remain untouched.
_FORM_PLACEHOLDER_PATTERN = re.compile(r"[._\u00b7\u2022\u2024\u2025\u2026\u22ef]{3,}")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_TABLE_SUMMARY_LABEL_PATTERN = re.compile(
    r"^\s*(?:total|subtotal|grand\s+total|vat|tax|discount|balance|"
    r"รวม(?:เป็นเงิน|ทั้งสิ้น|สุทธิ)?|ภาษี|ส่วนลด|ยอด(?:รวม|สุทธิ|คงเหลือ))",
    re.IGNORECASE,
)


def clean_fixed_position_value(value: str, *, remove_placeholders: bool = True) -> str:
    """Return a conservative display/mapping value from a BBox text result.

    The raw BBox value is retained in field evidence. Only repeated form-guide
    characters are removed by default, so real Thai text and identifiers are
    never inferred or discarded by a generic label-cleaning rule.
    """
    cleaned = str(value or "")
    if remove_placeholders:
        cleaned = _FORM_PLACEHOLDER_PATTERN.sub(" ", cleaned)
    return _WHITESPACE_PATTERN.sub(" ", cleaned).strip()


def _normalise_words(
    words: Iterable[dict[str, Any]],
    page_width: float,
    page_height: float,
) -> list[dict[str, Any]]:
    if page_width <= 0 or page_height <= 0:
        raise BboxLocatorError("The source page has invalid dimensions")

    normalised: list[dict[str, Any]] = []
    for word in words:
        text = str(word.get("text") or "").strip()
        if not text:
            continue
        try:
            x = float(word["x"])
            y = float(word["y"])
            width = float(word["width"])
            height = float(word["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if width <= 0 or height <= 0:
            continue
        normalised.append(
            {
                "text": text,
                "x": round(x * 100 / page_width, 4),
                "y": round(y * 100 / page_height, 4),
                "width": round(width * 100 / page_width, 4),
                "height": round(height * 100 / page_height, 4),
            }
        )
    return normalised


def _read_pdf_text_layer(file_path: str) -> dict[int, list[dict[str, Any]]]:
    """Read PDF word boxes directly from its text layer through Poppler."""
    try:
        result = subprocess.run(
            ["pdftotext", "-bbox", file_path, "-"],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1, settings.TESSERACT_OCR_TIMEOUT_SECONDS),
        )
    except FileNotFoundError as exc:
        raise BboxLocatorError("pdftotext is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise BboxLocatorError("Reading PDF text-layer coordinates timed out") from exc
    if result.returncode != 0:
        raise BboxLocatorError("Unable to read PDF text-layer coordinates")

    try:
        root = ET.fromstring(result.stdout)
    except ET.ParseError as exc:
        raise BboxLocatorError("PDF text-layer coordinates are invalid") from exc

    pages: dict[int, list[dict[str, Any]]] = {}
    for page_index, page in enumerate((node for node in root.iter() if node.tag.endswith("page")), start=1):
        try:
            page_width = float(page.attrib["width"])
            page_height = float(page.attrib["height"])
        except (KeyError, ValueError) as exc:
            raise BboxLocatorError("PDF text-layer page dimensions are invalid") from exc

        raw_words: list[dict[str, Any]] = []
        for word in (node for node in page.iter() if node.tag.endswith("word")):
            text = (word.text or "").strip()
            if not text:
                continue
            try:
                xmin = float(word.attrib["xMin"])
                ymin = float(word.attrib["yMin"])
                xmax = float(word.attrib["xMax"])
                ymax = float(word.attrib["yMax"])
            except (KeyError, ValueError):
                continue
            raw_words.append(
                {"text": text, "x": xmin, "y": ymin, "width": xmax - xmin, "height": ymax - ymin}
            )
        pages[page_index] = _normalise_words(raw_words, page_width, page_height)
    return pages


def _render_pdf_page(file_path: str, page_number: int) -> str:
    directory = tempfile.mkdtemp(prefix="bbox-locator-")
    output_prefix = os.path.join(directory, "page")
    try:
        result = subprocess.run(
            [
                "pdftoppm", "-png", "-f", str(page_number), "-l", str(page_number),
                "-r", "200", file_path, output_prefix,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=max(1, settings.TESSERACT_OCR_TIMEOUT_SECONDS),
        )
    except FileNotFoundError as exc:
        _cleanup_rendered_directory(directory)
        raise BboxLocatorError("pdftoppm is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        _cleanup_rendered_directory(directory)
        raise BboxLocatorError("Rendering the scanned PDF page timed out") from exc
    rendered_path = find_pdftoppm_page_png(output_prefix, page_number)
    if result.returncode != 0 or rendered_path is None or not os.path.isfile(rendered_path):
        _cleanup_rendered_directory(directory)
        detail = result.stderr.strip()
        suffix = f": {detail[:500]}" if detail else ""
        raise BboxLocatorError(f"Unable to render PDF page {page_number} for OCR{suffix}")
    return rendered_path


def _cleanup_rendered_directory(directory: str) -> None:
    """Remove a temporary page-render directory after either success or failure."""
    shutil.rmtree(directory, ignore_errors=True)


def _cleanup_rendered_page(image_path: str) -> None:
    _cleanup_rendered_directory(os.path.dirname(image_path))


def _tesseract_page_words(image_path: str) -> list[dict[str, Any]]:
    try:
        with Image.open(image_path) as image:
            width, height = image.size
    except OSError as exc:
        raise BboxLocatorError("Unable to inspect the OCR image") from exc
    try:
        words = process_tesseract_ocr_tsv(
            image_path,
            language=settings.TESSERACT_OCR_LANGUAGE,
            timeout=settings.TESSERACT_OCR_TIMEOUT_SECONDS,
        )
    except TesseractOcrError as exc:
        raise BboxLocatorError(str(exc)) from exc
    return _normalise_words(words, width, height)


def build_bbox_layout(file_path: str, page_numbers: Iterable[int]) -> dict[int, dict[str, Any]]:
    """Return positioned words for selected PDF pages or a single image page.

    Coordinates are percentages with a top-left origin, so a Schema remains
    stable if a browser renders the same fixed-layout form at another scale.
    """
    requested_pages = sorted({int(page) for page in page_numbers})
    if not requested_pages or any(page < 1 for page in requested_pages):
        raise BboxLocatorError("A fixed-position field must use a page number of 1 or greater")
    try:
        with open(file_path, "rb") as source:
            is_pdf = source.read(5) == b"%PDF-"
    except OSError as exc:
        raise BboxLocatorError("The source document could not be read") from exc

    if not is_pdf:
        if requested_pages != [1]:
            raise BboxLocatorError("Image documents only support page 1")
        words = _tesseract_page_words(file_path)
        return {1: {"source": "tesseract_ocr", "words": words}}

    try:
        reader = PdfReader(file_path)
        if reader.is_encrypted:
            raise BboxLocatorError("PDF is encrypted and cannot be used for fixed-position fields")
        page_count = len(reader.pages)
    except BboxLocatorError:
        raise
    except Exception as exc:
        raise BboxLocatorError("Unable to inspect the PDF") from exc
    if page_count > settings.ANYDOC_MAX_PAGES:
        raise BboxLocatorError(f"PDF has more than {settings.ANYDOC_MAX_PAGES} pages")
    if any(page > page_count for page in requested_pages):
        raise BboxLocatorError("A fixed-position field refers to a page outside this PDF")

    try:
        text_layout = _read_pdf_text_layer(file_path)
    except BboxLocatorError:
        # Some embedded fonts produce invalid XML even though the rendered
        # page is readable. Recover coordinates from the page image.
        text_layout = {}
    for page_number, words in list(text_layout.items()):
        text = " ".join(word["text"] for word in words)
        if "\ufffd" in text or any(ord(char) < 32 and char not in "\n\r\t" for char in text):
            text_layout[page_number] = []
    ocr_page_numbers = [
        page_number
        for page_number in requested_pages
        if not text_layout.get(page_number, [])
    ]
    if len(ocr_page_numbers) > settings.ANYDOC_MAX_OCR_PAGES:
        raise BboxLocatorError("Too many scanned pages were requested for fixed-position fields")

    layout: dict[int, dict[str, Any]] = {}
    for page_number in requested_pages:
        words = text_layout.get(page_number, [])
        if words:
            layout[page_number] = {"source": "text_layer", "words": words}
            continue
        image_path = _render_pdf_page(file_path, page_number)
        try:
            layout[page_number] = {"source": "tesseract_ocr", "words": _tesseract_page_words(image_path)}
        finally:
            _cleanup_rendered_page(image_path)
    return layout


def _intersects(locator: dict[str, Any], word: dict[str, Any]) -> bool:
    left = float(locator["x"])
    top = float(locator["y"])
    right = left + float(locator["width"])
    bottom = top + float(locator["height"])
    word_left = float(word["x"])
    word_top = float(word["y"])
    word_right = word_left + float(word["width"])
    word_bottom = word_top + float(word["height"])
    center_x = (word_left + word_right) / 2
    center_y = (word_top + word_bottom) / 2
    return left <= center_x <= right and top <= center_y <= bottom


def _value_from_words(locator: dict[str, Any], words: Iterable[dict[str, Any]]) -> str:
    """Return reading-order text for one BBox from positioned words."""
    selected_words = [word for word in words if _intersects(locator, word)]
    selected_words.sort(key=lambda word: (round(float(word["y"]) / 1.5), float(word["x"])))
    return " ".join(str(word["text"]) for word in selected_words).strip()


def _words_in_locator(locator: dict[str, Any], words: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [word for word in words if _intersects(locator, word)]


def _group_words_into_lines(words: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group positioned words into visual lines without relying on OCR order."""
    ordered = sorted(
        words,
        key=lambda word: (
            (float(word["y"]) + float(word["height"]) / 2),
            float(word["x"]),
        ),
    )
    if not ordered:
        return []

    heights = sorted(float(word["height"]) for word in ordered)
    median_height = heights[len(heights) // 2]
    tolerance = max(0.18, median_height * 0.7)
    lines: list[list[dict[str, Any]]] = []
    line_centers: list[float] = []
    for word in ordered:
        center = float(word["y"]) + float(word["height"]) / 2
        if lines and abs(center - line_centers[-1]) <= tolerance:
            lines[-1].append(word)
            line_centers[-1] = sum(
                float(item["y"]) + float(item["height"]) / 2
                for item in lines[-1]
            ) / len(lines[-1])
        else:
            lines.append([word])
            line_centers.append(center)
    for line in lines:
        line.sort(key=lambda word: float(word["x"]))
    return lines


def _table_column_bounds(locator: dict[str, Any], column: dict[str, Any]) -> tuple[float, float]:
    parent_x = float(locator["x"])
    parent_width = float(locator["width"])
    left = parent_x + parent_width * float(column["x"]) / 100
    right = left + parent_width * float(column["width"]) / 100
    return left, right


def _line_table_cells(
    line: Iterable[dict[str, Any]],
    locator: dict[str, Any],
    columns: list[dict[str, Any]],
) -> dict[str, str]:
    cells = {str(column["name"]): [] for column in columns}
    for word in line:
        word_center = float(word["x"]) + float(word["width"]) / 2
        for column in columns:
            left, right = _table_column_bounds(locator, column)
            if left <= word_center <= right:
                cells[str(column["name"])].append(str(word["text"]))
                break
    return {name: " ".join(parts).strip() for name, parts in cells.items()}


def _append_table_cells(row: dict[str, str], cells: dict[str, str]) -> None:
    for name, value in cells.items():
        if not value:
            continue
        row[name] = " ".join(part for part in (row.get(name, ""), value) if part).strip()


def _has_text_table_cells(cells: dict[str, str], columns: Iterable[dict[str, Any]]) -> bool:
    return any(
        cells.get(str(column["name"]), "")
        for column in columns
        if str(column.get("type") or "text") == "text"
    )


def _is_table_summary_line(cells: dict[str, str], columns: Iterable[dict[str, Any]]) -> bool:
    labels = " ".join(
        cells.get(str(column["name"]), "")
        for column in columns
        if str(column.get("type") or "text") == "text"
    ).strip()
    return bool(_TABLE_SUMMARY_LABEL_PATTERN.match(labels))


def _append_table_continuation(
    row: dict[str, str],
    cells: dict[str, str],
    columns: Iterable[dict[str, Any]],
) -> None:
    """Append wrapped text and fill values that are aligned on a later line."""
    for column in columns:
        name = str(column["name"])
        value = cells.get(name, "")
        if not value:
            continue
        if str(column.get("type") or "text") == "text":
            row[name] = " ".join(part for part in (row.get(name, ""), value) if part).strip()
        elif not row.get(name):
            row[name] = value


def _extract_table_rows(
    locator: dict[str, Any],
    array_config: dict[str, Any],
    words: Iterable[dict[str, Any]],
    *,
    clean_placeholders: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Read a BBox table as raw rows and conservatively cleaned rows.

    Anchor mode starts a new row only when the selected anchor column has text.
    This is deliberately safer for quotations whose descriptions wrap across
    multiple visual lines: subsequent lines are appended to the current item
    instead of becoming phantom line items.
    """
    columns = [column for column in array_config.get("columns", []) if isinstance(column, dict)]
    if not columns:
        raise BboxLocatorError("A fixed-position array field needs at least one table column")
    row_detection = array_config.get("row_detection", "anchor_column")
    anchor_column = str(array_config.get("anchor_column") or "")
    if row_detection == "anchor_column" and anchor_column not in {str(column.get("name")) for column in columns}:
        raise BboxLocatorError("The selected table anchor column is invalid")

    lines = _group_words_into_lines(_words_in_locator(locator, words))
    header_rows = int(array_config.get("header_rows", 1) or 0)
    raw_rows: list[dict[str, str]] = []
    current_row: dict[str, str] | None = None
    for line in lines[header_rows:]:
        cells = _line_table_cells(line, locator, columns)
        if not any(cells.values()):
            continue
        is_new_row = row_detection == "line" or bool(cells.get(anchor_column))
        if is_new_row:
            current_row = {str(column["name"]): cells.get(str(column["name"]), "") for column in columns}
            raw_rows.append(current_row)
        elif current_row is not None:
            # Spreadsheet-originated PDFs can put prices at the baseline of a
            # wrapped description, after the row's anchor number. Keep those
            # values with the active item, while excluding recognizable totals.
            non_text_values = [
                cells.get(str(column["name"]), "")
                for column in columns
                if str(column.get("type") or "text") != "text"
            ]
            if _is_table_summary_line(cells, columns):
                continue
            if _has_text_table_cells(cells, columns):
                _append_table_continuation(current_row, cells, columns)
            elif not any(non_text_values):
                _append_table_cells(current_row, cells)

    cleaned_rows: list[dict[str, str]] = []
    for row in raw_rows:
        cleaned = {
            name: clean_fixed_position_value(value, remove_placeholders=clean_placeholders)
            for name, value in row.items()
        }
        if any(cleaned.values()):
            cleaned_rows.append(cleaned)
    return raw_rows, cleaned_rows


def _read_bbox_from_tesseract(file_path: str, page_number: int) -> list[dict[str, Any]]:
    """Render one PDF page temporarily and return its local OCR word boxes."""
    image_path = _render_pdf_page(file_path, page_number)
    try:
        return _tesseract_page_words(image_path)
    finally:
        _cleanup_rendered_page(image_path)


def extract_fixed_position_fields(file_path: str, fields: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Extract field values and compact evidence for Schema BBox locators."""
    locator_fields = [field for field in fields if isinstance(field.get("locator"), dict)]
    if not locator_fields:
        return {}, {}

    layout = build_bbox_layout(file_path, (field["locator"].get("page", 1) for field in locator_fields))
    values: dict[str, Any] = {}
    evidence: dict[str, Any] = {}
    ocr_words_by_page: dict[int, list[dict[str, Any]]] = {}
    for field in locator_fields:
        name = str(field.get("name") or "").strip()
        locator = dict(field["locator"])
        if not name:
            continue
        page_number = int(locator.get("page", 1))
        page_layout = layout[page_number]
        array_config = field.get("array_config")
        if field.get("type") == "array" and isinstance(array_config, dict):
            remove_placeholders = bool(locator.get("clean_placeholders", True))
            raw_rows, cleaned_rows = _extract_table_rows(
                locator,
                array_config,
                page_layout["words"],
                clean_placeholders=remove_placeholders,
            )
            source = page_layout["source"]
            text_layer_rows: list[dict[str, str]] | None = None
            if source == "text_layer" and not cleaned_rows:
                if page_number not in ocr_words_by_page:
                    if len(ocr_words_by_page) >= settings.ANYDOC_MAX_OCR_PAGES:
                        raise BboxLocatorError("Too many text-layer BBoxes required local OCR fallback")
                    ocr_words_by_page[page_number] = _read_bbox_from_tesseract(file_path, page_number)
                ocr_raw_rows, ocr_cleaned_rows = _extract_table_rows(
                    locator,
                    array_config,
                    ocr_words_by_page[page_number],
                    clean_placeholders=remove_placeholders,
                )
                if ocr_cleaned_rows:
                    text_layer_rows = raw_rows
                    raw_rows = ocr_raw_rows
                    cleaned_rows = ocr_cleaned_rows
                    source = "tesseract_ocr_bbox_fallback"
            values[name] = raw_rows
            evidence[name] = {
                "page": page_number,
                "bbox": {key: locator[key] for key in ("x", "y", "width", "height")},
                "raw_rows": raw_rows,
                "cleaned_value": cleaned_rows,
                "row_count": len(cleaned_rows),
                "array_config": array_config,
                "placeholder_cleanup": remove_placeholders,
                "source": source,
            }
            if text_layer_rows is not None:
                evidence[name]["text_layer_rows"] = text_layer_rows
                evidence[name]["fallback_reason"] = "bbox_table_empty_after_placeholder_cleanup"
            continue
        raw_value = _value_from_words(locator, page_layout["words"])
        remove_placeholders = bool(locator.get("clean_placeholders", True))
        cleaned_value = clean_fixed_position_value(
            raw_value,
            remove_placeholders=remove_placeholders,
        )
        source = page_layout["source"]
        text_layer_value: str | None = None

        # A PDF can contain a static text layer while its filled values are an
        # image. Only fall back when this exact BBox has no usable text after
        # conservative placeholder cleanup; real text-layer values always win.
        if source == "text_layer" and not cleaned_value:
            if page_number not in ocr_words_by_page:
                if len(ocr_words_by_page) >= settings.ANYDOC_MAX_OCR_PAGES:
                    raise BboxLocatorError("Too many text-layer BBoxes required local OCR fallback")
                ocr_words_by_page[page_number] = _read_bbox_from_tesseract(file_path, page_number)
            ocr_raw_value = _value_from_words(locator, ocr_words_by_page[page_number])
            ocr_cleaned_value = clean_fixed_position_value(
                ocr_raw_value,
                remove_placeholders=remove_placeholders,
            )
            if ocr_cleaned_value:
                text_layer_value = raw_value
                raw_value = ocr_raw_value
                cleaned_value = ocr_cleaned_value
                source = "tesseract_ocr_bbox_fallback"

        values[name] = raw_value
        evidence[name] = {
            "page": page_number,
            "bbox": {key: locator[key] for key in ("x", "y", "width", "height")},
            "text": raw_value,
            "raw_text": raw_value,
            "cleaned_text": cleaned_value,
            "cleaned_value": cleaned_value,
            "placeholder_cleanup": remove_placeholders,
            "source": source,
        }
        if text_layer_value is not None:
            evidence[name]["text_layer_text"] = text_layer_value
            evidence[name]["fallback_reason"] = "bbox_empty_after_placeholder_cleanup"
    return values, evidence
