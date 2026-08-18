from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from app.schemas.schema import DocumentSchemaCreate
from app.services import anydoc_pipeline
from app.services.anydoc_pipeline import (
    AnydocFallbackToLegacy,
    AnydocTerminalError,
    _remaining_timeout,
    extract_anydoc_document,
    extract_schema_sample,
)
from app.services.extraction_profiles import validate_extraction_profile


class FakeQuery:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class FakeDb:
    def __init__(self, setting):
        self.setting = setting

    def query(self, _model):
        return FakeQuery(self.setting)


class FakeAnydoc:
    EncryptedError = RuntimeError

    @staticmethod
    def format_from_bytes(_data):
        return "pdf"

    @staticmethod
    def to_markdown_with_ocr(_data, _format, recognize):
        return "# Receipt\n" + recognize(b"png", 2)


def _schema():
    return SimpleNamespace(
        name="Invoice",
        document_type="invoice",
        fields=[
            {"name": "invoice_number", "type": "text", "required": True},
            {"name": "total_amount", "type": "currency", "required": True},
        ],
    )


def _setting(enabled=True):
    return SimpleNamespace(ocr_fallback_enabled=enabled, ocr_fallback_api_key=None, verify_ssl=True)


def _write_pdf_placeholder(tmp_path):
    path = tmp_path / "receipt.pdf"
    path.write_bytes(b"%PDF-1.7 placeholder")
    return str(path)


def _write_image(tmp_path):
    path = tmp_path / "receipt.png"
    Image.new("RGB", (24, 16), "white").save(path)
    return str(path)


@pytest.fixture(autouse=True)
def _skip_local_tesseract(monkeypatch):
    """Keep provider-chain tests deterministic; override per Tesseract test."""
    monkeypatch.setattr(anydoc_pipeline, "process_tesseract_ocr", lambda *_args, **_kwargs: "")


def test_anydoc_hybrid_preserves_all_pages_without_field_mapping(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline, "_load_anydoc", lambda: FakeAnydoc())
    monkeypatch.setattr(
        anydoc_pipeline,
        "_pdf_text_pages",
        lambda _path: [
            {"page_number": 1, "ocr_text": "Invoice INV-2026-01"},
            {"page_number": 2, "ocr_text": ""},
        ],
    )
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_ocr",
        lambda *_args, **_kwargs: {"results": {"pages": [{"ocr_text": "Total 1250.50"}]}},
    )
    result = extract_anydoc_document(_write_pdf_placeholder(tmp_path), FakeDb(_setting()), _schema())

    assert result.markdown.endswith("Total 1250.50")
    assert [page["page_number"] for page in result.pages] == [1, 2]
    assert result.pages[1]["provider"] == "softnix_ocr"
    assert result.metadata["ocr_pages"] == [2]
    assert result.extracted_data is None
    assert result.metadata["mapping"] == "pending"


def test_anydoc_hybrid_uses_configured_fallback_for_a_failed_page(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline, "_load_anydoc", lambda: FakeAnydoc())
    monkeypatch.setattr(anydoc_pipeline, "_pdf_text_pages", lambda _path: [{"page_number": 1, "ocr_text": ""}, {"page_number": 2, "ocr_text": ""}])
    monkeypatch.setattr(anydoc_pipeline, "process_ocr", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("primary down")))
    monkeypatch.setattr(anydoc_pipeline, "resolve_fallback_api_key", lambda _setting: ("fallback-key", "environment"))
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_fallback_ocr",
        lambda *_args, **_kwargs: {"results": {"pages": [{"ocr_text": "Fallback total 20"}]}},
    )
    monkeypatch.setattr(anydoc_pipeline, "get_verify_ssl", lambda *_args: True)
    result = extract_anydoc_document(_write_pdf_placeholder(tmp_path), FakeDb(_setting()), _schema())

    assert result.pages[1]["provider"] == "ocr_fallback"
    assert result.metadata["provider_counts"] == {
        "tesseract_ocr": 0,
        "softnix_ocr": 0,
        "ocr_fallback": 1,
    }


def test_anydoc_format_detection_error_falls_back_to_legacy(monkeypatch, tmp_path):
    class BrokenFormatAnydoc(FakeAnydoc):
        @staticmethod
        def format_from_bytes(_data):
            raise RuntimeError("malformed document")

    monkeypatch.setattr(anydoc_pipeline, "_load_anydoc", lambda: BrokenFormatAnydoc())
    monkeypatch.setattr(
        anydoc_pipeline,
        "_pdf_text_pages",
        lambda _path: [{"page_number": 1, "ocr_text": ""}],
    )

    with pytest.raises(AnydocFallbackToLegacy, match="could not detect"):
        extract_anydoc_document(_write_pdf_placeholder(tmp_path), FakeDb(_setting()), _schema())


def test_anydoc_hybrid_fails_when_ocr_providers_return_no_text(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline, "_load_anydoc", lambda: FakeAnydoc())
    monkeypatch.setattr(anydoc_pipeline, "_pdf_text_pages", lambda _path: [{"page_number": 1, "ocr_text": ""}, {"page_number": 2, "ocr_text": ""}])
    monkeypatch.setattr(anydoc_pipeline, "process_ocr", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(anydoc_pipeline, "resolve_fallback_api_key", lambda _setting: ("", "none"))
    monkeypatch.setattr(
        anydoc_pipeline,
        "fallback_configuration_error",
        lambda *_args, **_kwargs: "OCR fallback is enabled but no API key is configured",
    )

    with pytest.raises(AnydocTerminalError, match="enabled but no API key is configured"):
        extract_anydoc_document(_write_pdf_placeholder(tmp_path), FakeDb(_setting(True)), _schema())


def test_anydoc_hybrid_auto_skips_structured_field_mapping(monkeypatch, tmp_path):
    class TextLayerAnydoc(FakeAnydoc):
        @staticmethod
        def to_markdown_with_ocr(_data, _format, _recognize):
            return "# Contract\n\nText-layer content"

    monkeypatch.setattr(anydoc_pipeline, "_load_anydoc", lambda: TextLayerAnydoc())
    monkeypatch.setattr(
        anydoc_pipeline,
        "_pdf_text_pages",
        lambda _path: [{"page_number": 1, "ocr_text": "Text-layer content"}],
    )
    result = extract_anydoc_document(_write_pdf_placeholder(tmp_path), FakeDb(_setting()), None)

    assert result.extracted_data is None
    assert result.metadata["mapping"] == "not_requested"


def test_anydoc_hybrid_image_uses_softnix_ocr_after_tesseract_and_skips_auto_mapping(monkeypatch, tmp_path):
    monkeypatch.setattr(
        anydoc_pipeline,
        "_load_anydoc",
        lambda: (_ for _ in ()).throw(AssertionError("image extraction must not load the PDF parser")),
    )
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_ocr",
        lambda *_args, **_kwargs: {"results": {"pages": [{"ocr_text": "Receipt total 42"}]}},
    )
    result = extract_anydoc_document(_write_image(tmp_path), FakeDb(_setting()), None)

    assert result.markdown == "Receipt total 42"
    assert result.pages == [{"page_number": 1, "ocr_text": "Receipt total 42", "provider": "softnix_ocr"}]
    assert result.extracted_data is None
    assert result.metadata["source"] == "image"
    assert result.metadata["mapping"] == "not_requested"
    assert result.metadata["provider_counts"] == {
        "tesseract_ocr": 0,
        "softnix_ocr": 1,
        "ocr_fallback": 0,
    }


def test_anydoc_hybrid_image_uses_fallback_when_primary_returns_no_text(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline, "process_ocr", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(anydoc_pipeline, "resolve_fallback_api_key", lambda _setting: ("fallback-key", "environment"))
    monkeypatch.setattr(anydoc_pipeline, "get_verify_ssl", lambda *_args: True)
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_fallback_ocr",
        lambda *_args, **_kwargs: {"results": {"pages": [{"ocr_text": "Fallback image text"}]}},
    )

    result = extract_anydoc_document(_write_image(tmp_path), FakeDb(_setting()), None)

    assert result.pages[0]["provider"] == "ocr_fallback"
    assert result.metadata["fallback_pages"] == [1]
    assert result.metadata["provider_counts"] == {
        "tesseract_ocr": 0,
        "softnix_ocr": 0,
        "ocr_fallback": 1,
    }


def test_anydoc_hybrid_uses_tesseract_before_softnix_ocr(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline, "process_tesseract_ocr", lambda *_args, **_kwargs: "Local receipt text")
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_ocr",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Softnix OCR must not be called")),
    )

    result = extract_anydoc_document(_write_image(tmp_path), FakeDb(_setting()), None)

    assert result.pages[0]["provider"] == "tesseract_ocr"
    assert result.metadata["tesseract_pages"] == [1]
    assert result.metadata["softnix_ocr_pages"] == []


def test_anydoc_quality_gate_routes_nonempty_corrupt_text_layer_to_tesseract(monkeypatch, tmp_path):
    class CorruptTextLayerAnydoc(FakeAnydoc):
        @staticmethod
        def to_markdown_bytes(_data, _format):
            return "unused valid page markdown"

        @staticmethod
        def to_markdown_with_ocr(*_args, **_kwargs):
            raise AssertionError("Corrupt text layer must use the explicit page OCR path")

    monkeypatch.setattr(anydoc_pipeline, "_load_anydoc", lambda: CorruptTextLayerAnydoc())
    monkeypatch.setattr(
        anydoc_pipeline,
        "_pdf_text_pages",
        lambda _path: [
            {"page_number": 1, "ocr_text": "เพี้ยน\x1f@0N"},
            {"page_number": 2, "ocr_text": "เพี้ยน\x1e@1N"},
        ],
    )
    monkeypatch.setattr(anydoc_pipeline, "_single_pdf_page_bytes", lambda *_args: b"page")
    monkeypatch.setattr(anydoc_pipeline, "_render_pdf_page", lambda *_args: "/tmp/page.png")
    monkeypatch.setattr(anydoc_pipeline, "_cleanup_rendered_page", lambda _path: None)
    monkeypatch.setattr(anydoc_pipeline, "process_tesseract_ocr", lambda *_args, **_kwargs: "Readable Thai OCR")

    result = extract_anydoc_document(_write_pdf_placeholder(tmp_path), FakeDb(_setting()), _schema())

    assert result.markdown == "Readable Thai OCR\n\nReadable Thai OCR"
    assert result.metadata["text_layer_invalid_pages"] == [1, 2]
    assert result.metadata["tesseract_pages"] == [1, 2]
    assert result.metadata["ocr_pages"] == [1, 2]


def test_manual_ocr_engine_forces_selected_provider_for_every_pdf_page(monkeypatch, tmp_path):
    class ManualEngineAnydoc(FakeAnydoc):
        @staticmethod
        def to_markdown_bytes(_data, _format):
            return "unused text layer"

    monkeypatch.setattr(anydoc_pipeline, "_load_anydoc", lambda: ManualEngineAnydoc())
    monkeypatch.setattr(
        anydoc_pipeline,
        "_pdf_text_pages",
        lambda _path: [{"page_number": 1, "ocr_text": "Good text layer"}],
    )
    monkeypatch.setattr(anydoc_pipeline, "_render_pdf_page", lambda *_args: "/tmp/page.png")
    monkeypatch.setattr(anydoc_pipeline, "_cleanup_rendered_page", lambda _path: None)
    monkeypatch.setattr(anydoc_pipeline, "process_tesseract_ocr", lambda *_args, **_kwargs: pytest.fail("Tesseract must not run"))
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_ocr",
        lambda *_args, **_kwargs: {"results": {"pages": [{"ocr_text": "Softnix manual OCR"}]}},
    )

    result = extract_anydoc_document(
        _write_pdf_placeholder(tmp_path),
        FakeDb(_setting()),
        _schema(),
        requested_ocr_engine="softnix_ocr",
    )

    assert result.markdown == "Softnix manual OCR"
    assert result.pages[0]["provider"] == "softnix_ocr"
    assert result.metadata["requested_ocr_engine"] == "softnix_ocr"


def test_anydoc_hybrid_continues_when_tesseract_has_an_unexpected_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_tesseract_ocr",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("local runtime error")),
    )
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_ocr",
        lambda *_args, **_kwargs: {"results": {"pages": [{"ocr_text": "Softnix result"}]}},
    )

    result = extract_anydoc_document(_write_image(tmp_path), FakeDb(_setting()), None)

    assert result.pages[0]["provider"] == "softnix_ocr"


def test_anydoc_image_rejects_pixel_limit_before_loading_or_calling_ocr(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline.settings, "ANYDOC_MAX_IMAGE_PIXELS", 100)
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_ocr",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("OCR must not be called")),
    )

    with pytest.raises(AnydocTerminalError, match="exceeds 100 pixels"):
        extract_anydoc_document(_write_image(tmp_path), FakeDb(_setting()), None)


def test_schema_profile_is_limited_to_supported_values():
    with pytest.raises(ValidationError):
        DocumentSchemaCreate(
            name="Bad profile",
            document_type="invoice",
            extraction_profile="not-a-profile",
            fields=[],
        )


def test_anydoc_profile_supports_all_schema_document_types():
    assert validate_extraction_profile("contract", "anydoc_hybrid") == "anydoc_hybrid"


def test_anydoc_budget_expires_before_another_provider_call():
    with pytest.raises(AnydocTerminalError, match="time budget"):
        _remaining_timeout(-1, 90)


def test_anydoc_hybrid_uses_the_configured_primary_page_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(anydoc_pipeline, "_load_anydoc", lambda: FakeAnydoc())
    monkeypatch.setattr(anydoc_pipeline, "_pdf_text_pages", lambda _path: [{"page_number": 1, "ocr_text": ""}, {"page_number": 2, "ocr_text": ""}])
    monkeypatch.setattr(anydoc_pipeline.settings, "ANYDOC_PRIMARY_OCR_TIMEOUT_SECONDS", 17)
    observed_timeouts = []

    def process_primary(*_args, **kwargs):
        observed_timeouts.append(kwargs["timeout"])
        return {"results": {"pages": [{"ocr_text": "Total 20"}]}}

    monkeypatch.setattr(anydoc_pipeline, "process_ocr", process_primary)
    extract_anydoc_document(_write_pdf_placeholder(tmp_path), FakeDb(_setting()), _schema())

    assert observed_timeouts
    assert all(1 <= timeout <= 17 for timeout in observed_timeouts)


def test_schema_sample_uses_anydoc_text_layer_without_calling_ocr(monkeypatch, tmp_path):
    class TextLayerAnydoc(FakeAnydoc):
        @staticmethod
        def to_markdown_with_ocr(_data, _format, _recognize):
            return "# Invoice\n\nInvoice number: INV-2026-42"

    monkeypatch.setattr(anydoc_pipeline, "_load_anydoc", lambda: TextLayerAnydoc())
    monkeypatch.setattr(
        anydoc_pipeline,
        "_pdf_text_pages",
        lambda _path: [{"page_number": 1, "ocr_text": "Invoice number: INV-2026-42"}],
    )
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_ocr",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Softnix OCR must not be called")),
    )

    result = extract_schema_sample(_write_pdf_placeholder(tmp_path), FakeDb(_setting()))

    assert result.markdown.startswith("# Invoice")
    assert result.metadata["pipeline"] == "schema_sample"
    assert result.metadata["text_layer_pages"] == [1]
    assert result.metadata["provider_counts"]["softnix_ocr"] == 0


def test_schema_sample_uses_ocr_fallback_without_softnix_ocr(monkeypatch, tmp_path):
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_ocr",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Softnix OCR must not be called")),
    )
    monkeypatch.setattr(anydoc_pipeline, "resolve_fallback_api_key", lambda _setting: ("fallback-key", "environment"))
    monkeypatch.setattr(anydoc_pipeline, "get_verify_ssl", lambda *_args: True)
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_fallback_ocr",
        lambda *_args, **_kwargs: {"results": {"pages": [{"ocr_text": "Fallback sample text"}]}},
    )

    result = extract_schema_sample(_write_image(tmp_path), FakeDb(_setting()))

    assert result.markdown == "Fallback sample text"
    assert result.pages[0]["provider"] == "ocr_fallback"
    assert result.metadata["provider_counts"] == {
        "tesseract_ocr": 0,
        "softnix_ocr": 0,
        "ocr_fallback": 1,
    }


def test_schema_sample_fails_when_tesseract_and_fallback_return_no_text(monkeypatch, tmp_path):
    monkeypatch.setattr(
        anydoc_pipeline,
        "process_ocr",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Softnix OCR must not be called")),
    )
    monkeypatch.setattr(anydoc_pipeline, "resolve_fallback_api_key", lambda _setting: ("", "none"))

    with pytest.raises(AnydocTerminalError, match="TesseractOCR and OCR fallback"):
        extract_schema_sample(_write_image(tmp_path), FakeDb(_setting(False)))
