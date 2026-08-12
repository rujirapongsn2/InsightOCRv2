from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.tesseract_ocr import (
    TesseractOcrError,
    process_tesseract_ocr,
    process_tesseract_ocr_tsv,
)


def test_tesseract_ocr_uses_configured_language_and_returns_text(tmp_path):
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"image")

    with patch(
        "app.services.tesseract_ocr.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout="  ภาษาไทย  ", stderr=""),
    ) as run:
        assert process_tesseract_ocr(str(image_path), language="tha+eng", timeout=12) == "ภาษาไทย"

    assert run.call_args.args[0] == ["tesseract", str(image_path), "stdout", "-l", "tha+eng"]
    assert run.call_args.kwargs["timeout"] == 12


def test_tesseract_ocr_rejects_empty_output(tmp_path):
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"image")

    with patch(
        "app.services.tesseract_ocr.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
    ):
        with pytest.raises(TesseractOcrError, match="returned no text"):
            process_tesseract_ocr(str(image_path))


def test_tesseract_ocr_tsv_returns_positioned_words(tmp_path):
    image_path = tmp_path / "page.png"
    image_path.write_bytes(b"image")
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t12\t34\t56\t18\t95\tInvoice\n"
    )

    with patch(
        "app.services.tesseract_ocr.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout=tsv, stderr=""),
    ) as run:
        assert process_tesseract_ocr_tsv(str(image_path), language="eng", timeout=8) == [
            {"text": "Invoice", "x": 12.0, "y": 34.0, "width": 56.0, "height": 18.0}
        ]

    assert run.call_args.args[0] == ["tesseract", str(image_path), "stdout", "-l", "eng", "tsv"]
