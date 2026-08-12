from types import SimpleNamespace

import pytest

from app.tasks import document_tasks


def _schema(fields):
    return SimpleNamespace(name="packing_list", fields=fields)


def test_anydoc_schema_mapping_uses_selected_schema(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        document_tasks,
        "extract_structure",
        lambda markdown, schema_json, db, prompt: captured.update(
            {"markdown": markdown, "schema_json": schema_json, "prompt": prompt}
        ) or {"structured_output": {"packing_list_number": "PL-2026-0425"}},
    )

    mapped = document_tasks.map_anydoc_schema_fields(
        "# Packing list\nNo: PL-2026-0425",
        _schema([{"name": "packing_list_number", "type": "text"}]),
        object(),
    )

    assert mapped == {"packing_list_number": "PL-2026-0425"}
    assert "packing_list_number" in captured["schema_json"]
    assert "Packing list" in captured["markdown"]


def test_anydoc_schema_mapping_skips_auto_mode():
    assert document_tasks.map_anydoc_schema_fields("text", None, object()) is None


def test_anydoc_schema_mapping_rejects_schema_without_fields():
    with pytest.raises(ValueError, match="has no extraction fields"):
        document_tasks.map_anydoc_schema_fields("text", _schema([]), object())


def test_anydoc_schema_mapping_rejects_fields_outside_selected_schema(monkeypatch):
    monkeypatch.setattr(
        document_tasks,
        "extract_structure",
        lambda *args, **kwargs: {"structured_output": {"unexpected": "value"}},
    )

    with pytest.raises(ValueError, match="outside the selected schema"):
        document_tasks.map_anydoc_schema_fields(
            "Invoice No: INV-1",
            _schema([{"name": "invoice_number", "type": "text"}]),
            object(),
        )


def test_anydoc_schema_mapping_rejects_non_json_provider_text(monkeypatch):
    monkeypatch.setattr(
        document_tasks,
        "extract_structure",
        lambda *args, **kwargs: {"structured_output": "The invoice number is INV-1"},
    )

    with pytest.raises(ValueError, match="outside the selected schema"):
        document_tasks.map_anydoc_schema_fields(
            "Invoice No: INV-1",
            _schema([{"name": "invoice_number", "type": "text"}]),
            object(),
        )


def test_anydoc_schema_mapping_normalizes_numeric_values(monkeypatch):
    monkeypatch.setattr(
        document_tasks,
        "extract_structure",
        lambda *args, **kwargs: {"structured_output": {"total_amount": "1,250.50"}},
    )

    mapped = document_tasks.map_anydoc_schema_fields(
        "Total: 1,250.50",
        _schema([{"name": "total_amount", "type": "currency", "required": True}]),
        object(),
    )

    assert mapped == {"total_amount": 1250.5}


def test_apply_schema_mapping_marks_failures_without_losing_ocr_text(monkeypatch):
    document = SimpleNamespace(filename="invoice.pdf", ocr_text="Invoice No: INV-1", extracted_data=None)
    metadata = {"pipeline": "ocr_fallback"}
    monkeypatch.setattr(
        document_tasks,
        "map_anydoc_schema_fields",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("provider unavailable")),
    )

    error = document_tasks.apply_schema_mapping(
        document,
        _schema([{"name": "invoice_number", "type": "text"}]),
        object(),
        metadata,
    )

    assert error == "provider unavailable"
    assert document.ocr_text == "Invoice No: INV-1"
    assert metadata["mapping"]["status"] == "failed"
