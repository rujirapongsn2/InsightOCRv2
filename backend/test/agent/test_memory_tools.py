"""
Unit tests for agent memory tools (save_memory, recall_memory, list_memories, forget_memory).

Run: cd backend && python -m pytest test/agent/test_memory_tools.py -v
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.agent.context import AgentContext
from app.agent.tools.memory_tools import (
    _save_memory_handler,
    _recall_memory_handler,
    _list_memories_handler,
    _forget_memory_handler,
    ALLOWED_SCOPES,
    ALLOWED_TYPES,
    MAX_KEY_LENGTH,
    MAX_CONTENT_LENGTH,
)
from app.crud.crud_agent_memory import agent_memory as crud_memory

pytestmark = pytest.mark.asyncio


def _make_context(user_id=None, job_id=None, conv_id=None):
    db = MagicMock()
    return AgentContext(
        db=db,
        user_id=user_id or uuid.uuid4(),
        job_id=job_id or uuid.uuid4(),
        conversation_id=conv_id or uuid.uuid4(),
    )


def _fake_memory_row(**overrides):
    """Return a dict-like stand-in matching what CRUD returns."""
    defaults = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "job_id": None,
        "scope": "user",
        "memory_type": "general",
        "key": "test-key",
        "content": "test content",
        "importance": 1.0,
        "access_count": 0,
        "expires_at": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    result = MagicMock()
    for k, v in defaults.items():
        setattr(result, k, v)
    return result


# ── save_memory ───────────────────────────────────────────────────────────────

class TestSaveMemory:
    async def test_save_user_scoped(self):
        ctx = _make_context()
        with patch.object(crud_memory, "upsert", return_value=_fake_memory_row(key="lang", scope="user", memory_type="preference")) as mock_upsert:
            result = await _save_memory_handler(
                {"key": "language", "content": "Thai", "scope": "user", "memory_type": "preference"},
                ctx,
            )
        assert result["ok"] is True
        assert result["key"] == "lang"
        mock_upsert.assert_called_once()

    async def test_save_job_scoped(self):
        ctx = _make_context()
        row = _fake_memory_row(scope="job", key="note")
        with patch.object(crud_memory, "upsert", return_value=row) as mock_upsert:
            result = await _save_memory_handler(
                {"key": "note", "content": "invoice batch #1", "scope": "job", "memory_type": "observation"},
                ctx,
            )
        assert result["ok"] is True
        assert result["scope"] == "job"
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["job_id"] == ctx.job_id

    async def test_save_with_ttl(self):
        ctx = _make_context()
        with patch.object(crud_memory, "upsert", return_value=_fake_memory_row()) as mock_upsert:
            result = await _save_memory_handler(
                {"key": "temp", "content": "short-lived", "ttl_minutes": 60},
                ctx,
            )
        assert result["ok"] is True
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["expires_at"] is not None

    async def test_save_ttl_clamped_to_positive(self):
        ctx = _make_context()
        with patch.object(crud_memory, "upsert", return_value=_fake_memory_row()) as mock_upsert:
            await _save_memory_handler({"key": "k", "content": "v", "ttl_minutes": -5}, ctx)
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["expires_at"] is not None  # clamped to 1

    async def test_save_importance_clamped(self):
        ctx = _make_context()
        with patch.object(crud_memory, "upsert", return_value=_fake_memory_row()) as mock_upsert:
            await _save_memory_handler({"key": "vip", "content": "high", "importance": 10}, ctx)
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["importance"] == 5.0

    async def test_save_importance_clamped_low(self):
        ctx = _make_context()
        with patch.object(crud_memory, "upsert", return_value=_fake_memory_row()) as mock_upsert:
            await _save_memory_handler({"key": "low", "content": "low", "importance": -1}, ctx)
        call_kwargs = mock_upsert.call_args.kwargs
        assert call_kwargs["importance"] == 0.0

    async def test_save_empty_key_rejected(self):
        ctx = _make_context()
        result = await _save_memory_handler({"key": "  ", "content": "x"}, ctx)
        assert "error" in result

    async def test_save_empty_content_rejected(self):
        ctx = _make_context()
        result = await _save_memory_handler({"key": "k", "content": "  "}, ctx)
        assert "error" in result

    async def test_save_invalid_scope_rejected(self):
        ctx = _make_context()
        result = await _save_memory_handler({"key": "k", "content": "x", "scope": "global"}, ctx)
        assert "error" in result
        assert "Invalid scope" in result["error"]

    async def test_save_invalid_memory_type_rejected(self):
        ctx = _make_context()
        result = await _save_memory_handler({"key": "k", "content": "x", "memory_type": "secret"}, ctx)
        assert "error" in result
        assert "Invalid memory_type" in result["error"]

    async def test_save_key_too_long_rejected(self):
        ctx = _make_context()
        result = await _save_memory_handler({"key": "x" * (MAX_KEY_LENGTH + 1), "content": "x"}, ctx)
        assert "error" in result

    async def test_save_content_too_long_rejected(self):
        ctx = _make_context()
        result = await _save_memory_handler({"key": "k", "content": "x" * (MAX_CONTENT_LENGTH + 1)}, ctx)
        assert "error" in result


# ── recall_memory ─────────────────────────────────────────────────────────────

class TestRecallMemory:
    async def test_recall_finds_by_keyword(self):
        ctx = _make_context()
        mems = [_fake_memory_row(key="pref_lang", content="User prefers Thai")]
        with patch.object(crud_memory, "search", return_value=mems):
            result = await _recall_memory_handler({"query": "Thai"}, ctx)
        assert result["count"] == 1
        assert result["memories"][0]["key"] == "pref_lang"

    async def test_recall_empty_query_returns_all(self):
        ctx = _make_context()
        mems = [_fake_memory_row(key="a"), _fake_memory_row(key="b")]
        with patch.object(crud_memory, "search", return_value=mems):
            result = await _recall_memory_handler({"query": ""}, ctx)
        assert result["count"] == 2

    async def test_recall_respects_limit(self):
        ctx = _make_context()
        mems = [_fake_memory_row(key=f"k{i}") for i in range(5)]
        with patch.object(crud_memory, "search", return_value=mems[:3]) as mock_search:
            result = await _recall_memory_handler({"query": "", "limit": 3}, ctx)
        assert result["count"] == 3
        mock_search.assert_called_once()
        assert mock_search.call_args.kwargs["limit"] == 3

    async def test_recall_limit_capped_at_20(self):
        ctx = _make_context()
        with patch.object(crud_memory, "search", return_value=[]) as mock_search:
            await _recall_memory_handler({"query": "", "limit": 100}, ctx)
        assert mock_search.call_args.kwargs["limit"] == 20

    async def test_recall_filters_by_scope(self):
        ctx = _make_context()
        mems = [
            _fake_memory_row(key="global", scope="user"),
            _fake_memory_row(key="local", scope="job"),
        ]
        with patch.object(crud_memory, "search", return_value=mems):
            result = await _recall_memory_handler({"query": "", "scope": "job"}, ctx)
        assert result["count"] == 1
        assert result["memories"][0]["key"] == "local"

    async def test_recall_has_required_fields(self):
        ctx = _make_context()
        mems = [_fake_memory_row()]
        with patch.object(crud_memory, "search", return_value=mems):
            result = await _recall_memory_handler({"query": "test"}, ctx)
        mem = result["memories"][0]
        for field in ("id", "scope", "memory_type", "key", "content", "importance", "access_count"):
            assert field in mem


# ── list_memories ─────────────────────────────────────────────────────────────

class TestListMemories:
    async def test_list_user_scope(self):
        ctx = _make_context()
        mems = [_fake_memory_row(key="k1", scope="user"), _fake_memory_row(key="k2", scope="user")]
        with patch.object(crud_memory, "list_by_scope", return_value=mems):
            result = await _list_memories_handler({"scope": "user"}, ctx)
        assert result["count"] == 2

    async def test_list_job_scope_passes_job_id(self):
        ctx = _make_context()
        with patch.object(crud_memory, "list_by_scope", return_value=[]) as mock_list:
            await _list_memories_handler({"scope": "job"}, ctx)
        mock_list.assert_called_once()
        assert mock_list.call_args.kwargs["job_id"] == ctx.job_id

    async def test_list_invalid_scope_rejected(self):
        ctx = _make_context()
        result = await _list_memories_handler({"scope": "admin"}, ctx)
        assert "error" in result

    async def test_list_includes_timestamps(self):
        ctx = _make_context()
        mems = [_fake_memory_row(key="ts")]
        with patch.object(crud_memory, "list_by_scope", return_value=mems):
            result = await _list_memories_handler({"scope": "user"}, ctx)
        assert "created_at" in result["memories"][0]


# ── forget_memory ─────────────────────────────────────────────────────────────

class TestForgetMemory:
    async def test_forget_existing(self):
        ctx = _make_context()
        with patch.object(crud_memory, "delete", return_value=True):
            result = await _forget_memory_handler({"key": "delete_me", "scope": "user"}, ctx)
        assert result["ok"] is True

    async def test_forget_nonexistent(self):
        ctx = _make_context()
        with patch.object(crud_memory, "delete", return_value=False):
            result = await _forget_memory_handler({"key": "no_such_key", "scope": "user"}, ctx)
        assert result["ok"] is False
        assert "error" in result

    async def test_forget_invalid_scope_rejected(self):
        ctx = _make_context()
        result = await _forget_memory_handler({"key": "x", "scope": "global"}, ctx)
        assert "error" in result

    async def test_forget_empty_key_rejected(self):
        ctx = _make_context()
        # Handler now validates empty key before calling delete — no mock needed
        result = await _forget_memory_handler({"key": "  ", "scope": "user"}, ctx)
        assert result["ok"] is False
        assert "error" in result

    async def test_forget_passes_job_id_when_job_scoped(self):
        ctx = _make_context()
        with patch.object(crud_memory, "delete", return_value=True) as mock_delete:
            await _forget_memory_handler({"key": "note", "scope": "job"}, ctx)
        assert mock_delete.call_args.kwargs["job_id"] == ctx.job_id


# ── Constants validation ──────────────────────────────────────────────────────

class TestAllowedValues:
    async def test_allowed_scopes(self):
        assert "user" in ALLOWED_SCOPES
        assert "job" in ALLOWED_SCOPES

    async def test_allowed_types(self):
        for t in ("fact", "preference", "observation", "field_mapping", "review_rule",
                   "integration_preference", "general"):
            assert t in ALLOWED_TYPES
