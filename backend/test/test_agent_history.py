"""What the model reads of earlier turns: a request that was stopped, rejected or expired is shown as such.

Rebuilt from UAT N4/N5 (conversation d7dac20a): the user asked to approve
starbuck.pdf, pressed Stop while the confirmation waited, then asked to
approve 567_Generated_Image.png. The stopped approve_document call has no
result row. History used to drop that call and keep the assistant's text
("checked starbuck.pdf"), so the model read the starbuck request as never
acted on and asked to approve starbuck.pdf again.

Runs on SQLite and on a throwaway Postgres database (postgres_engine in
conftest.py), skipped without a server unless REQUIRE_POSTGRES=1.
"""
import asyncio
import importlib
import json
import pkgutil
import uuid
from datetime import datetime, timedelta, timezone

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


from app.agent.confirmations import declined_result  # noqa: E402
from app.agent.context import AgentContext  # noqa: E402
from app.models.agent_conversation import AgentConversation  # noqa: E402
from app.models.agent_message import AgentMessage  # noqa: E402
from app.models.job import Job  # noqa: E402
from app.models.user import User  # noqa: E402

USER = uuid.uuid4()
JOB = uuid.uuid4()
STARBUCK = "4dd62db4-f192-4042-bc8f-c60b8c6c21a5"
START = datetime(2026, 11, 1, 0, 50, tzinfo=timezone.utc)


@pytest.fixture(params=["sqlite", "postgres"])
def db(request):
    if request.param == "sqlite":
        engine = create_engine("sqlite://")
        AgentMessage.metadata.create_all(engine, tables=[AgentConversation.__table__, AgentMessage.__table__])
    else:
        engine = request.getfixturevalue("postgres_engine")
    session = sessionmaker(bind=engine, autoflush=False)()
    if request.param == "postgres":
        session.add_all([User(id=USER, email="history@example.com", hashed_password="x"),
                         Job(id=JOB, user_id=USER, name="history")])
        session.commit()
    yield session
    session.close()


def _call(call_id, name, **arguments):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def _conversation(db, *rows):
    conversation = AgentConversation(id=uuid.uuid4(), job_id=JOB, user_id=USER)
    db.add(conversation)
    for second, (role, fields) in enumerate(rows):
        db.add(AgentMessage(id=uuid.uuid4(), conversation_id=conversation.id, role=role,
                            created_at=START + timedelta(seconds=second), **fields))
    db.commit()
    return AgentContext(db, USER, JOB, conversation.id)


def _history(context):
    return asyncio.run(context.load_history())


def _results(history):
    return {m["tool_call_id"]: json.loads(m["content"]) for m in history if m["role"] == "tool"}


def _stopped_approval(db, *, latest):
    return _conversation(
        db,
        ("user", {"content": "อนุมัติเอกสาร starbuck.pdf"}),
        ("assistant", {"tool_calls": [_call("search", "search_documents", query="starbuck")]}),
        ("tool", {"tool_call_id": "search", "tool_name": "search_documents",
                  "tool_result": {"count": 1, "documents": [{"id": STARBUCK, "filename": "starbuck.pdf"}]}}),
        ("assistant", {"content": "ตรวจสอบเอกสารแล้ว **starbuck.pdf** ข้อมูลครบถ้วน",
                       "tool_calls": [_call("approve", "approve_document", doc_id=STARBUCK)]}),
        # Stop: the run ended while approve_document waited for confirmation; no result row was written.
        ("user", {"content": latest}),
    )


def test_a_stopped_request_shows_its_call_as_unfinished_and_the_latest_request_comes_last(db):
    history = _history(_stopped_approval(db, latest="อนุมัติเอกสาร 567_Generated_Image.png"))

    approve = next(m for m in history if m.get("tool_calls") and m["tool_calls"][0]["id"] == "approve")
    assert json.loads(approve["tool_calls"][0]["function"]["arguments"]) == {"doc_id": STARBUCK}
    result = _results(history)["approve"]
    assert result["unfinished"] is True
    assert "approve_document did not finish" in result["error"] and "Do not assume it took effect" in result["error"]
    assert history[-1] == {"role": "user", "content": "อนุมัติเอกสาร 567_Generated_Image.png"}


def test_every_call_in_history_is_followed_by_its_own_result(db):
    history = _history(_stopped_approval(db, latest="ต่อ"))
    for index, message in enumerate(history):
        if message.get("tool_calls"):
            ids = [call["id"] for call in message["tool_calls"]]
            following = history[index + 1:index + 1 + len(ids)]
            assert [(m["role"], m["tool_call_id"]) for m in following] == [("tool", i) for i in ids]


@pytest.mark.parametrize("answer", ["rejected", "expired"])
def test_a_rejected_or_expired_request_keeps_the_result_it_recorded(db, answer):
    context = _conversation(
        db,
        ("user", {"content": "อนุมัติเอกสาร starbuck.pdf"}),
        ("assistant", {"tool_calls": [_call("approve", "approve_document", doc_id=STARBUCK)]}),
        ("tool", {"tool_call_id": "approve", "tool_name": "approve_document",
                  "tool_result": declined_result("approve_document", answer)}),
        ("assistant", {"content": "ไม่ได้อนุมัติ"}),
        ("user", {"content": "อนุมัติเอกสาร 567_Generated_Image.png"}),
    )
    assert _results(_history(context))["approve"] == declined_result("approve_document", answer)
