"""
Unit tests for execute_python tool handler.

Run: cd backend && python -m pytest test/agent/test_code_tools.py -v
"""
import uuid
import base64
from unittest.mock import MagicMock, patch

import pytest

from app.agent.context import AgentContext
from app.agent.tools.code_tools import _create_pdf_handler, _execute_python_handler, _run_report_code_handler, _normalize_report_path

pytestmark = pytest.mark.asyncio


def _make_context():
    db = MagicMock()
    return AgentContext(db=db, user_id=uuid.uuid4(), job_id=uuid.uuid4(), conversation_id=uuid.uuid4())


class TestExecutePython:
    async def test_execute_success(self):
        ctx = _make_context()
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec:
            mock_exec.return_value = {"result": 42, "error": None}
            result = await _execute_python_handler(
                {"code": "result = sum(inputs['nums'])", "inputs": {"nums": [1, 2, 3]}},
                ctx,
            )
        assert result["result"] == 42
        mock_exec.assert_called_once()
        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["code"] == "result = sum(inputs['nums'])"
        assert call_kwargs["inputs"] == {"nums": [1, 2, 3]}

    async def test_execute_with_error(self):
        ctx = _make_context()
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec:
            mock_exec.return_value = {"result": None, "error": {"type": "ValueError", "message": "bad value"}}
            result = await _execute_python_handler(
                {"code": "raise ValueError('bad value')"},
                ctx,
            )
        assert result["error"] is not None

    async def test_empty_code_rejected(self):
        ctx = _make_context()
        result = await _execute_python_handler({"code": ""}, ctx)
        assert "error" in result

    async def test_whitespace_only_code_rejected(self):
        ctx = _make_context()
        result = await _execute_python_handler({"code": "   \n  \t "}, ctx)
        assert "error" in result

    async def test_code_too_long_rejected(self):
        ctx = _make_context()
        result = await _execute_python_handler({"code": "x" * 100_001}, ctx)
        assert "error" in result

    async def test_code_under_limit_accepted(self):
        ctx = _make_context()
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec:
            mock_exec.return_value = {"result": "ok", "error": None}
            result = await _execute_python_handler({"code": "x" * 100_000}, ctx)
        assert result["result"] == "ok"

    async def test_inputs_must_be_dict(self):
        ctx = _make_context()
        result = await _execute_python_handler({"code": "pass", "inputs": "not_a_dict"}, ctx)
        assert "error" in result

    async def test_default_inputs_empty_dict(self):
        ctx = _make_context()
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec:
            mock_exec.return_value = {"result": None, "error": None}
            await _execute_python_handler({"code": "pass"}, ctx)
        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["inputs"] == {}

    async def test_sandbox_unavailable_graceful(self):
        ctx = _make_context()
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec:
            mock_exec.return_value = {"error": "Sandbox unavailable: docker package not installed"}
            result = await _execute_python_handler({"code": "pass"}, ctx)
        assert "error" in result

    async def test_execute_auto_persists_generated_file(self):
        ctx = _make_context()
        pdf = b"%PDF-1.4\n% test\n"
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec, \
             patch("app.agent.tools.code_tools.get_storage_service") as mock_storage, \
             patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_verify_storage:
            mock_exec.return_value = {
                "result": {"path": "/tmp/test.pdf"},
                "error": None,
                "files": [{
                    "filename": "test.pdf",
                    "path": "/tmp/test.pdf",
                    "mime_type": "application/pdf",
                    "base64": base64.b64encode(pdf).decode("ascii"),
                    "size": len(pdf),
                    "auto_captured": True,
                }],
            }
            svc = mock_storage.return_value
            mock_verify_storage.return_value = svc
            svc.exists.return_value = True
            svc.get_local_path.return_value.__enter__.return_value = "/tmp/test.pdf"
            with patch("pathlib.Path.stat") as mock_stat, \
                 patch("pathlib.Path.read_bytes", return_value=pdf):
                mock_stat.return_value.st_size = len(pdf)
                result = await _execute_python_handler({"code": "result = {'path': '/tmp/test.pdf'}"}, ctx)

        assert result["ok"] is True
        assert result["path"] == "outputs/test.pdf"
        assert result["verified"] is True
        assert result["saved_files"][0]["auto_captured"] is True
        svc.upload_file.assert_called_once()


class TestCreatePdf:
    async def test_create_pdf_persists_verified_file(self):
        ctx = _make_context()
        pdf = b"%PDF-1.4\n% test pdf\n"
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec, \
             patch("app.agent.tools.code_tools.get_storage_service") as mock_storage, \
             patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_verify_storage:
            mock_exec.return_value = {
                "result": {"path": "/tmp/risk_report.pdf"},
                "error": None,
                "files": [{
                    "filename": "risk_report.pdf",
                    "path": "/tmp/risk_report.pdf",
                    "mime_type": "application/pdf",
                    "base64": base64.b64encode(pdf).decode("ascii"),
                    "size": len(pdf),
                }],
            }
            svc = mock_storage.return_value
            mock_verify_storage.return_value = svc
            svc.exists.return_value = True
            svc.get_local_path.return_value.__enter__.return_value = "/tmp/risk_report.pdf"
            with patch("pathlib.Path.stat") as mock_stat, \
                 patch("pathlib.Path.read_bytes", return_value=pdf):
                mock_stat.return_value.st_size = len(pdf)
                result = await _create_pdf_handler(
                    {"content": "ตารางความเสี่ยง", "output_path": "outputs/risk_report.pdf"},
                    ctx,
                )

        assert result["ok"] is True
        assert result["path"] == "outputs/risk_report.pdf"
        assert result["verified"] is True
        assert result["mime_type"] == "application/pdf"
        mock_exec.assert_called_once()
        assert mock_exec.call_args.kwargs["allow_network"] is False


class TestRunReportCode:
    async def test_normalize_report_path(self):
        assert _normalize_report_path("report") == "outputs/report.html"
        assert _normalize_report_path("jobs/job-1/outputs/a.html") == "outputs/a.html"
        assert _normalize_report_path("outputs/a") == "outputs/a.html"
        assert _normalize_report_path("../a.html") == ""
        assert _normalize_report_path("tmp/a.html") == ""

    async def test_syntax_error_rejected_before_sandbox(self):
        ctx = _make_context()
        result = await _run_report_code_handler(
            {"code": "if True print('bad')", "inputs": {}, "output_path": "outputs/report.html"},
            ctx,
        )
        assert result["error"] == "Syntax check failed"

    async def test_inputs_must_be_dict(self):
        ctx = _make_context()
        result = await _run_report_code_handler(
            {"code": "result = {}", "inputs": [], "output_path": "outputs/report.html"},
            ctx,
        )
        assert "inputs must be a dict" in result["error"]

    async def test_execution_error_returned(self):
        ctx = _make_context()
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec:
            mock_exec.return_value = {"error": {"type": "NameError", "message": "name docs is not defined"}, "stdout": "trace"}
            result = await _run_report_code_handler(
                {"code": "result = docs", "inputs": {"documents": []}, "output_path": "outputs/report.html"},
                ctx,
            )
        assert result["error"] == "Report code execution failed"
        assert result["execution_error"]["type"] == "NameError"

    async def test_invalid_result_rejected(self):
        ctx = _make_context()
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec:
            mock_exec.return_value = {"result": {"ok": True, "html": "not html"}, "error": None}
            result = await _run_report_code_handler(
                {"code": "result = {'ok': True, 'html': 'not html'}", "inputs": {}, "output_path": "outputs/report.html"},
                ctx,
            )
        assert result["error"] == "Report result validation failed"

    async def test_success_writes_html(self):
        ctx = _make_context()
        html = "<!doctype html><html><body>ok</body></html>"
        with patch("app.agent.tools.code_tools.execute_python") as mock_exec, \
             patch("app.agent.tools.code_tools.get_storage_service") as mock_storage:
            mock_exec.return_value = {
                "result": {"ok": True, "html": html, "summary": {"status": "ok"}, "rules": [{"id": "R1"}]},
                "error": None,
            }
            result = await _run_report_code_handler(
                {"code": "result = {'ok': True, 'html': '<html></html>'}", "inputs": {}, "output_path": "jobs/abc/outputs/report.html"},
                ctx,
            )
        assert result["ok"] is True
        assert result["path"] == "outputs/report.html"
        assert result["rule_count"] == 1
        mock_storage.return_value.upload_file.assert_called_once()
        assert mock_storage.return_value.upload_file.call_args.kwargs["content_type"] == "text/html; charset=utf-8"
