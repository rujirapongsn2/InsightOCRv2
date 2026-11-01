"""A call whose run ended before it returned gets one stored result saying so (UAT round 2 N4).

Before, Stop while approve_document waited for confirmation left the call
without a result row, and the chat showed it running forever, even after a
reload. Each test runs on SQLite and on a throwaway Postgres database
(postgres_engine in conftest.py).
"""
import asyncio
import importlib
import importlib.util
import json
import pkgutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
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
from app.agent.context import AgentContext  # noqa: E402
from app.api.v1.endpoints import agent as agent_endpoints  # noqa: E402
from app.models.agent_conversation import AgentConversation  # noqa: E402
from app.models.agent_message import AgentMessage  # noqa: E402
from app.models.agent_pending_action import AgentPendingAction  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.user import User  # noqa: E402
from app.tasks import agent_tasks  # noqa: E402
from app.tasks.maintenance_tasks import _reconcile_agent_runs  # noqa: E402

USER = uuid.uuid4()
JOB = uuid.uuid4()


@pytest.fixture(params=["sqlite", "postgres"])
def db(request, monkeypatch):
    if request.param == "sqlite":
        engine = create_engine("sqlite://")
        AgentRun.metadata.create_all(engine, tables=[
            AgentConversation.__table__, AgentMessage.__table__, AgentPendingAction.__table__, AgentRun.__table__,
            Document.__table__])
    else:
        engine = request.getfixturevalue("postgres_engine")
    session = sessionmaker(bind=engine, autoflush=False)()
    if request.param == "postgres":
        session.add_all([User(id=USER, email="unfinished@example.com", hashed_password="x"),
                         Job(id=JOB, user_id=USER, name="unfinished")])
        session.commit()
    # The worker and its stop checks use this session (SQLite in memory is one connection).
    monkeypatch.setattr(agent_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(session, "close", lambda: None)
    yield session
    session.rollback()
    Session = type(session)
    Session.close(session)


def _queued_run(db, *, ago=timedelta(minutes=1), conversation_id=None):
    """A run as send_agent_message stores it: the user turn and the queued run in one transaction."""
    created = datetime.now(timezone.utc) - ago
    if conversation_id is None:
        conversation_id = uuid.uuid4()
        db.add(AgentConversation(id=conversation_id, job_id=JOB, user_id=USER))
    run = AgentRun(id=uuid.uuid4(), conversation_id=conversation_id, user_id=USER, user_message="อนุมัติ",
                   status="queued", created_at=created)
    db.add_all([run, AgentMessage(id=uuid.uuid4(), conversation_id=conversation_id, role="user", content="อนุมัติ",
                                  iteration=0, created_at=created)])
    db.commit()
    return run


def _document(db):
    doc = Document(id=uuid.uuid4(), job_id=JOB, filename="Q25100034-8.pdf", file_path="x",
                   status="extraction_completed")
    db.add(doc)
    db.commit()
    return doc


def _model(monkeypatch, *calls):
    """A model that makes these calls, one turn each, then answers."""
    turns = []

    async def chat(_client, **kwargs):
        if not kwargs.get("tools"):  # planning and reflection
            message = SimpleNamespace(content='{"steps": []}', tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)
        turns.append(kwargs["messages"])
        if len(turns) <= len(calls):
            name, args = calls[len(turns) - 1]
            call = SimpleNamespace(id=f"call{len(turns)}", type="function", function=SimpleNamespace(
                name=name, arguments=json.dumps(args)))
            message = SimpleNamespace(content=None, tool_calls=[call])
        else:
            message = SimpleNamespace(content="เรียบร้อย", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")], usage=None)

    monkeypatch.setattr(loop_module, "_chat_with_retry", chat)
    monkeypatch.setattr(loop_module, "build_system_prompt", lambda context, request: "sys")
    monkeypatch.setattr(loop_module, "log_activity", lambda *a, **k: None)
    monkeypatch.setattr(agent_endpoints, "_build_agent_llm_config", lambda db, conversation: {"apiKey": "k", "model": "m"})
    monkeypatch.setattr(agent_tasks, "CANCEL_CHECK_SECONDS", 0.0)
    return turns


def _work(db, run):
    agent_tasks.run_agent_task.push_request(id="task-1")
    try:
        agent_tasks.run_agent_task.run(str(run.id))
    finally:
        agent_tasks.run_agent_task.pop_request()
    db.expire_all()
    return db.get(AgentRun, run.id)


async def _press_stop(db, run):
    await agent_endpoints.cancel_agent_run(run.conversation_id, run.id, db=db, current_user=SimpleNamespace(id=USER))


def _results(db, conversation_id):
    return [(m.tool_call_id, m.tool_result) for m in db.query(AgentMessage)
            .filter(AgentMessage.conversation_id == conversation_id, AgentMessage.role == "tool")
            .order_by(AgentMessage.created_at)]


def _unfinished(result):
    return result.get("unfinished") is True and "did not finish" in result["error"]


def _model_history(db, conversation_id):
    return asyncio.run(AgentContext(db, USER, JOB, conversation_id).load_history())


def test_stop_while_a_confirmation_waits_stores_one_unfinished_result(db, monkeypatch):
    doc = _document(db)
    run = _queued_run(db)
    _model(monkeypatch, ("approve_document", {"doc_id": str(doc.id)}))

    stored_by_stop = []

    async def user_presses_stop(self, pending_id, timeout_s=0):
        await _press_stop(db, run)
        stored_by_stop.extend(_results(db, run.conversation_id))
        return "expired"  # what the wait returns once it sees the run stopped

    monkeypatch.setattr(loop_module.AgentLoop, "_wait_for_confirmation", user_presses_stop)
    finished = _work(db, run)

    assert stored_by_stop == []  # the worker, not the Stop endpoint, stores it
    assert finished.status == "cancelled" and finished.finished_at is not None
    [(call_id, result)] = _results(db, run.conversation_id)
    assert call_id == "call1" and _unfinished(result) and result["error"].startswith("approve_document did not finish")
    assert db.get(Document, doc.id).status == "extraction_completed"

    told = [m for m in _model_history(db, run.conversation_id) if m.get("tool_call_id") == "call1"]
    assert len(told) == 1 and json.loads(told[0]["content"]) == result


@pytest.mark.parametrize("where", ["worker", "runtime_limit"])
def test_a_run_that_dies_mid_call_stores_an_unfinished_result(db, monkeypatch, where):
    run = _queued_run(db)
    _model(monkeypatch, ("list_documents", {}))
    if where == "worker":
        original = agent_tasks._read_event

        def crash_on_the_call(event, completed, error):
            if '"type": "tool_call"' in event:
                raise RuntimeError("worker crashed")
            return original(event, completed, error)
        monkeypatch.setattr(agent_tasks, "_read_event", crash_on_the_call)
    else:
        async def hangs(*args, **kwargs):
            await asyncio.sleep(60)
        monkeypatch.setattr(loop_module.tool_registry, "execute", hangs)
        monkeypatch.setattr(loop_module, "AGENT_MAX_RUNTIME_S", 0.5)

    finished = _work(db, run)

    assert finished.status == "failed"
    [(call_id, result)] = _results(db, run.conversation_id)
    assert call_id == "call1" and _unfinished(result)


def test_a_normal_finish_stores_no_extra_result(db, monkeypatch):
    run = _queued_run(db)
    _model(monkeypatch, ("list_documents", {}))

    async def listed(*args, **kwargs):
        return {"documents": [], "total": 0}
    monkeypatch.setattr(loop_module.tool_registry, "execute", listed)

    finished = _work(db, run)

    assert finished.status == "succeeded"
    assert _results(db, run.conversation_id) == [("call1", {"documents": [], "total": 0})]


def test_stop_pressed_while_an_approved_call_runs_keeps_only_its_real_result(db, monkeypatch):
    """The race: Stop lands while the worker is about to store the real result."""
    doc = _document(db)
    run = _queued_run(db)
    _model(monkeypatch, ("approve_document", {"doc_id": str(doc.id)}))

    async def approved(self, pending_id, timeout_s=0):
        return "confirmed"

    async def approve_then_stop(name, args, context):
        await _press_stop(db, run)
        return {"ok": True, "doc_id": args["doc_id"], "status": "approved"}

    monkeypatch.setattr(loop_module.AgentLoop, "_wait_for_confirmation", approved)
    monkeypatch.setattr(loop_module.tool_registry, "execute", approve_then_stop)
    finished = _work(db, run)

    assert finished.status == "cancelled"
    real = [("call1", {"ok": True, "doc_id": str(doc.id), "status": "approved"})]
    assert _results(db, run.conversation_id) == real

    # Maintenance or the migration reaching the same run later changes nothing.
    _reconcile_agent_runs(db, datetime.now(timezone.utc) + timedelta(days=1))
    db.commit()
    assert _results(db, run.conversation_id) == real


def test_maintenance_closes_the_calls_of_a_run_whose_worker_died(db):
    run = _queued_run(db, ago=timedelta(hours=2))
    run.status, run.started_at = "running", datetime.now(timezone.utc) - timedelta(hours=2)
    db.add(AgentMessage(id=uuid.uuid4(), conversation_id=run.conversation_id, role="assistant",
                        tool_calls=[{"id": "call1", "type": "function",
                                     "function": {"name": "bulk_approve", "arguments": "{}"}}],
                        iteration=1, created_at=run.created_at + timedelta(seconds=5)))
    db.commit()

    assert _reconcile_agent_runs(db, datetime.now(timezone.utc)) == 1
    db.commit()
    db.expire_all()
    assert db.get(AgentRun, run.id).status == "failed"
    [(call_id, result)] = _results(db, run.conversation_id)
    assert call_id == "call1" and result["error"].startswith("bulk_approve did not finish")


def _migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0032_unfinished_call_results.py"
    spec = importlib.util.spec_from_file_location("migration_0032", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call_message(db, run, call_id, seconds, name="approve_document"):
    db.add(AgentMessage(id=uuid.uuid4(), conversation_id=run.conversation_id, role="assistant",
                        tool_calls=[{"id": call_id, "type": "function", "function": {"name": name, "arguments": "{}"}}],
                        iteration=1, created_at=run.created_at + timedelta(seconds=seconds)))


def test_the_migration_repairs_only_ended_runs_and_a_second_run_changes_nothing(db):
    stopped = _queued_run(db, ago=timedelta(hours=3))
    stopped.status, stopped.finished_at = "cancelled", datetime.now(timezone.utc) - timedelta(hours=3)
    _call_message(db, stopped, "stopped", 5)
    # The same call id answered in a later run of the conversation is not this run's result.
    answered_later = _queued_run(db, ago=timedelta(hours=2), conversation_id=stopped.conversation_id)
    answered_later.status = "succeeded"
    _call_message(db, answered_later, "answered", 5)
    db.add(AgentMessage(id=uuid.uuid4(), conversation_id=stopped.conversation_id, role="tool",
                        tool_call_id="answered", tool_name="approve_document", tool_result={"ok": True},
                        created_at=answered_later.created_at + timedelta(seconds=6)))
    db.add(AgentMessage(id=uuid.uuid4(), conversation_id=stopped.conversation_id, role="tool",
                        tool_call_id="stopped", tool_name="approve_document", tool_result={"ok": True},
                        created_at=answered_later.created_at + timedelta(seconds=7)))
    stopping = _queued_run(db, ago=timedelta(minutes=5))
    stopping.status = "cancelled"  # its worker is still finishing: it stores the result itself
    _call_message(db, stopping, "stopping", 5)
    live = _queued_run(db, ago=timedelta(minutes=5))
    live.status = "running"
    _call_message(db, live, "live", 5)
    db.commit()
    migration = _migration()

    with db.get_bind().begin() as connection:
        assert migration.upgrade_data(connection) == 1
    db.expire_all()
    repaired = _results(db, stopped.conversation_id)
    assert [call_id for call_id, _ in repaired] == ["stopped", "answered", "stopped"]
    assert _unfinished(repaired[0][1])
    assert _results(db, stopping.conversation_id) == [] and _results(db, live.conversation_id) == []

    # Dated just after its call, the stored result is the one the model reads, once.
    told = [m for m in _model_history(db, stopped.conversation_id) if m.get("tool_call_id") == "stopped"]
    assert [json.loads(m["content"]) for m in told] == [repaired[0][1]]

    with db.get_bind().begin() as connection:
        assert migration.upgrade_data(connection) == 0
    db.expire_all()
    assert _results(db, stopped.conversation_id) == repaired
