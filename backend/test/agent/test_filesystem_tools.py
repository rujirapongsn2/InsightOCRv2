"""
Unit tests for filesystem tools (read_file, write_file, list_files, delete_file).

Run: cd backend && python -m pytest test/agent/test_filesystem_tools.py -v
"""
import uuid
import base64
import io
import zipfile
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agent.context import AgentContext
from app.agent.tools.filesystem_tools import (
    _read_file_handler,
    _write_file_handler,
    _convert_to_xlsx_handler,
    _build_docx_bytes,
    _build_html_document,
    _list_files_handler,
    _delete_file_handler,
    _resolve_path,
    verify_saved_file,
    ALLOWED_EXTENSIONS,
)

pytestmark = pytest.mark.asyncio


def _persist_uploads(mock_storage):
    files = {}
    storage = mock_storage.return_value

    def upload(file_obj, path, **kwargs):
        files[path] = file_obj.read()

    @contextmanager
    def local_path(path):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / "artifact"
            local.write_bytes(files[path])
            yield str(local)

    storage.upload_file.side_effect = upload
    storage.exists.side_effect = lambda path: path in files
    storage.get_local_path.side_effect = local_path


def _make_context(user_id=None, job_id=None):
    db = MagicMock()
    return AgentContext(
        db=db,
        user_id=user_id or uuid.uuid4(),
        job_id=job_id or uuid.uuid4(),
        conversation_id=uuid.uuid4(),
    )


def _minimal_xlsx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as workbook:
        workbook.writestr("[Content_Types].xml", "<Types/>")
        workbook.writestr("xl/workbook.xml", "<workbook/>")
        workbook.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    return buffer.getvalue()


# ── Path Resolution ──────────────────────────────────────────────────────────

class TestResolvePath:
    def test_basic_scoping(self):
        result = _resolve_path("abc-123", "outputs/report.txt")
        assert result == "jobs/abc-123/outputs/report.txt"

    def test_strips_leading_slash(self):
        result = _resolve_path("abc-123", "/outputs/data.csv")
        assert result == "jobs/abc-123/outputs/data.csv"

    def test_accepts_current_job_scoped_path_without_double_scoping(self):
        result = _resolve_path("abc-123", "jobs/abc-123/outputs/report.txt")
        assert result == "jobs/abc-123/outputs/report.txt"

    def test_blocks_other_job_scoped_path(self):
        with pytest.raises(ValueError, match="Cross-job"):
            _resolve_path("abc-123", "jobs/other-job/outputs/report.txt")

    def test_blocks_path_traversal(self):
        with pytest.raises(ValueError, match="Path traversal"):
            _resolve_path("abc-123", "../../../etc/passwd")

    def test_blocks_double_dot_in_middle(self):
        with pytest.raises(ValueError, match="Path traversal"):
            _resolve_path("abc-123", "outputs/../secrets.env")


# ── read_file ────────────────────────────────────────────────────────────────

class TestReadFile:
    async def test_read_empty_path_rejected(self):
        ctx = _make_context()
        result = await _read_file_handler({"path": "  "}, ctx)
        assert "error" in result

    async def test_read_path_traversal_blocked(self):
        ctx = _make_context()
        result = await _read_file_handler({"path": "../../../etc/passwd"}, ctx)
        assert "error" in result

    async def test_read_file_not_found(self):
        ctx = _make_context()
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            mock_storage.return_value.exists.return_value = False
            result = await _read_file_handler({"path": "outputs/missing.txt"}, ctx)
        assert "error" in result

    async def test_read_success(self):
        ctx = _make_context()
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            svc = mock_storage.return_value
            svc.exists.return_value = True
            svc.get_local_path.return_value.__enter__.return_value = "/tmp/fake.txt"

            with patch("pathlib.Path.stat") as mock_stat, \
                 patch("pathlib.Path.read_text", return_value="hello world"):
                mock_stat.return_value.st_size = 11
                result = await _read_file_handler({"path": "outputs/hello.txt"}, ctx)

        assert result["content"] == "hello world"
        assert result["binary"] is False

    async def test_read_binary_base64_success(self):
        ctx = _make_context()
        data = _minimal_xlsx_bytes()
        fake_path = "/tmp/fake.xlsx"
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            svc = mock_storage.return_value
            svc.exists.return_value = True
            svc.get_local_path.return_value.__enter__.return_value = fake_path

            with patch("pathlib.Path.stat") as mock_stat, \
                 patch("pathlib.Path.read_bytes", return_value=data):
                mock_stat.return_value.st_size = len(data)
                result = await _read_file_handler({"path": "outputs/fake.xlsx", "return_base64": True}, ctx)

        assert result["binary"] is True
        assert result["mime_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert base64.b64decode(result["content_base64"]) == data


# ── write_file ────────────────────────────────────────────────────────────────

class TestWriteFile:
    async def test_write_empty_path_rejected(self):
        ctx = _make_context()
        result = await _write_file_handler({"path": "  ", "content": "data"}, ctx)
        assert "error" in result

    async def test_write_empty_content_rejected(self):
        ctx = _make_context()
        result = await _write_file_handler({"path": "report.txt", "content": ""}, ctx)
        assert "error" in result

    async def test_write_auto_scopes_to_outputs(self):
        ctx = _make_context()
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            _persist_uploads(mock_storage)
            result = await _write_file_handler({"path": "report.txt", "content": "data"}, ctx)
        assert result["ok"] is True
        assert result["path"] == "outputs/report.txt"
        mock_storage.return_value.upload_file.assert_called_once()
        assert mock_storage.return_value.upload_file.call_args.args[1] == f"jobs/{ctx.job_id}/outputs/report.txt"

    async def test_write_text_scoped_input_returns_relative_path(self):
        ctx = _make_context()
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            _persist_uploads(mock_storage)
            result = await _write_file_handler(
                {"path": f"jobs/{ctx.job_id}/outputs/risk_comparison_table.md", "content": "table"},
                ctx,
            )
        assert result["ok"] is True
        assert result["path"] == "outputs/risk_comparison_table.md"
        assert mock_storage.return_value.upload_file.call_args.args[1] == f"jobs/{ctx.job_id}/outputs/risk_comparison_table.md"

    async def test_write_explicit_subdirectory(self):
        ctx = _make_context()
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            _persist_uploads(mock_storage)
            result = await _write_file_handler(
                {"path": "outputs/summary/report.json", "content": '{"ok": true}'},
                ctx,
            )
        assert result["ok"] is True

    async def test_write_disallowed_extension(self):
        ctx = _make_context()
        result = await _write_file_handler({"path": "script.exe", "content": "x"}, ctx)
        assert "error" in result
        assert "extension" in result["error"].lower() or "File extension" in result["error"]

    async def test_write_allowed_extensions(self):
        for ext in [".txt", ".csv", ".json", ".md", ".html", ".py", ".report"]:
            ctx = _make_context()
            with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
                _persist_uploads(mock_storage)
                result = await _write_file_handler(
                    {"path": f"outputs/file{ext}", "content": "data"},
                    ctx,
                )
            assert result["ok"] is True, f"Extension {ext} should be allowed"

    async def test_write_binary_extension_requires_base64(self):
        ctx = _make_context()
        result = await _write_file_handler({"path": "outputs/bad.xlsx", "content": "not an xlsx"}, ctx)
        assert "content_base64" in result["error"]

    async def test_write_rejects_invalid_xlsx_base64(self):
        ctx = _make_context()
        invalid_zip = base64.b64encode(b"not a real workbook").decode("ascii")
        result = await _write_file_handler({"path": "outputs/bad.xlsx", "content_base64": invalid_zip}, ctx)
        assert "valid ZIP" in result["error"]

    async def test_write_accepts_valid_xlsx_base64(self):
        ctx = _make_context()
        encoded = base64.b64encode(_minimal_xlsx_bytes()).decode("ascii")
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            _persist_uploads(mock_storage)
            result = await _write_file_handler({"path": "outputs/good.xlsx", "content_base64": encoded}, ctx)
        assert result["ok"] is True
        assert result["mime_type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        mock_storage.return_value.upload_file.assert_called_once()

    def test_verify_saved_file_rejects_missing_file(self):
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            mock_storage.return_value.exists.return_value = False
            result = verify_saved_file("job-1", "outputs/missing.xlsx")

        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_verify_saved_file_rejects_corrupt_xlsx(self):
        fake_path = "/tmp/bad.xlsx"
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            svc = mock_storage.return_value
            svc.exists.return_value = True
            svc.get_local_path.return_value.__enter__.return_value = fake_path

            with patch("pathlib.Path.stat") as mock_stat, \
                 patch("pathlib.Path.read_bytes", return_value=b"not a workbook"):
                mock_stat.return_value.st_size = 14
                result = verify_saved_file("job-1", "outputs/bad.xlsx", expected_size=14)

        assert result["ok"] is False
        assert "File verification failed" in result["error"]

    def test_verify_saved_file_accepts_current_job_scoped_path(self):
        fake_path = "/tmp/good.md"
        job_id = "job-1"
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            svc = mock_storage.return_value
            svc.exists.return_value = True
            svc.get_local_path.return_value.__enter__.return_value = fake_path

            with patch("pathlib.Path.stat") as mock_stat:
                mock_stat.return_value.st_size = 5
                result = verify_saved_file(job_id, f"jobs/{job_id}/outputs/good.md", expected_size=5)

        assert result["ok"] is True
        assert result["path"] == "outputs/good.md"

    async def test_write_path_traversal_blocked(self):
        ctx = _make_context()
        result = await _write_file_handler(
            {"path": "../../../etc/cron.d/agent", "content": "malicious"},
            ctx,
        )
        assert "error" in result


class TestConvertToXlsx:
    async def test_convert_docx_to_verified_xlsx(self, tmp_path):
        ctx = _make_context()
        source_path = "outputs/summary.docx"
        source_file = tmp_path / "summary.docx"
        source_file.write_bytes(_build_docx_bytes("หัวข้อ\n| A | B |\n|---|---|\n| หนึ่ง | สอง |"))
        uploaded: dict[str, bytes] = {}

        def exists(path):
            if path.endswith("outputs/summary.docx"):
                return True
            return path in uploaded

        class LocalPath:
            def __init__(self, path):
                self.path = path
            def __enter__(self):
                if self.path.endswith("outputs/summary.docx"):
                    return str(source_file)
                output_file = tmp_path / "summary.xlsx"
                output_file.write_bytes(uploaded[self.path])
                return str(output_file)
            def __exit__(self, exc_type, exc, tb):
                return False

        def upload(file_obj, path, content_type=None):
            uploaded[path] = file_obj.read()

        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            svc = mock_storage.return_value
            svc.exists.side_effect = exists
            svc.get_local_path.side_effect = lambda path: LocalPath(path)
            svc.upload_file.side_effect = upload
            result = await _convert_to_xlsx_handler({"source_path": source_path}, ctx)

        assert result["ok"] is True
        assert result["verified"] is True
        assert result["path"] == "outputs/summary.xlsx"
        xlsx_bytes = next(iter(uploaded.values()))
        with zipfile.ZipFile(io.BytesIO(xlsx_bytes), "r") as workbook:
            assert "[Content_Types].xml" in workbook.namelist()
            assert "xl/workbook.xml" in workbook.namelist()
            assert "xl/worksheets/sheet1.xml" in workbook.namelist()

    async def test_convert_missing_source_rejected(self):
        ctx = _make_context()
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            mock_storage.return_value.exists.return_value = False
            result = await _convert_to_xlsx_handler({"source_path": "outputs/missing.docx"}, ctx)
        assert "Source file not found" in result["error"]


# ── list_files ────────────────────────────────────────────────────────────────

class TestListFiles:
    async def test_list_scopes_to_job(self):
        ctx = _make_context()
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            svc = mock_storage.return_value
            svc.client.get_paginator.return_value.paginate.return_value = [
                {"Contents": [{"Key": f"jobs/{ctx.job_id}/outputs/a.txt", "Size": 100, "LastModified": "2025-01-01"}]},
            ]
            result = await _list_files_handler({"prefix": "outputs/"}, ctx)
        assert result["count"] == 1
        assert result["files"][0]["path"] == "outputs/a.txt"

    async def test_list_empty_job(self):
        ctx = _make_context()
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            svc = mock_storage.return_value
            svc.client.get_paginator.return_value.paginate.return_value = []
            result = await _list_files_handler({}, ctx)
        assert result["count"] == 0


# ── delete_file ───────────────────────────────────────────────────────────────

class TestDeleteFile:
    async def test_delete_empty_path_rejected(self):
        ctx = _make_context()
        result = await _delete_file_handler({"path": "  "}, ctx)
        assert "error" in result

    async def test_delete_path_traversal_blocked(self):
        ctx = _make_context()
        result = await _delete_file_handler({"path": "../../../secrets.env"}, ctx)
        assert "error" in result

    async def test_delete_not_found(self):
        ctx = _make_context()
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            mock_storage.return_value.exists.return_value = False
            result = await _delete_file_handler({"path": "outputs/ghost.txt"}, ctx)
        assert "error" in result

    async def test_delete_success(self):
        ctx = _make_context()
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
            mock_storage.return_value.exists.side_effect = [True, False]
            result = await _delete_file_handler({"path": "outputs/old.txt"}, ctx)
        assert result["ok"] is True


# ── Allowed Extensions ───────────────────────────────────────────────────────

class TestAllowedExtensions:
    def test_common_extensions_allowed(self):
        for ext in [".txt", ".md", ".csv", ".json", ".jsonl", ".yaml", ".yml",
                     ".html", ".xml", ".log", ".py", ".sh", ".sql", ".tsv",
                     ".report", ".summary"]:
            assert ext in ALLOWED_EXTENSIONS, f"Extension {ext} should be in ALLOWED_EXTENSIONS"

    def test_dangerous_extensions_blocked(self):
        for ext in [".exe", ".bin", ".dll", ".so", ".shs", ".ps1", ".bat"]:
            assert ext not in ALLOWED_EXTENSIONS, f"Extension {ext} should NOT be allowed"


# ── HTML Rendering ───────────────────────────────────────────────────────────

class TestBuildHtmlDocument:
    def test_markdown_becomes_a_standalone_styled_document(self):
        html = _build_html_document(
            "# รายงานสัญญา\n\n## สรุป\n- ข้อ **หนึ่ง**\n\n| A | B |\n|---|---|\n| 1 | 2 |",
            "รายงานสัญญา",
        )
        assert html.startswith("<!DOCTYPE html>")
        assert "<title>รายงานสัญญา</title>" in html
        assert "<h2>สรุป</h2>" in html
        assert "<strong>หนึ่ง</strong>" in html
        assert "<th>A</th>" in html and "<td>2</td>" in html
        # The title already renders as the document heading.
        assert html.count("รายงานสัญญา") == 2

    def test_escapes_untrusted_markup_in_content(self):
        html = _build_html_document("Value <script>alert(1)</script>", "Report")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_complete_html_document_is_passed_through(self):
        source = "<html><body><p>done</p></body></html>"
        assert _build_html_document(source, "Report") == "<!DOCTYPE html>\n" + source

    def test_dash_filled_data_row_is_not_mistaken_for_the_header_divider(self):
        """Only the row immediately after the header is a divider; a later
        all-dash row (e.g. an 'N/A' placeholder) is real data and must survive.
        """
        html = _build_html_document(
            "| Field | Value |\n|---|---|\n| Amount | -- |\n| Note | -- |",
            "Report",
        )
        assert html.count("<td>--</td>") == 2

    def test_duplicate_title_heading_is_stripped_even_with_leading_blank_line(self):
        html = _build_html_document("\n# Report\n\nBody text", "Report")
        # Stripped from the body — only the <h1 class="report-title"> remains.
        assert html.count("Report") == 2  # <title> + report-title, not a third in <p>/body</p>
        assert "<p>Report</p>" not in html
