"""Bulk review confirmations: the user confirms a frozen, named set of documents."""
import asyncio
import importlib
import pkgutil
import uuid
from datetime import datetime, timezone
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


from app.models.agent_conversation import AgentConversation
from app.models.agent_pending_action import AgentPendingAction
from app.models.agent_run import AgentRun
from app.models.document import Document

JOB = uuid.uuid4()
OTHER_JOB = uuid.uuid4()


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    tables = [AgentConversation.__table__, AgentPendingAction.__table__, AgentRun.__table__, Document.__table__]
    Document.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _doc(db, filename, job_id=JOB, status="extraction_completed", confidence=None):
    doc = Document(id=uuid.uuid4(), job_id=job_id, filename=filename, file_path="x", status=status,
                   extraction_confidence=confidence)
    db.add(doc)
    db.commit()
    return str(doc.id)


def _run_tool(db, tool_name, args):
    from app.agent.tools.document_tools import _bulk_approve_handler, _bulk_reject_handler

    handler = {"bulk_approve": _bulk_approve_handler, "bulk_reject": _bulk_reject_handler}[tool_name]
    context = SimpleNamespace(db=db, job_id=JOB, user_id=uuid.uuid4())
    return asyncio.run(handler(args, context))


def _status(db, doc_id):
    db.expire_all()
    return db.get(Document, uuid.UUID(doc_id)).status


def _set_status(db, doc_id, status):
    db.get(Document, uuid.UUID(doc_id)).status = status
    db.commit()


def _freeze(db, tool_name, args):
    from app.agent.tools.document_tools import freeze_confirmation

    return freeze_confirmation(db, JOB, tool_name, args)


def test_bulk_approve_with_doc_ids_approves_only_the_selection(db):
    chosen, other, foreign = _doc(db, "a.pdf"), _doc(db, "b.pdf"), _doc(db, "c.pdf", job_id=OTHER_JOB)
    result = _run_tool(db, "bulk_approve", {"doc_ids": [chosen.upper(), foreign]})

    assert result["approved_count"] == 1
    assert result["not_approved_doc_ids"] == [foreign]
    assert (_status(db, chosen), _status(db, other), _status(db, foreign)) == (
        "reviewed", "extraction_completed", "extraction_completed")


def test_empty_selection_approves_nothing(db):
    waiting = _doc(db, "a.pdf")
    result = _run_tool(db, "bulk_approve", {"doc_ids": []})
    assert result["ok"] is False
    assert _status(db, waiting) == "extraction_completed"


def test_one_malformed_id_rejects_the_whole_bulk_call(db):
    waiting = _doc(db, "a.pdf")
    for tool_name in ("bulk_approve", "bulk_reject"):
        result = _run_tool(db, tool_name, {"doc_ids": [waiting, "not-an-id"]})
        assert result["ok"] is False and "not-an-id" in result["error"]
    assert _status(db, waiting) == "extraction_completed"


def test_confirmation_freezes_the_set_the_user_sees(db):
    """Approving "all waiting" approves exactly the documents listed when the user was asked."""
    from app.agent.confirmations import describe_action

    sure = _doc(db, "sure.pdf", confidence=0.95)
    _doc(db, "unsure.pdf", confidence=0.4)
    _doc(db, "done.pdf", status="reviewed", confidence=0.99)
    _doc(db, "other-job.pdf", job_id=OTHER_JOB, confidence=0.99)

    frozen = _freeze(db, "bulk_approve", {"min_confidence": 0.9})
    assert frozen.error is None
    assert frozen.arguments == {"min_confidence": 0.9, "doc_ids": [sure]}
    assert frozen.documents == [{"id": sure, "filename": "sure.pdf", "status": "extraction_completed"}]
    assert describe_action("bulk_approve", frozen.arguments) == "อนุมัติเอกสารที่รอตรวจ 1 รายการ (ความมั่นใจ ≥ 0.9)"

    arrived_later = _doc(db, "arrived-later.pdf", confidence=0.97)
    result = _run_tool(db, "bulk_approve", frozen.arguments)

    assert result["approved_count"] == 1
    assert (_status(db, sure), _status(db, arrived_later)) == ("reviewed", "extraction_completed")


def test_a_frozen_document_no_longer_waiting_is_reported_not_replaced(db):
    first, second = _doc(db, "first.pdf"), _doc(db, "second.pdf")
    frozen = _freeze(db, "bulk_reject", {"doc_ids": [first, second]})
    _set_status(db, second, "reviewed")  # approved elsewhere while the user was deciding
    replacement = _doc(db, "replacement.pdf")

    result = _run_tool(db, "bulk_reject", frozen.arguments)

    assert result["rejected_count"] == 1
    assert result["not_rejected_doc_ids"] == [second]
    assert (_status(db, first), _status(db, second), _status(db, replacement)) == (
        "rejected", "reviewed", "extraction_completed")


def test_bulk_reject_rejects_the_selection_in_one_action(db):
    from app.agent.confirmations import describe_action, requires_confirmation

    a, b, keep = _doc(db, "a.pdf"), _doc(db, "b.pdf"), _doc(db, "keep.pdf")
    frozen = _freeze(db, "bulk_reject", {"doc_ids": [a, b]})

    assert requires_confirmation("bulk_reject", frozen.arguments) is True
    assert describe_action("bulk_reject", frozen.arguments) == "ปฏิเสธเอกสารที่รอตรวจ 2 รายการ"
    assert [d["filename"] for d in frozen.documents] == ["a.pdf", "b.pdf"]
    assert _run_tool(db, "bulk_reject", frozen.arguments)["rejected_count"] == 2
    db.expire_all()
    saved = db.get(Document, uuid.UUID(a))
    assert (saved.status, saved.review_decision, _status(db, keep)) == ("rejected", "rejected", "extraction_completed")
    assert _run_tool(db, "bulk_reject", {})["ok"] is False  # never "reject everything"


def test_nothing_to_confirm_skips_the_question(db):
    _doc(db, "done.pdf", status="reviewed")
    nothing = _freeze(db, "bulk_approve", {})
    assert nothing.error["nothing_to_approve"] is True
    malformed = _freeze(db, "bulk_reject", {"doc_ids": ["nope"]})
    assert "nope" in malformed.error["error"]
    unrelated = _freeze(db, "delete_file", {"path": "outputs/x.csv"})
    assert (unrelated.arguments, unrelated.documents, unrelated.error) == ({"path": "outputs/x.csv"}, None, None)


def _pending_payload(db, tool_name, frozen):
    from app.api.v1.endpoints.agent import _agent_run_payload
    from app.crud.crud_agent_pending import agent_pending

    user = uuid.uuid4()
    conversation = AgentConversation(id=uuid.uuid4(), job_id=JOB, user_id=user)
    run = AgentRun(id=uuid.uuid4(), conversation_id=conversation.id, user_id=user, user_message="go",
                   status="running", created_at=datetime.now(timezone.utc))
    db.add_all([conversation, run])
    db.commit()
    agent_pending.create(db, conversation_id=conversation.id, user_id=user, tool_name=tool_name,
                         tool_arguments=frozen.arguments, run_id=run.id, documents=frozen.documents)
    return lambda: _agent_run_payload(db, run)["pending_action"]


def test_confirmation_lists_the_frozen_snapshot_on_every_poll(db):
    a, b = _doc(db, "invoice-a.pdf"), _doc(db, "invoice-b.pdf")
    _doc(db, "not-selected.pdf")
    foreign = _doc(db, "other-job.pdf", job_id=OTHER_JOB)
    poll = _pending_payload(db, "bulk_approve", _freeze(db, "bulk_approve", {"doc_ids": [b, a, foreign]}))

    expected = [
        {"id": a, "filename": "invoice-a.pdf", "status": "extraction_completed"},
        {"id": b, "filename": "invoice-b.pdf", "status": "extraction_completed"},
    ]
    assert poll()["documents"] == expected
    assert poll()["arguments"] == {"doc_ids": [a, b]}
    db.get(Document, uuid.UUID(a)).filename = "renamed.pdf"
    db.commit()
    assert poll()["documents"] == expected


def test_confirmation_names_come_from_the_database_not_arguments(db):
    doc_id = _doc(db, "real-name.pdf", status="reviewed")
    poll = _pending_payload(db, "reject_document",
                            _freeze(db, "reject_document", {"doc_id": doc_id, "filename": "fake.pdf"}))
    assert poll()["documents"] == [{"id": doc_id, "filename": "real-name.pdf", "status": "reviewed"}]


def test_confirmation_for_foreign_or_unrelated_actions(db):
    foreign = _doc(db, "other-job.pdf", job_id=OTHER_JOB)
    assert _freeze(db, "approve_document", {"doc_id": foreign}).error == {"error": "Document not found"}
    poll = _pending_payload(db, "delete_file", _freeze(db, "delete_file", {"path": "outputs/x.csv"}))
    assert "documents" not in poll()
