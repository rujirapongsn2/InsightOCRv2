import uuid
from unittest.mock import MagicMock, patch

from app.agent.context import AgentContext
from app.agent.loop import (
    _file_success_final_text,
    _claims_file_success,
    _is_file_write_success,
    _is_xlsx_conversion_request,
    _sanitize_unverified_file_claims,
    _verify_file_tool_result,
)


def _make_context():
    return AgentContext(
        db=MagicMock(),
        user_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
    )


def test_file_success_requires_verified_flag():
    assert _is_file_write_success("write_file", {"ok": True, "path": "outputs/a.xlsx"}) is False
    assert _is_file_write_success("write_file", {"ok": True, "path": "outputs/a.xlsx", "verified": True}) is True
    assert _is_file_write_success("convert_to_xlsx", {"ok": True, "path": "outputs/a.xlsx", "verified": True}) is True


def test_detects_thai_excel_conversion_request():
    assert _is_xlsx_conversion_request("ช่วยแปลงเป็น excel") is True
    assert _is_xlsx_conversion_request("ช่วยทำรายงาน excel ใหม่") is False


def test_success_final_text_prefers_verified_file_over_old_errors():
    text = _file_success_final_text(
        {
            "path": "outputs/summary.xlsx",
            "source_path": "outputs/summary.docx",
            "verified": True,
        },
        "ช่วยแปลงเป็น excel",
    )
    assert "outputs/summary.xlsx" in text
    assert "ตรวจสอบไฟล์แล้ว" in text


def test_sanitize_unverified_file_claims_preserves_table_body():
    text = (
        "ไฟล์ `outputs/risk.md` มีอยู่แล้วในระบบครับ\n\n"
        "| มิติ | Trend |\n|---|---|\n| Legal | สูงขึ้น |\n\n"
        "ต้องการให้ผมแปลงเป็น Excel (.xlsx) ให้พร้อมดาวน์โหลดไหมครับ"
    )
    sanitized = _sanitize_unverified_file_claims(text)
    assert "outputs/risk.md" not in sanitized
    assert "ดาวน์โหลด" not in sanitized
    assert "| Legal | สูงขึ้น |" in sanitized


def test_source_pdf_mention_is_not_file_success_claim():
    assert _claims_file_success("Report generated from Contract_V1.pdf and Contract_V2.pdf") is False
    assert _claims_file_success("ไฟล์ถูกสร้างแล้ว: outputs/report.md") is True


def test_verify_file_tool_result_marks_success_verified():
    ctx = _make_context()
    with patch("app.agent.loop.filesystem_tools.verify_saved_file") as verify:
        verify.return_value = {
            "ok": True,
            "path": "outputs/a.xlsx",
            "size": 123,
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        result = _verify_file_tool_result(ctx, "write_file", {"ok": True, "path": "outputs/a.xlsx", "size": 123})

    assert result["ok"] is True
    assert result["verified"] is True
    assert result["verified_size"] == 123
    assert _is_file_write_success("write_file", result) is True


def test_verify_file_tool_result_turns_missing_file_into_failure():
    ctx = _make_context()
    with patch("app.agent.loop.filesystem_tools.verify_saved_file") as verify:
        verify.return_value = {"ok": False, "error": "File verification failed: not found"}
        result = _verify_file_tool_result(ctx, "write_file", {"ok": True, "path": "outputs/a.xlsx", "size": 123})

    assert result["ok"] is False
    assert result["verified"] is False
    assert "not found" in result["error"]
    assert _is_file_write_success("write_file", result) is False
