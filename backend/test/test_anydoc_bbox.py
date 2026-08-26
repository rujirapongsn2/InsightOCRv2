from pathlib import Path
from types import SimpleNamespace

import pytest

from app.schemas.schema import BboxLocator, SchemaField
from app.services import anydoc_bbox
from app.tasks import document_tasks


def test_bbox_locator_rejects_rectangles_outside_page():
    with pytest.raises(ValueError, match="inside the page"):
        BboxLocator(page=1, x=80, y=10, width=21, height=10)


def test_fixed_position_array_rejects_overlapping_columns():
    with pytest.raises(ValueError, match="cannot overlap"):
        SchemaField.model_validate({
            "name": "line_items",
            "type": "array",
            "locator": {"page": 1, "x": 0, "y": 0, "width": 100, "height": 40},
            "array_config": {
                "row_detection": "line",
                "header_rows": 0,
                "columns": [
                    {"name": "description", "type": "text", "x": 0, "width": 70},
                    {"name": "amount", "type": "currency", "x": 60, "width": 40},
                ],
            },
        })


def test_extract_fixed_position_fields_uses_words_inside_selected_box(monkeypatch):
    monkeypatch.setattr(
        anydoc_bbox,
        "build_bbox_layout",
        lambda _path, _pages: {
            1: {
                "source": "text_layer",
                "words": [
                    {"text": "Invoice", "x": 8, "y": 10, "width": 12, "height": 3},
                    {"text": "INV-42", "x": 21, "y": 10, "width": 12, "height": 3},
                    {"text": "Ignored", "x": 75, "y": 75, "width": 8, "height": 3},
                ],
            }
        },
    )
    values, evidence = anydoc_bbox.extract_fixed_position_fields(
        "/tmp/invoice.pdf",
        [{"name": "invoice_number", "locator": {"page": 1, "x": 5, "y": 5, "width": 35, "height": 15}}],
    )

    assert values == {"invoice_number": "Invoice INV-42"}
    assert evidence["invoice_number"]["source"] == "text_layer"


def test_bbox_preserves_raw_value_and_removes_only_form_placeholders(monkeypatch):
    monkeypatch.setattr(
        anydoc_bbox,
        "build_bbox_layout",
        lambda _path, _pages: {
            1: {
                "source": "text_layer",
                "words": [
                    {"text": "................................", "x": 8, "y": 10, "width": 12, "height": 3},
                    {"text": "Softnix", "x": 21, "y": 10, "width": 12, "height": 3},
                    {"text": "Technology", "x": 34, "y": 10, "width": 12, "height": 3},
                ],
            }
        },
    )

    values, evidence = anydoc_bbox.extract_fixed_position_fields(
        "/tmp/form.pdf",
        [{"name": "company_name", "locator": {"page": 1, "x": 5, "y": 5, "width": 45, "height": 15}}],
    )

    assert values["company_name"].startswith("...")
    assert evidence["company_name"]["raw_text"] == values["company_name"]
    assert evidence["company_name"]["cleaned_text"] == "Softnix Technology"


def test_bbox_can_keep_form_placeholders_when_schema_disables_cleanup(monkeypatch):
    monkeypatch.setattr(
        anydoc_bbox,
        "build_bbox_layout",
        lambda _path, _pages: {1: {"source": "text_layer", "words": [{"text": "....", "x": 8, "y": 10, "width": 12, "height": 3}]}},
    )

    _, evidence = anydoc_bbox.extract_fixed_position_fields(
        "/tmp/form.pdf",
        [{"name": "raw_markers", "locator": {"page": 1, "x": 5, "y": 5, "width": 45, "height": 15, "clean_placeholders": False}}],
    )

    assert evidence["raw_markers"]["cleaned_text"] == "...."


def test_bbox_uses_tesseract_when_text_layer_box_contains_only_placeholders(monkeypatch):
    monkeypatch.setattr(
        anydoc_bbox,
        "build_bbox_layout",
        lambda _path, _pages: {
            1: {
                "source": "text_layer",
                "words": [{"text": "................", "x": 8, "y": 10, "width": 12, "height": 3}],
            }
        },
    )
    monkeypatch.setattr(anydoc_bbox, "_render_pdf_page", lambda *_args: "/tmp/page-1.png")
    monkeypatch.setattr(
        anydoc_bbox,
        "_tesseract_page_words",
        lambda _path: [{"text": "Softnix", "x": 8, "y": 10, "width": 12, "height": 3}],
    )
    monkeypatch.setattr(anydoc_bbox, "_cleanup_rendered_page", lambda _path: None)

    values, evidence = anydoc_bbox.extract_fixed_position_fields(
        "/tmp/form.pdf",
        [{"name": "company_name", "locator": {"page": 1, "x": 5, "y": 5, "width": 45, "height": 15}}],
    )

    assert values == {"company_name": "Softnix"}
    assert evidence["company_name"]["cleaned_text"] == "Softnix"
    assert evidence["company_name"]["text_layer_text"] == "................"
    assert evidence["company_name"]["source"] == "tesseract_ocr_bbox_fallback"


def test_bbox_keeps_usable_text_layer_value_without_running_tesseract(monkeypatch):
    monkeypatch.setattr(
        anydoc_bbox,
        "build_bbox_layout",
        lambda _path, _pages: {
            1: {
                "source": "text_layer",
                "words": [{"text": "Softnix", "x": 8, "y": 10, "width": 12, "height": 3}],
            }
        },
    )
    monkeypatch.setattr(
        anydoc_bbox,
        "_read_bbox_from_tesseract",
        lambda *_args: pytest.fail("Tesseract must not run for usable text-layer values"),
    )

    values, evidence = anydoc_bbox.extract_fixed_position_fields(
        "/tmp/form.pdf",
        [{"name": "company_name", "locator": {"page": 1, "x": 5, "y": 5, "width": 45, "height": 15}}],
    )

    assert values == {"company_name": "Softnix"}
    assert evidence["company_name"]["source"] == "text_layer"


def test_bbox_extracts_array_rows_and_keeps_wrapped_text_with_its_item(monkeypatch):
    monkeypatch.setattr(
        anydoc_bbox,
        "build_bbox_layout",
        lambda _path, _pages: {
            1: {
                "source": "text_layer",
                "words": [
                    {"text": "No", "x": 3, "y": 3, "width": 3, "height": 2},
                    {"text": "Description", "x": 16, "y": 3, "width": 12, "height": 2},
                    {"text": "Qty", "x": 73, "y": 3, "width": 4, "height": 2},
                    {"text": "Amount", "x": 87, "y": 3, "width": 8, "height": 2},
                    {"text": "1", "x": 3, "y": 10, "width": 2, "height": 2},
                    {"text": "Service", "x": 16, "y": 10, "width": 8, "height": 2},
                    {"text": "fee", "x": 25, "y": 10, "width": 4, "height": 2},
                    {"text": "2", "x": 73, "y": 10, "width": 2, "height": 2},
                    {"text": "1,000", "x": 87, "y": 10, "width": 7, "height": 2},
                    {"text": "including", "x": 16, "y": 14, "width": 9, "height": 2},
                    {"text": "support", "x": 26, "y": 14, "width": 8, "height": 2},
                    {"text": "2", "x": 3, "y": 18, "width": 2, "height": 2},
                    {"text": "License", "x": 16, "y": 18, "width": 8, "height": 2},
                    {"text": "1", "x": 73, "y": 18, "width": 2, "height": 2},
                    {"text": "500", "x": 87, "y": 18, "width": 5, "height": 2},
                    {"text": "Total", "x": 16, "y": 22, "width": 6, "height": 2},
                    {"text": "1,500", "x": 87, "y": 22, "width": 7, "height": 2},
                ],
            }
        },
    )
    values, evidence = anydoc_bbox.extract_fixed_position_fields(
        "/tmp/quotation.pdf",
        [{
            "name": "line_items",
            "type": "array",
            "locator": {"page": 1, "x": 0, "y": 0, "width": 100, "height": 30},
            "array_config": {
                "row_detection": "anchor_column",
                "anchor_column": "line_no",
                "header_rows": 1,
                "columns": [
                    {"name": "line_no", "type": "number", "x": 0, "width": 10},
                    {"name": "description", "type": "text", "x": 10, "width": 60},
                    {"name": "quantity", "type": "number", "x": 70, "width": 15},
                    {"name": "amount", "type": "currency", "x": 85, "width": 15},
                ],
            },
        }],
    )

    assert values["line_items"] == [
        {"line_no": "1", "description": "Service fee including support", "quantity": "2", "amount": "1,000"},
        {"line_no": "2", "description": "License", "quantity": "1", "amount": "500"},
    ]
    assert evidence["line_items"]["cleaned_value"] == values["line_items"]
    assert evidence["line_items"]["row_count"] == 2


def test_bbox_array_keeps_prices_aligned_with_wrapped_descriptions(monkeypatch):
    monkeypatch.setattr(
        anydoc_bbox,
        "build_bbox_layout",
        lambda _path, _pages: {
            1: {
                "source": "text_layer",
                "words": [
                    {"text": "No", "x": 3, "y": 3, "width": 3, "height": 2},
                    {"text": "Description", "x": 16, "y": 3, "width": 12, "height": 2},
                    {"text": "Amount", "x": 87, "y": 3, "width": 8, "height": 2},
                    {"text": "1", "x": 3, "y": 10, "width": 2, "height": 2},
                    {"text": "Managed", "x": 16, "y": 10, "width": 8, "height": 2},
                    {"text": "service", "x": 16, "y": 14, "width": 7, "height": 2},
                    {"text": "1,000", "x": 87, "y": 14, "width": 7, "height": 2},
                    {"text": "2", "x": 3, "y": 18, "width": 2, "height": 2},
                    {"text": "License", "x": 16, "y": 18, "width": 8, "height": 2},
                    {"text": "500", "x": 87, "y": 18, "width": 5, "height": 2},
                    {"text": "Total", "x": 16, "y": 22, "width": 6, "height": 2},
                    {"text": "1,500", "x": 87, "y": 22, "width": 7, "height": 2},
                ],
            }
        },
    )

    values, _ = anydoc_bbox.extract_fixed_position_fields(
        "/tmp/quotation.pdf",
        [{
            "name": "line_items",
            "type": "array",
            "locator": {"page": 1, "x": 0, "y": 0, "width": 100, "height": 30},
            "array_config": {
                "row_detection": "anchor_column",
                "anchor_column": "line_no",
                "header_rows": 1,
                "columns": [
                    {"name": "line_no", "type": "number", "x": 0, "width": 10},
                    {"name": "description", "type": "text", "x": 10, "width": 70},
                    {"name": "amount", "type": "currency", "x": 80, "width": 20},
                ],
            },
        }],
    )

    assert values["line_items"] == [
        {"line_no": "1", "description": "Managed service", "amount": "1,000"},
        {"line_no": "2", "description": "License", "amount": "500"},
    ]


def test_locator_mapping_normalizes_fixed_position_array_columns(monkeypatch):
    schema = SimpleNamespace(
        name="quotation",
        fields=[{
            "name": "line_items",
            "type": "array",
            "locator": {"type": "bbox", "page": 1, "x": 1, "y": 1, "width": 90, "height": 40},
            "array_config": {
                "row_detection": "line",
                "header_rows": 0,
                "columns": [
                    {"name": "line_no", "type": "number", "x": 0, "width": 10},
                    {"name": "description", "type": "text", "x": 10, "width": 70},
                    {"name": "amount", "type": "currency", "x": 80, "width": 20},
                ],
            },
        }],
    )
    monkeypatch.setattr(
        document_tasks,
        "extract_fixed_position_fields",
        lambda *_args, **_kwargs: (
            {"line_items": [{"line_no": "1", "description": "Service", "amount": "1,250.50"}]},
            {"line_items": {"cleaned_value": [{"line_no": "1", "description": "Service", "amount": "1,250.50"}]}},
        ),
    )

    mapped, _, provider = document_tasks.map_schema_fields_with_locators(
        "document text", schema, object(), "/tmp/quotation.pdf"
    )

    assert mapped == {"line_items": [{"line_no": 1.0, "description": "Service", "amount": 1250.5}]}
    assert provider == "bbox"


def test_locator_mapping_treats_bare_dash_currency_cell_as_null(monkeypatch):
    schema = SimpleNamespace(
        name="quotation",
        fields=[{
            "name": "line_items",
            "type": "array",
            "locator": {"type": "bbox", "page": 1, "x": 1, "y": 1, "width": 90, "height": 40},
            "array_config": {
                "row_detection": "line",
                "header_rows": 0,
                "columns": [
                    {"name": "description", "type": "text", "x": 0, "width": 80},
                    {"name": "amount", "type": "currency", "x": 80, "width": 20},
                ],
            },
        }],
    )
    monkeypatch.setattr(
        document_tasks,
        "extract_fixed_position_fields",
        lambda *_args, **_kwargs: (
            {"line_items": [{"description": "Included service", "amount": "-"}]},
            {"line_items": {"cleaned_value": [{"description": "Included service", "amount": "-"}]}},
        ),
    )

    mapped, _, provider = document_tasks.map_schema_fields_with_locators(
        "document text", schema, object(), "/tmp/quotation.pdf"
    )

    assert mapped == {"line_items": [{"description": "Included service", "amount": None}]}
    assert provider == "bbox"


def test_locator_mapping_uses_cleaned_value_and_preserves_raw_evidence(monkeypatch):
    schema = SimpleNamespace(
        name="fixed_form",
        fields=[
            {"name": "company_name", "type": "text", "locator": {"type": "bbox", "page": 1, "x": 1, "y": 1, "width": 20, "height": 10}},
        ],
    )
    monkeypatch.setattr(
        document_tasks,
        "extract_fixed_position_fields",
        lambda *_args, **_kwargs: (
            {"company_name": "................ Softnix Technology"},
            {"company_name": {"raw_text": "................ Softnix Technology", "cleaned_text": "Softnix Technology"}},
        ),
    )

    mapped, evidence, provider = document_tasks.map_schema_fields_with_locators(
        "document text", schema, object(), "/tmp/fixed-form.pdf"
    )

    assert mapped == {"company_name": "Softnix Technology"}
    assert evidence["company_name"]["raw_text"].startswith("...")
    assert provider == "bbox"


def test_locator_mapping_does_not_call_structured_provider_when_all_fields_are_fixed(monkeypatch):
    schema = SimpleNamespace(
        name="fixed_form",
        fields=[
            {"name": "document_number", "type": "text", "required": True, "locator": {"type": "bbox", "page": 1, "x": 1, "y": 1, "width": 20, "height": 10}},
            {"name": "total_amount", "type": "currency", "locator": {"type": "bbox", "page": 1, "x": 70, "y": 80, "width": 20, "height": 10}},
        ],
    )
    monkeypatch.setattr(
        document_tasks,
        "extract_fixed_position_fields",
        lambda *_args, **_kwargs: (
            {"document_number": "PND-1", "total_amount": "1,250.50"},
            {"document_number": {"page": 1}, "total_amount": {"page": 1}},
        ),
    )
    monkeypatch.setattr(
        document_tasks,
        "extract_structure",
        lambda *_args, **_kwargs: pytest.fail("Structured provider must not run"),
    )

    mapped, evidence, provider = document_tasks.map_schema_fields_with_locators(
        "document text", schema, object(), "/tmp/fixed-form.pdf"
    )

    assert mapped == {"document_number": "PND-1", "total_amount": 1250.5}
    assert evidence["document_number"]["page"] == 1
    assert provider == "bbox"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("31/03/2569", "2026-03-31"),
        ("วันที่ ๓๑ มีนาคม ๒๕๖๙", "2026-03-31"),
        ("31 March 2026", "2026-03-31"),
    ],
)
def test_fixed_position_dates_support_thai_buddhist_era(value, expected):
    field = {"type": "string", "format": "date"}

    assert document_tasks._normalise_fixed_position_value(value, field, "document_date") == expected


def test_partial_mapping_keeps_fixed_position_values(monkeypatch):
    schema = SimpleNamespace(
        name="mixed_form",
        fields=[
            {"name": "document_number", "type": "text", "required": True, "locator": {"type": "bbox", "page": 1, "x": 1, "y": 1, "width": 20, "height": 10}},
            {"name": "notes", "type": "text", "required": False},
        ],
    )
    document = SimpleNamespace(filename="fixed.pdf", ocr_text="document text", extracted_data=None)
    monkeypatch.setattr(
        document_tasks,
        "extract_fixed_position_fields",
        lambda *_args, **_kwargs: ({"document_number": "PND-1"}, {"document_number": {"page": 1}}),
    )
    monkeypatch.setattr(document_tasks, "extract_structure", lambda *_args, **_kwargs: None)

    metadata = {}
    error = document_tasks.apply_schema_mapping(document, schema, object(), metadata, "/tmp/fixed-form.pdf")

    assert error == "Structured output must be a JSON object"
    assert document.extracted_data == {"document_number": "PND-1"}
    assert metadata["mapping"]["status"] == "partial"
    assert metadata["field_evidence"]["document_number"]["page"] == 1


def test_failed_pdf_render_removes_temporary_directory(monkeypatch, tmp_path):
    render_directory = tmp_path / "render"
    render_directory.mkdir()
    monkeypatch.setattr(anydoc_bbox.tempfile, "mkdtemp", lambda **_kwargs: str(render_directory))
    monkeypatch.setattr(
        anydoc_bbox.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr="failed"),
    )

    with pytest.raises(anydoc_bbox.BboxLocatorError, match="Unable to render"):
        anydoc_bbox._render_pdf_page("/tmp/form.pdf", 1)

    assert not Path(render_directory).exists()
