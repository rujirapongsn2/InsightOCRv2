from types import SimpleNamespace

import pytest

from app.api.v1.endpoints.schemas import _schema_update_values
from app.api.v1.endpoints.documents import _validate_requested_extraction_profile
from app.services.extraction_profiles import supports_anydoc_source, validate_extraction_profile
from app.schemas.schema import DocumentSchemaUpdate, SchemaField


def test_schema_update_keeps_anydoc_profile_and_normalizes_fields():
    existing = SimpleNamespace(document_type="invoice", extraction_profile="legacy")
    update = DocumentSchemaUpdate(
        name="Thai_PackingList",
        document_type="invoice",
        extraction_profile="anydoc_hybrid",
        fields=[SchemaField(name="invoice_number", type="text")],
    )

    values = _schema_update_values(update, existing)

    assert values["extraction_profile"] == "anydoc_hybrid"
    assert values["fields"] == [{"name": "invoice_number", "type": "text"}]


def test_schema_update_defaults_missing_profile_to_standard_extraction():
    existing = SimpleNamespace(document_type="invoice", extraction_profile=None)
    update = DocumentSchemaUpdate(name="Thai_PackingList")

    values = _schema_update_values(update, existing)

    assert values["extraction_profile"] == "anydoc_hybrid"
    assert "document_type" not in values


def test_supported_documents_default_to_standard_extraction():
    invoice_schema = SimpleNamespace(document_type="invoice")
    pdf_document = SimpleNamespace(filename="receipt.pdf", mime_type="application/pdf")

    assert _validate_requested_extraction_profile(invoice_schema, None, pdf_document) == "anydoc_hybrid"
    assert _validate_requested_extraction_profile(None, "legacy", pdf_document) == "anydoc_hybrid"
    assert _validate_requested_extraction_profile(None, "anydoc_hybrid", pdf_document) == "anydoc_hybrid"


def test_anydoc_pipeline_allows_supported_image_documents():
    invoice_schema = SimpleNamespace(document_type="invoice")
    image_document = SimpleNamespace(filename="scan.png", mime_type="image/png")

    assert _validate_requested_extraction_profile(
        invoice_schema,
        "anydoc_hybrid",
        image_document,
    ) == "anydoc_hybrid"


def test_anydoc_source_support_is_shared_for_image_extensions_and_mime_types():
    assert supports_anydoc_source("scan.tif", None)
    assert supports_anydoc_source("receipt", "image/webp")
    assert not supports_anydoc_source("receipt.heic", "image/heic")


def test_unsupported_sources_use_internal_legacy_compatibility_route():
    office_document = SimpleNamespace(
        filename="packing-list.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert _validate_requested_extraction_profile(None, None, office_document) == "legacy"


def test_shadow_profile_is_rejected_after_standardization():
    with pytest.raises(ValueError, match="Unsupported extraction profile"):
        validate_extraction_profile("invoice", "anydoc_shadow")
