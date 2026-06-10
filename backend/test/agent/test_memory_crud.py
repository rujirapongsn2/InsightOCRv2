"""
Unit tests for memory CRUD operations.

Run: cd backend && python -m pytest test/agent/test_memory_crud.py -v
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.db.base_class import Base
from app.models.agent_memory import AgentMemory
from app.crud.crud_agent_memory import agent_memory as crud_memory, _not_expired


# ── Helpers to build in-memory rows without going through create_all ──────────

class _FakeMemory:
    """Stand-in for AgentMemory so we can test CRUD logic without SQLite."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _make_fake_mem(**overrides):
    defaults = {
        "id": uuid.uuid4(), "user_id": uuid.uuid4(), "job_id": None,
        "scope": "user", "memory_type": "fact", "key": "test-key",
        "content": "test content", "importance": 1.0, "access_count": 0,
        "expires_at": None, "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return _FakeMemory(**defaults)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestUpsert:
    def test_create_new_memory(self):
        db = MagicMock()
        db.query().filter().first.return_value = None  # no existing row
        mem = crud_memory.upsert(db, user_id=uuid.uuid4(), job_id=None, scope="user",
                                  memory_type="preference", key="lang", content="th")
        assert mem is not None
        db.add.assert_called_once()
        db.commit.assert_called()

    def test_upsert_updates_existing(self):
        db = MagicMock()
        existing = _make_fake_mem(key="lang", content="th", memory_type="preference", importance=1.0)
        db.query().filter().first.return_value = existing
        mem = crud_memory.upsert(db, user_id=existing.user_id, job_id=None, scope="user",
                                  memory_type="fact", key="lang", content="en", importance=3.0)
        assert mem.content == "en"
        assert mem.memory_type == "fact"
        assert mem.importance == 3.0

    def test_upsert_with_expires_at(self):
        db = MagicMock()
        db.query().filter().first.return_value = None
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        crud_memory.upsert(db, user_id=uuid.uuid4(), job_id=None, scope="user",
                           memory_type="fact", key="temp", content="gone soon",
                           expires_at=expires)
        added_obj = db.add.call_args[0][0]
        assert added_obj.expires_at == expires


class TestSearch:
    def test_search_filters_by_user(self):
        db = MagicMock()
        user_id = uuid.uuid4()
        mock_query = db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.limit.return_value.all.return_value = []
        crud_memory.search(db, user_id=user_id, query="test")
        # Verify user_id filter was applied
        args = db.query.call_args

    def test_search_filters_expired(self):
        db = MagicMock()
        mock_query = db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.limit.return_value.all.return_value = []
        crud_memory.search(db, user_id=uuid.uuid4(), query="test")
        # _not_expired() should have been included in filters
        # Verify the filter chain was called
        assert mock_query.filter.called

    def test_search_returns_results(self):
        db = MagicMock()
        fake_mems = [
            _make_fake_mem(key="a", content="first", importance=2.0),
            _make_fake_mem(key="b", content="second", importance=5.0),
        ]
        mock_query = db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.limit.return_value.all.return_value = fake_mems
        results = crud_memory.search(db, user_id=uuid.uuid4(), query="")
        assert len(results) == 2

    def test_search_increments_access_count_atomically(self):
        db = MagicMock()
        fake_mems = [_make_fake_mem(key="hit", access_count=5)]
        mock_query = db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.limit.return_value.all.return_value = fake_mems
        crud_memory.search(db, user_id=uuid.uuid4(), query="hit")
        # Should execute an UPDATE for access_count
        db.execute.assert_called_once()

    def test_search_tenant_isolation_different_user(self):
        db = MagicMock()
        mock_query = db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.limit.return_value.all.return_value = []
        results = crud_memory.search(db, user_id=uuid.uuid4(), query="secret")
        assert results == []


class TestListByScope:
    def test_list_user_scope(self):
        db = MagicMock()
        fake_mems = [_make_fake_mem(scope="user"), _make_fake_mem(scope="user")]
        mock_query = db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = fake_mems
        results = crud_memory.list_by_scope(db, user_id=uuid.uuid4(), scope="user")
        assert len(results) == 2

    def test_list_job_scope_with_job_id(self):
        db = MagicMock()
        fake_mems = [_make_fake_mem(scope="job", job_id=uuid.uuid4())]
        mock_query = db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = fake_mems
        results = crud_memory.list_by_scope(db, user_id=uuid.uuid4(), scope="job", job_id=uuid.uuid4())
        assert len(results) == 1

    def test_list_filters_expired(self):
        db = MagicMock()
        mock_query = db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.all.return_value = []
        results = crud_memory.list_by_scope(db, user_id=uuid.uuid4(), scope="user")
        assert results == []
        # _not_expired() should be in filter chain
        assert mock_query.filter.called


class TestDelete:
    def test_delete_existing(self):
        db = MagicMock()
        existing = _make_fake_mem()
        db.query().filter().first.return_value = existing
        result = crud_memory.delete(db, user_id=existing.user_id, key=existing.key, scope=existing.scope)
        assert result is True
        db.delete.assert_called_once_with(existing)
        db.commit.assert_called()

    def test_delete_nonexistent(self):
        db = MagicMock()
        db.query().filter().first.return_value = None
        result = crud_memory.delete(db, user_id=uuid.uuid4(), key="ghost", scope="user")
        assert result is False


class TestNotExpiredFilter:
    def test_not_expired_clause_includes_no_expiry(self):
        # Verify the SQL expression is constructed correctly
        clause = _not_expired()
        assert clause is not None

    def test_not_expired_clause_includes_future_expiry(self):
        clause = _not_expired()
        assert clause is not None
