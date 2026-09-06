import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.agent.context import AgentContext, build_system_prompt, tool_content_for_llm
from app.agent.loop import AgentLoop
from app.agent.tools.filesystem_tools import _extract_rows_for_xlsx
from app.agent.tools.document_tools import (
    _get_document_detail_handler, _search_documents_handler,
    _compare_documents_handler,
)


def document(**kwargs):
    values = dict(id="doc", filename="contract.pdf", status="reviewed", page_count=2,
                  ocr_text="", extracted_data=None, reviewed_data=None,
                  extraction_confidence=1, review_decision="approved")
    return SimpleNamespace(**(values | kwargs))


def context(docs):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = docs
    db.query.return_value.filter.return_value.all.return_value = docs
    return AgentContext(db, "user", "job", "conversation")


@pytest.mark.asyncio
async def test_full_text_can_be_reconstructed_without_silent_truncation():
    doc = document(ocr_text="a" * 9000 + "FINAL CLAUSE")
    ctx = context([doc] * 4)
    parts, offset = [], 0
    while offset is not None:
        result = await _get_document_detail_handler({"doc_id": "doc", "offset": offset}, ctx)
        parts.append(result["ocr_text"])
        offset = result["next_offset"]
    assert "".join(parts) == doc.ocr_text
    assert result["text_range"]["end"] == len(doc.ocr_text)


@pytest.mark.asyncio
async def test_large_structured_data_is_recoverable_and_model_payload_bounded():
    data = [{"item": "Thai text " * 100, "amount": i} for i in range(40)]
    doc = document(ocr_text="a" * 20000, reviewed_data=data)
    ctx = context([doc] * 50)
    parts, offset = [], 0
    while offset is not None:
        result = await _get_document_detail_handler({"doc_id": "doc", "data_offset": offset}, ctx)
        assert "truncated" not in tool_content_for_llm(result)
        parts.append(result["structured_data_json_excerpt"])
        offset = result["next_data_offset"]
    assert json.loads("".join(parts)) == data


@pytest.mark.asyncio
async def test_search_finds_wrapped_query_and_late_match():
    doc = document(ocr_text="x" * 10000 + " Article\n28 transfers")
    result = await _search_documents_handler({"query": "Article 28"}, context([doc]))
    assert result["count"] == 1
    assert "Article 28" in result["documents"][0]["snippets"][0]


@pytest.mark.asyncio
async def test_search_pages_and_reviewed_values():
    docs = [document(id=str(i), reviewed_data={"name": "corrected"}) for i in range(12)]
    result = await _search_documents_handler({"query": "corrected", "offset": 10}, context(docs))
    assert result["count"] == 12
    assert len(result["documents"]) == 2
    assert result["next_offset"] is None


@pytest.mark.asyncio
async def test_empty_diff_does_not_claim_text_equivalence():
    result = await _compare_documents_handler(
        {"doc_id_1": "a", "doc_id_2": "b"},
        context([document(ocr_text="old"), document(ocr_text="new")]),
    )
    assert result["differences"] == {}
    assert result["ocr_text_equal"] is False
    assert result["comparison_scope"] == "structured_fields_only"


@pytest.mark.asyncio
async def test_history_discards_orphan_and_incomplete_tool_batches():
    messages = [
        SimpleNamespace(role="tool", tool_call_id="orphan", tool_result={}),
        SimpleNamespace(role="assistant", content=None, tool_calls=[{"id": "a"}, {"id": "b"}]),
        SimpleNamespace(role="tool", tool_call_id="a", tool_result={}),
        SimpleNamespace(role="user", content="continue"),
    ]
    with patch("app.agent.context.crud_conv.get_messages", return_value=messages):
        assert await context([]).load_history() == [{"role": "user", "content": "continue"}]


@pytest.mark.asyncio
async def test_runtime_limit_interrupts_silent_provider_and_closes_iterator():
    closed = []

    async def stalled(_):
        try:
            await asyncio.sleep(10)
            yield "never"
        finally:
            closed.append(True)

    loop = object.__new__(AgentLoop)
    loop._run_inner = stalled
    with patch("app.agent.loop.AGENT_MAX_RUNTIME_S", 0.02):
        events = [event async for event in loop.run("summarize")]
    assert closed == [True]
    assert len(events) == 1
    assert "runtime limit" in events[0]


def test_bad_pdf_conversion_does_not_create_successful_error_spreadsheet():
    with pytest.raises(ValueError, match="PDF text extraction failed"):
        _extract_rows_for_xlsx("report.pdf", b"%PDF-broken")


def test_scanned_pdf_requires_ocr_instead_of_empty_workbook():
    with patch("pypdf.PdfReader") as reader:
        reader.return_value.pages = [SimpleNamespace(extract_text=lambda: "")]
        with pytest.raises(ValueError, match="OCR is required"):
            _extract_rows_for_xlsx("scan.pdf", b"%PDF")


def test_system_prompt_keeps_processing_layers_internal_and_focuses_on_user_intent():
    ctx = context([])
    with (
        patch.object(ctx, "recall_relevant_memories", return_value=[]),
        patch.object(ctx, "list_relevant_skills", return_value=[]),
    ):
        prompt = build_system_prompt(ctx, "เอกสารสองฉบับนี้มีประเด็นสำคัญอะไรบ้าง")

    assert "Evidence Hierarchy (Internal Reasoning Only)" in prompt
    assert "Never expose implementation or storage vocabulary" in prompt
    assert "Organize the answer around the user's intent and business meaning" in prompt
    assert "**[ควรตรวจสอบ]**" in prompt
    assert "Keep this strong source attribution behavior" in prompt
