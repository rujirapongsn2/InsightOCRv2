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
            {"text": "Invoice", "x": 12.0, "y": 34.0, "width": 56.0, "height": 18.0, "conf": 95.0, "line": "1.1.1"}
        ]

    assert run.call_args.args[0] == ["tesseract", str(image_path), "stdout", "-l", "eng", "tsv"]


def test_words_come_from_the_same_pass_as_percent_of_the_image(tmp_path, monkeypatch):
    """One Tesseract run writes page.txt and page.tsv; word boxes become percent of the image."""
    from PIL import Image
    from app.services import tesseract_ocr

    image_path = tmp_path / "page.png"
    Image.new("RGB", (200, 100), "white").save(image_path)
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t20\t10\t40\t5\t95\tINV-1\n"
           "5\t1\t1\t1\t1\t2\t70\t10\t30\t5\t95\t\"quoted\n")
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        base = command[2]
        with open(base + ".txt", "w", encoding="utf-8") as handle:
            handle.write("INV-1 \"quoted\n")
        with open(base + ".tsv", "w", encoding="utf-8") as handle:
            handle.write(tsv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(tesseract_ocr.subprocess, "run", fake_run)
    words = []
    text = tesseract_ocr.process_tesseract_ocr(str(image_path), language="eng", words_out=words)

    assert text == 'INV-1 "quoted'
    assert len(commands) == 1 and commands[0][-2:] == ["txt", "tsv"]
    assert words == [{"text": "INV-1", "x": 10.0, "y": 10.0, "width": 20.0, "height": 5.0, "conf": 95.0, "line": "1.1.1"},
                     {"text": '"quoted', "x": 35.0, "y": 10.0, "width": 15.0, "height": 5.0, "conf": 95.0, "line": "1.1.1"}]


def test_sample_words_reads_each_pdf_page_with_tesseract(monkeypatch, tmp_path):
    from app.api.v1.endpoints import schemas as ep
    from app.services import anydoc_pipeline, ocr, tesseract_ocr

    monkeypatch.setattr(ocr, "count_pdf_pages", lambda path: 7)
    rendered, cleaned = [], []
    monkeypatch.setattr(anydoc_pipeline, "_render_pdf_page", lambda path, page: rendered.append(page) or f"/tmp/p{page}.png")
    monkeypatch.setattr(anydoc_pipeline, "_cleanup_rendered_page", lambda path: cleaned.append(path))

    def fake_ocr(image_path, *, language, timeout, words_out):
        if image_path.endswith("p2.png"):
            raise tesseract_ocr.TesseractOcrError("blank page")
        words_out.append({"text": "INV-1", "x": 1.0, "y": 2.0, "width": 3.0, "height": 1.0})
        return "INV-1"

    monkeypatch.setattr(tesseract_ocr, "process_tesseract_ocr", fake_ocr)
    pages = ep._sample_words_in_worker("sample.pdf", True)

    assert rendered == [1, 2, 3, 4, 5]  # capped at SAMPLE_WORDS_MAX_PAGES
    assert pages[2] == [] and pages[1][0]["text"] == "INV-1"
    assert len(cleaned) == 5
