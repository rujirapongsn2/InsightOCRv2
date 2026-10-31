"""Selected-document approval: bulk_approve doc_ids and named documents in the confirmation."""
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


def _doc(db, filename, job_id=JOB, status="extraction_completed"):
    doc = Document(id=uuid.uuid4(), job_id=job_id, filename=filename, file_path="x", status=status)
    db.add(doc)
    db.commit()
    return str(doc.id)


def _bulk_approve(db, args):
    from app.agent.tools.document_tools import _bulk_approve_handler

    context = SimpleNamespace(db=db, job_id=JOB, user_id=uuid.uuid4())
    return asyncio.run(_bulk_approve_handler(args, context))


def _status(db, doc_id):
    db.expire_all()
    return db.get(Document, uuid.UUID(doc_id)).status


def test_bulk_approve_with_doc_ids_approves_only_the_selection(db):
    chosen, other, foreign = _doc(db, "a.pdf"), _doc(db, "b.pdf"), _doc(db, "c.pdf", job_id=OTHER_JOB)
    result = _bulk_approve(db, {"doc_ids": [chosen.upper(), foreign]})

    assert result["approved_count"] == 1
    assert result["not_approved_doc_ids"] == [foreign]
    assert (_status(db, chosen), _status(db, other), _status(db, foreign)) == (
        "reviewed", "extraction_completed", "extraction_completed")


def test_empty_selection_approves_nothing(db):
    waiting = _doc(db, "a.pdf")
    result = _bulk_approve(db, {"doc_ids": []})
    assert result["ok"] is False
    assert _status(db, waiting) == "extraction_completed"


def _pending_payload(db, tool_name, arguments):
    from app.api.v1.endpoints.agent import _agent_run_payload

    user = uuid.uuid4()
    conversation = AgentConversation(id=uuid.uuid4(), job_id=JOB, user_id=user)
    run = AgentRun(id=uuid.uuid4(), conversation_id=conversation.id, user_id=user, user_message="go",
                   status="running", created_at=datetime.now(timezone.utc))
    action = AgentPendingAction(id=uuid.uuid4(), conversation_id=conversation.id, user_id=user,
                                tool_name=tool_name, tool_arguments=arguments, status="pending", run_id=run.id)
    db.add_all([conversation, run, action])
    db.commit()
    return _agent_run_payload(db, run)["pending_action"]


def test_confirmation_lists_selected_documents_from_the_job(db):
    a, b = _doc(db, "invoice-a.pdf"), _doc(db, "invoice-b.pdf")
    _doc(db, "not-selected.pdf")
    foreign = _doc(db, "other-job.pdf", job_id=OTHER_JOB)
    pending = _pending_payload(db, "bulk_approve", {"doc_ids": [b, a, foreign]})

    assert pending["documents"] == [
        {"id": a, "filename": "invoice-a.pdf", "status": "extraction_completed"},
        {"id": b, "filename": "invoice-b.pdf", "status": "extraction_completed"},
    ]
    assert pending["arguments"] == {"doc_ids": [b, a, foreign]}


def test_confirmation_names_come_from_the_database_not_arguments(db):
    doc_id = _doc(db, "real-name.pdf", status="reviewed")
    pending = _pending_payload(db, "reject_document", {"doc_id": doc_id, "filename": "fake.pdf"})
    assert pending["documents"] == [{"id": doc_id, "filename": "real-name.pdf", "status": "reviewed"}]


def test_confirmation_for_foreign_or_unrelated_actions(db):
    foreign = _doc(db, "other-job.pdf", job_id=OTHER_JOB)
    assert _pending_payload(db, "approve_document", {"doc_id": foreign})["documents"] == []
    assert "documents" not in _pending_payload(db, "delete_file", {"path": "outputs/x.csv"})
