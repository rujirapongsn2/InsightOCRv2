"""Tests for agent trustworthiness: success aggregation, DB read-back,
sandbox error surfacing, reflection honesty.

These guard against the false-success problem where the agent reports DONE
when work actually failed.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch
import uuid

import pytest

from app.agent.loop import (
    AgentLoop,
    _aggregate_success,
    _chat_with_retry,
    _is_context_length_error,
    _is_report_success,
    _tool_failed,
)


# ── _aggregate_success ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "result, expected",
    [
        ({"result": {"answer": "ok"}, "error": None}, False),
        ({"result": 1, "error": "sandbox failed"}, True),
        ({"ok": True, "verified": True}, False),
        ({"ok": False, "error": "write failed"}, True),
        ({"error": ""}, False),
    ],
)
def test_tool_failed_only_marks_truthy_errors(result, expected):
    """Tools may include an explicit null error field on successful results."""
    assert _tool_failed(result) is expected


def test_aggregate_success_pure_success():
    ok, steps = _aggregate_success(
        stopped=None,
        reflection={"complete": True, "missing": []},
        critical_failures=[],
        current_turn_file_success=True,
        requires_file=True,
    )
    assert ok is True
    assert steps == []


def test_aggregate_success_max_iterations_means_failure():
    ok, steps = _aggregate_success(
        stopped="max_iterations",
        reflection={"complete": True, "missing": []},
        critical_failures=[],
        current_turn_file_success=True,
        requires_file=False,
    )
    assert ok is False
    assert any("max tool iterations" in s.lower() for s in steps)


def test_aggregate_success_reflection_incomplete_propagates_missing():
    ok, steps = _aggregate_success(
        stopped=None,
        reflection={"complete": False, "missing": ["Step A not done", "Step B not done"]},
        critical_failures=[],
        current_turn_file_success=True,
        requires_file=False,
    )
    assert ok is False
    assert "Step A not done" in steps
    assert "Step B not done" in steps


def test_aggregate_success_critical_failure_blocks_success():
    ok, steps = _aggregate_success(
        stopped=None,
        reflection={"complete": True, "missing": []},
        critical_failures=[{"tool": "write_file", "error": "write_file: disk full"}],
        current_turn_file_success=False,
        requires_file=False,
    )
    assert ok is False
    assert "write_file: disk full" in steps


def test_aggregate_success_missing_file_output_blocks_success():
    ok, steps = _aggregate_success(
        stopped=None,
        reflection={"complete": True, "missing": []},
        critical_failures=[],
        current_turn_file_success=False,
        requires_file=True,
    )
    assert ok is False
    assert any("file output" in s.lower() for s in steps)


def test_aggregate_success_no_reflection_is_tolerated():
    """If reflection never ran (None), don't fail just because it's absent."""
    ok, steps = _aggregate_success(
        stopped=None,
        reflection=None,
        critical_failures=[],
        current_turn_file_success=True,
        requires_file=True,
    )
    assert ok is True
    assert steps == []


@pytest.mark.asyncio
async def test_required_tool_call_provider_failure_is_not_silently_degraded():
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("function calling unsupported"))

    with pytest.raises(RuntimeError, match="rejected tool/function calling"):
        await _chat_with_retry(
            client,
            model="test",
            messages=[],
            tools=[{"type": "function", "function": {"name": "create_docx"}}],
            tool_choice="auto",
            require_tools=True,
        )


# ── context-length overflow: fail fast, don't burn retries ─────────────


@pytest.mark.parametrize(
    "exc",
    [
        RuntimeError("Error code: 400 - This model's maximum context length is 8192 tokens"),
        RuntimeError("400 context_length_exceeded: reduce the length of the messages"),
        RuntimeError("the prompt is too long for this model's context window"),
    ],
)
def test_is_context_length_error_matches_common_provider_messages(exc):
    assert _is_context_length_error(exc) is True


def test_is_context_length_error_ignores_unrelated_failures():
    assert _is_context_length_error(RuntimeError("connection reset by peer")) is False


def test_is_context_length_error_ignores_rate_limit_errors_with_overlapping_wording():
    """A 429 tokens-per-minute message can legitimately say 'too many tokens' —
    that must still be retried with backoff, not treated as a fatal overflow."""
    exc = RuntimeError("Rate limit reached: too many tokens per minute, please retry later")
    exc.status_code = 429
    assert _is_context_length_error(exc) is False


def test_is_context_length_error_ignores_rate_limit_error_class_name():
    class RateLimitError(RuntimeError):
        pass

    assert _is_context_length_error(RateLimitError("context window busy, try again")) is False


# ── _is_report_success recognizes every report-producing tool ──────────


def test_is_report_success_recognizes_create_html():
    result = {"ok": True, "verified": True, "path": "outputs/report.html"}
    assert _is_report_success("create_html", result) is True


def test_is_report_success_still_recognizes_run_report_code():
    result = {"ok": True, "verified": True, "path": "outputs/report.html"}
    assert _is_report_success("run_report_code", result) is True


def test_is_report_success_rejects_unrelated_tools():
    result = {"ok": True, "verified": True, "path": "outputs/data.xlsx"}
    assert _is_report_success("convert_to_xlsx", result) is False


@pytest.mark.asyncio
async def test_context_length_overflow_fails_fast_without_retrying():
    """Retrying a too-large prompt just resends the same size — must not retry."""
    client = MagicMock()
    call_count = 0

    async def raise_context_error(**_kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Error code: 400 - This model's maximum context length is 4096 tokens")

    client.chat.completions.create = AsyncMock(side_effect=raise_context_error)

    with pytest.raises(RuntimeError, match="context window"):
        await _chat_with_retry(
            client,
            model="test",
            messages=[{"role": "user", "content": "x" * 50_000}],
            max_attempts=3,
        )
    assert call_count == 1


# ── _reflect honesty ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reflect_failure_returns_incomplete():
    """When the reflect LLM call raises, _reflect must NOT default to complete."""
    loop = AgentLoop.__new__(AgentLoop)  # bypass __init__
    client = MagicMock()
    with patch("app.agent.loop._chat_with_retry", new=AsyncMock(side_effect=RuntimeError("network down"))):
        result = await loop._reflect(
            client, model="gpt-test", user_message="do X",
            plan_steps=["step 1"], draft_answer="did X", tools_used={"write_file"},
        )
    assert result["complete"] is False
    assert any("Self-review could not run" in m for m in result["missing"])
    assert "RuntimeError" in result["missing"][0]


# ── code_sandbox JSONDecodeError ─────────────────────────────────────


@pytest.mark.asyncio
async def test_code_sandbox_jsondecode_surfaces_error(monkeypatch):
    """Malformed __SANDBOX_OUTPUT__ must surface as an error, not silent success."""
    fake_output = "__SANDBOX_OUTPUT__: {not valid json\n"

    # Sandbox now runs detached: containers.run() returns a Container the
    # code drives via wait()/logs()/remove().
    class _FakeContainer:
        def wait(self, *a, **k):
            return {"StatusCode": 0}

        def logs(self, *a, **k):
            return fake_output.encode("utf-8")

        def remove(self, *a, **k):
            pass

    fake_client = MagicMock()
    fake_client.containers.run.return_value = _FakeContainer()
    fake_client.images.get.return_value = MagicMock()  # image exists

    fake_docker = MagicMock()
    fake_docker.from_env.return_value = fake_client
    fake_docker.errors.ContainerError = type("ContainerError", (Exception,), {})
    fake_docker.errors.ImageNotFound = type("ImageNotFound", (Exception,), {})

    monkeypatch.setitem(__import__("sys").modules, "docker", fake_docker)

    from app.services import code_sandbox
    result = await code_sandbox.execute_python(code="print('hi')", inputs={})

    assert result.get("error") is not None
    assert "malformed json" in result["error"].lower()


# ── document_tools DB read-back ──────────────────────────────────────


@pytest.mark.asyncio
async def test_document_update_readback_detects_commit_failure():
    """If db.commit() raises, the handler must return ok: False."""
    from app.agent.tools.document_tools import _update_document_field_handler

    doc = MagicMock()
    doc.reviewed_data = {"existing": "value"}
    doc.id = uuid.uuid4()

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = doc
    db.commit.side_effect = RuntimeError("connection lost")

    context = MagicMock()
    context.db = db
    context.job_id = uuid.uuid4()

    result = await _update_document_field_handler(
        {"doc_id": str(doc.id), "field": "amount", "value": 100},
        context,
    )
    assert result.get("ok") is False
    assert "DB commit failed" in result["error"]
    assert "connection lost" in result["error"]
    db.rollback.assert_called_once()


@pytest.mark.asyncio
async def test_document_update_readback_detects_mismatch():
    """If read-back shows the field wasn't persisted, return ok: False."""
    from app.agent.tools.document_tools import _update_document_field_handler

    doc = MagicMock()
    doc.reviewed_data = {"existing": "value"}
    doc.id = uuid.uuid4()

    # Simulate a commit that "succeeds" but the value didn't stick on refresh.
    def _refresh(d):
        # reviewed_data stays as the original dict, missing the new field
        d.reviewed_data = {"existing": "value"}

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = doc
    db.refresh.side_effect = _refresh

    context = MagicMock()
    context.db = db
    context.job_id = uuid.uuid4()

    result = await _update_document_field_handler(
        {"doc_id": str(doc.id), "field": "amount", "value": 100},
        context,
    )
    assert result.get("ok") is False
    assert "Read-back mismatch" in result["error"]
