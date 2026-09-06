import pytest

from app.services.ocr_result import extract_ocr_text, validate_ocr_result


def test_markdown_precedes_raw_text_without_duplicating_pages():
    page = {"ocr_text": "RAW", "ai_processing": {"success": True, "content": "# Page"}}
    assert extract_ocr_text({"results": {"pages": [page, page]}}) == "# Page\n\n# Page"


def test_failed_ai_uses_raw_text_and_aggregate_markdown_is_supported():
    assert extract_ocr_text({"pages": [{
        "ocr_text": "raw", "ai_processing": {"success": False, "content": "error text"},
    }]}) == "raw"
    assert extract_ocr_text({"results": {"combined_markdown": "# Page"}}) == "# Page"


def test_partial_page_failures_cannot_be_marked_complete():
    with pytest.raises(ValueError, match="incomplete"):
        validate_ocr_result({"results": {"failed_pages": [2], "pages": [{"ocr_text": "page 1"}]}})


def test_structured_output_is_not_used_as_document_text():
    with pytest.raises(ValueError, match="no readable text"):
        validate_ocr_result({"status": "success", "results": {"structured_output": {"data": {"total": 50}}}})
