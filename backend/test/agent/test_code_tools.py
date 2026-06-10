"""
Unit tests for execute_python tool handler.

Run: cd backend && python -m pytest test/agent/test_code_tools.py -v
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.agent.context import AgentContext
from app.agent.tools.code_tools import _execute_python_handler

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
