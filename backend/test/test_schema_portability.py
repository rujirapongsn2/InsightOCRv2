from types import SimpleNamespace
from uuid import UUID

import pytest

from app.api.v1.endpoints.schemas import (
    SCHEMA_PACKAGE_FORMAT,
    SCHEMA_PACKAGE_VERSION,
    _extract_import_records,
    _normalize_import_schema,
    _schema_export_record,
    _schema_id_keys,
)


def test_schema_package_preserves_bbox_and_table_array_configuration():
    record = _normalize_import_schema({
        "name": "Quotation table",
        "description": "Portable quotation schema",
        "document_type": "invoice",
        "extraction_profile": "anydoc_hybrid",
        "fields": [{
            "name": "items",
            "type": "array",
            "required": True,
            "description": "Line items",
            "locator": {"type": "bbox", "page": 1, "x": 10, "y": 20, "width": 80, "height": 30},
            "array_config": {
                "item_type": "object",
                "row_detection": "anchor_column",
                "anchor_column": "line_no",
                "header_rows": 1,
                "columns": [{"name": "line_no", "type": "number", "x": 0, "width": 20}],
            },
            "help_text": "Keep table rows",
            "id": "local-ui-key",
        }],
    })

    field = record["fields"][0]
    assert field["locator"]["page"] == 1
    assert field["array_config"]["anchor_column"] == "line_no"
    assert field["help_text"] == "Keep table rows"
    assert "id" not in field


def test_schema_export_record_excludes_database_identity():
    exported = _schema_export_record(SimpleNamespace(
        id="internal-id",
        name="Invoice",
        description="desc",
        document_type="invoice",
        ocr_engine="tesseract",
        extraction_profile=None,
        fields=[{"name": "number", "type": "text"}],
        created_by="owner-id",
    ))

    assert exported["name"] == "Invoice"
    assert exported["extraction_profile"] == "anydoc_hybrid"
    assert "id" not in exported
    assert "created_by" not in exported


def test_export_request_uuid_values_match_string_lookup_keys():
    schema_id = UUID("11111111-1111-1111-1111-111111111111")

    assert _schema_id_keys([schema_id]) == ["11111111-1111-1111-1111-111111111111"]


def test_import_requires_supported_package_envelope():
    package = {
        "format": SCHEMA_PACKAGE_FORMAT,
        "version": SCHEMA_PACKAGE_VERSION,
        "schemas": [{"name": "Invoice", "document_type": "invoice", "fields": []}],
    }

    assert _extract_import_records(package) == package["schemas"]

    with pytest.raises(ValueError, match="Unsupported schema package format"):
        _extract_import_records({"format": "other", "version": 1, "schemas": []})

    with pytest.raises(ValueError, match="Unsupported schema package version"):
        _extract_import_records({"format": SCHEMA_PACKAGE_FORMAT, "version": 2, "schemas": []})


def test_import_rejects_blank_schema_name():
    with pytest.raises(ValueError, match="Schema name cannot be empty"):
        _normalize_import_schema({
            "name": "   ",
            "document_type": "invoice",
            "fields": [],
        })
