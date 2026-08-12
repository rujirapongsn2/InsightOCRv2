from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.tesseract_ocr import TesseractOcrError, process_tesseract_ocr


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
