"""
Unit tests for filesystem tools (read_file, write_file, list_files, delete_file).

Run: cd backend && python -m pytest test/agent/test_filesystem_tools.py -v
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.agent.context import AgentContext
from app.agent.tools.filesystem_tools import (
    _read_file_handler,
    _write_file_handler,
    _list_files_handler,
    _delete_file_handler,
    _resolve_path,
    ALLOWED_EXTENSIONS,
)

pytestmark = pytest.mark.asyncio


def _make_context(user_id=None, job_id=None):
    db = MagicMock()
    return AgentContext(
        db=db,
        user_id=user_id or uuid.uuid4(),
        job_id=job_id or uuid.uuid4(),
        conversation_id=uuid.uuid4(),
    )


# ── Path Resolution ──────────────────────────────────────────────────────────

class TestResolvePath:
    def test_basic_scoping(self):
        result = _resolve_path("abc-123", "outputs/report.txt")
        assert result == "jobs/abc-123/outputs/report.txt"

    def test_strips_leading_slash(self):
        result = _resolve_path("abc-123", "/outputs/data.csv")
        assert result == "jobs/abc-123/outputs/data.csv"

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
            result = await _write_file_handler({"path": "report.txt", "content": "data"}, ctx)
        assert result["ok"] is True
        # Path should be scoped to outputs/
        assert "outputs/report.txt" in result["path"]

    async def test_write_explicit_subdirectory(self):
        ctx = _make_context()
        with patch("app.agent.tools.filesystem_tools.get_storage_service") as mock_storage:
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
                result = await _write_file_handler(
                    {"path": f"outputs/file{ext}", "content": "data"},
                    ctx,
                )
            assert result["ok"] is True, f"Extension {ext} should be allowed"

    async def test_write_path_traversal_blocked(self):
        ctx = _make_context()
        result = await _write_file_handler(
            {"path": "../../../etc/cron.d/agent", "content": "malicious"},
            ctx,
        )
        assert "error" in result


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
            mock_storage.return_value.exists.return_value = True
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
