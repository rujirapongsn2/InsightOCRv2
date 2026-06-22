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
    _tool_failed,
)


# ── _aggregate_success ───────────────────────────────────────────────


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

    class _FakeContainer:
        def decode(self, *a, **k):
            return fake_output  # str — mirrors what bytes.decode() returns

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
