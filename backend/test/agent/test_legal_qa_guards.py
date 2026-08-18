import uuid
from unittest.mock import MagicMock

import pytest

from app.agent.context import is_focused_legal_qa
from app.agent.tools.document_tools import _search_documents_handler, normalize_search_text

def _document(*, filename: str, ocr_text: str = "", extracted_data=None):
    document = MagicMock()
    document.id = uuid.uuid4()
    document.filename = filename
    document.ocr_text = ocr_text
    document.extracted_data = extracted_data
    document.status = "extraction_completed"
    return document


def _context(documents):
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = documents
    context = MagicMock()
    context.db = db
    context.job_id = uuid.uuid4()
    return context


def test_normalize_search_text_translates_thai_digits_and_spacing():
    assert normalize_search_text("มาตรา ๒๘") == "มาตรา 28"
    assert normalize_search_text("  SECTION\u00a028  ") == "section 28"


@pytest.mark.asyncio
async def test_search_documents_matches_thai_and_arabic_digits_with_evidence():
    doc = _document(
        filename="pdpa.pdf",
        ocr_text="มาตรา ๒๘ การส่งหรือโอนข้อมูลส่วนบุคคลไปยังต่างประเทศ",
    )

    result = await _search_documents_handler({"query": "มาตรา 28"}, _context([doc]))

    assert result["count"] == 1
    assert result["documents"][0]["filename"] == "pdpa.pdf"
    assert result["documents"][0]["snippets"] == [
        "มาตรา ๒๘ การส่งหรือโอนข้อมูลส่วนบุคคลไปยังต่างประเทศ"
    ]


@pytest.mark.asyncio
async def test_search_documents_returns_empty_for_unmatched_query():
    doc = _document(filename="pdpa.pdf", ocr_text="มาตรา 39 ผู้ควบคุมข้อมูล")

    result = await _search_documents_handler({"query": "มาตรา 40"}, _context([doc]))

    assert result["count"] == 0


@pytest.mark.parametrize(
    "query",
    [
        "หน้าที่ของ DPO ตามกฎหมายคืออะไร",
        "PDPA มาตรา 28 มีข้อกำหนดอย่างไร",
        "What is the legal duty under Article 39?",
    ],
)
def test_focused_legal_qa_detects_read_only_questions(query):
    assert is_focused_legal_qa(query) is True


def test_focused_legal_qa_allows_explicit_report_requests():
    assert is_focused_legal_qa("สร้างรายงานสรุปกฎหมายมาตรา 28 เป็น PDF") is False
