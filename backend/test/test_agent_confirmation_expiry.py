"""An unanswered confirmation expires: distinct from a rejection, for the model, the UI and the API."""
import asyncio
import importlib
import pkgutil
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

import app.models

for _module in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_module.name}")


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(element, compiler, **kw):
    return "JSON"


from app.agent import loop as loop_module  # noqa: E402
from app.agent.confirmations import declined_result  # noqa: E402
from app.api.v1.endpoints.agent import (  # noqa: E402
    _agent_run_payload, agent_metrics, cancel_agent_run, confirm_pending_action,
)
from app.crud.crud_agent_pending import agent_pending  # noqa: E402
from app.models.agent_conversation import AgentConversation  # noqa: E402
from app.models.agent_message import AgentMessage  # noqa: E402
from app.models.agent_pending_action import AgentPendingAction  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.schemas.agent import ConfirmActionRequest  # noqa: E402

USER = uuid.uuid4()


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    tables = [AgentConversation.__table__, AgentMessage.__table__, AgentPendingAction.__table__, AgentRun.__table__]
    AgentRun.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def run(db):
    conversation = AgentConversation(id=uuid.uuid4(), job_id=uuid.uuid4(), user_id=USER)
    run = AgentRun(id=uuid.uuid4(), conversation_id=conversation.id, user_id=USER, user_message="อนุมัติ",
                   status="running", created_at=datetime.now(timezone.utc))
    db.add_all([conversation, run])
    db.commit()
    return run


def _ask(db, run):
    return agent_pending.create(db, conversation_id=run.conversation_id, user_id=USER, tool_name="bulk_approve",
                                tool_arguments={"doc_ids": ["a"]}, run_id=run.id, description="อนุมัติเอกสาร 1 รายการ")


def _waiting_loop(db, monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(loop_module.asyncio, "sleep", no_sleep)
    loop = loop_module.AgentLoop.__new__(loop_module.AgentLoop)
    loop.db, loop.run_id = db, None
    return loop


def _confirm(db, pending_id, approved=True):
    return asyncio.run(confirm_pending_action(pending_id, ConfirmActionRequest(approved=approved,
                                                                               explicit_confirmation=True),
                                              db=db, current_user=SimpleNamespace(id=USER)))


def test_an_unanswered_request_expires_and_is_not_a_rejection(db, run, monkeypatch):
    pending = _ask(db, run)
    answer = asyncio.run(_waiting_loop(db, monkeypatch)._wait_for_confirmation(pending.id, timeout_s=3))
    db.expire_all()
    assert answer == "expired" and agent_pending.get(db, pending.id).status == "expired"

    result = declined_result("bulk_approve", answer)
    assert result["expired"] is True and "expired" in result["error"] and "rejected" not in result["error"]
    assert declined_result("bulk_approve", "rejected")["error"] == "User rejected action"


def test_an_answer_stored_as_the_wait_ends_wins_over_expiry(db, run, monkeypatch):
    pending = _ask(db, run)
    loop = _waiting_loop(db, monkeypatch)
    assert agent_pending.resolve(db, pending.id, "confirmed")
    assert loop._expire_confirmation(pending.id) == "confirmed"
    assert asyncio.run(loop._wait_for_confirmation(pending.id, timeout_s=3)) == "confirmed"


def test_the_poll_carries_the_request_state_until_and_after_it_expires(db, run, monkeypatch):
    pending = _ask(db, run)
    shown = _agent_run_payload(db, run)["pending_action"]
    assert (shown["pending_action_id"], shown["status"]) == (str(pending.id), "pending")

    asyncio.run(_waiting_loop(db, monkeypatch)._wait_for_confirmation(pending.id, timeout_s=1))
    assert _agent_run_payload(db, run)["pending_action"]["status"] == "expired"
    run.status = "succeeded"
    db.commit()
    assert _agent_run_payload(db, run)["pending_action"]["status"] == "expired"


def test_confirming_an_expired_request_is_refused_and_changes_nothing(db, run):
    pending = _ask(db, run)
    assert agent_pending.resolve(db, pending.id, "expired")
    with pytest.raises(HTTPException) as refused:
        _confirm(db, pending.id)
    db.expire_all()
    assert refused.value.status_code == 409 and "หมดเวลา" in refused.value.detail
    assert agent_pending.get(db, pending.id).status == "expired"


def test_answering_twice_is_refused(db, run):
    pending = _ask(db, run)
    assert _confirm(db, pending.id, approved=False) == {"ok": True}
    with pytest.raises(HTTPException) as refused:
        _confirm(db, pending.id)
    db.expire_all()
    assert refused.value.status_code == 409 and agent_pending.get(db, pending.id).status == "rejected"


def test_a_request_a_finished_run_left_waiting_expires(db, run):
    pending = _ask(db, run)
    assert agent_pending.expire_for_run(db, run.id) == 1
    db.expire_all()
    assert agent_pending.get(db, pending.id).status == "expired"


def test_stopping_a_run_expires_the_request_it_was_waiting_on(db, run):
    pending = _ask(db, run)
    body = asyncio.run(cancel_agent_run(run.conversation_id, run.id, db=db, current_user=SimpleNamespace(id=USER)))
    db.expire_all()
    assert body["run"]["status"] == "cancelled"
    assert agent_pending.get(db, pending.id).status == "expired"
    assert body["run"]["pending_action"]["status"] == "expired"


def test_a_loop_that_notices_its_run_stopped_expires_the_request(db, run, monkeypatch):
    pending = _ask(db, run)
    loop = _waiting_loop(db, monkeypatch)
    loop.run_id = run.id
    monkeypatch.setattr(loop_module.AgentLoop, "_run_active", lambda self: False)
    answer = asyncio.run(loop._wait_for_confirmation(pending.id, timeout_s=3))
    db.expire_all()
    assert answer == "expired" and agent_pending.get(db, pending.id).status == "expired"
    assert declined_result("bulk_approve", answer)["expired"] is True


def test_metrics_count_expired_requests_apart_from_rejections(db, run):
    _ask(db, run)
    for status in ("confirmed", "rejected", "expired", "expired"):
        agent_pending.resolve(db, _ask(db, run).id, status)
    body = asyncio.run(agent_metrics(days=0, db=db, current_user=SimpleNamespace(role="admin")))
    assert body["confirmations"] == {"pending": 1, "confirmed": 1, "rejected": 1, "expired": 2,
                                     "rejection_rate": 0.5}
