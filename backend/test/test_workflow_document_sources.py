from types import SimpleNamespace

from app.services.ingestion import resolve_ingestion_schema_id
from app.services.workflow_engine import (
    NODE_TYPES,
    _workflow_document_extraction,
    _workflow_document_status,
)


def _node_type(name):
    return next(node for node in NODE_TYPES if node["type"] == name)


def test_document_source_defaults_to_completed_documents_and_hides_retired_status():
    fields = {field["name"]: field for field in _node_type("document_source")["config_fields"]}

    assert fields["only_completed"]["default"] is True
    assert "ocr_completed" not in fields["status"]["options"]
    assert _workflow_document_status("ocr_completed") == "extraction_completed"


def test_onedrive_import_offers_the_same_schema_override_as_google_drive():
    for node_name in ("gdrive_import", "onedrive_import"):
        field_names = {field["name"] for field in _node_type(node_name)["config_fields"]}
        assert "schema_id" in field_names
        assert "auto_review" in field_names
        assert "wait_for_completion" in field_names
        auto_review_field = next(f for f in _node_type(node_name)["config_fields"] if f["name"] == "auto_review")
        assert auto_review_field["type"] == "boolean"
        assert auto_review_field["default"] is False
        wait_field = next(f for f in _node_type(node_name)["config_fields"] if f["name"] == "wait_for_completion")
        assert wait_field["type"] == "boolean"
        assert wait_field["default"] is True
        output_names = {f["name"] for f in _node_type(node_name)["output_fields"]}
        assert "records" in output_names
        assert "documents" in output_names


def test_ingestion_inherits_job_schema_unless_workflow_selects_an_override():
    job = SimpleNamespace(schema_id="job-schema")

    assert resolve_ingestion_schema_id(job, None) == "job-schema"
    assert resolve_ingestion_schema_id(job, "") == "job-schema"
    assert resolve_ingestion_schema_id(job, "auto") == "job-schema"
    assert resolve_ingestion_schema_id(job, "node-schema") == "node-schema"
    assert resolve_ingestion_schema_id(SimpleNamespace(schema_id=None), None) is None
    assert resolve_ingestion_schema_id(SimpleNamespace(schema_id=None), "auto") is None


def test_workflow_document_extraction_exposes_compact_provenance_only():
    document = SimpleNamespace(
        extraction_metadata={
            "pipeline": "anydoc_hybrid",
            "source": "image",
            "provider_counts": {"tesseract_ocr": 1},
            "text_layer_pages": [],
            "ocr_pages": [1],
            "mapping": {
                "status": "failed",
                "schema": "Invoice",
                "provider": "structured_output",
                "reason": "provider response body",
            },
            "legacy_fallback": {"reason": "parser error"},
        }
    )

    output = _workflow_document_extraction(document)

    assert output == {
        "pipeline": "anydoc_hybrid",
        "source": "image",
        "provider_counts": {"tesseract_ocr": 1},
        "text_layer_pages": [],
        "ocr_pages": [1],
        "mapping": {"status": "failed", "schema": "Invoice", "provider": "structured_output"},
        "legacy_fallback": True,
    }
