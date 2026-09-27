"""Agent tool fixes: paged reads, binary files via the sandbox, skill parts, rollback,
pending actions, field updates, web search and job-scoped skill files."""
import asyncio
import importlib
import pkgutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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


from app.models.agent_pending_action import AgentPendingAction
from app.models.agent_run import AgentRun
from app.models.document import Document
from app.models.schema import DocumentSchema


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    tables = [AgentPendingAction.__table__, AgentRun.__table__, Document.__table__, DocumentSchema.__table__]
    AgentRun.metadata.create_all(engine, tables=tables)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class FakeStorage:
    def __init__(self, files):
        self.files = files
        self.uploaded = {}

    def exists(self, key):
        return key in self.files

    @contextmanager
    def get_local_path(self, key):
        import tempfile, os
        handle = tempfile.NamedTemporaryFile(delete=False, suffix="-" + key.rsplit("/", 1)[-1])
        handle.write(self.files[key])
        handle.close()
        try:
            yield handle.name
        finally:
            os.unlink(handle.name)

    def upload_file(self, file_obj, key, content_type=None):
        self.uploaded[key] = file_obj.read()


JOB = uuid.uuid4()


def _ctx(**extra):
    return SimpleNamespace(job_id=JOB, user_id=uuid.uuid4(), db=None, **extra)


def test_read_file_pages_long_text(monkeypatch):
    from app.agent.tools import filesystem_tools as fs

    text = "".join(f"line {i}\n" for i in range(5000))
    storage = FakeStorage({f"jobs/{JOB}/outputs/big.txt": text.encode()})
    monkeypatch.setattr(fs, "get_storage_service", lambda: storage)

    first = asyncio.run(fs._read_file_handler({"path": "outputs/big.txt"}, _ctx()))
    assert len(first["content"]) == fs.READ_WINDOW_CHARS and first["complete"] is False
    second = asyncio.run(fs._read_file_handler({"path": "outputs/big.txt", "offset": first["next_offset"]}, _ctx()))
    assert second["content"].startswith(text[first["next_offset"]:first["next_offset"] + 20])
    assert asyncio.run(fs._read_file_handler({"path": "outputs/big.txt", "max_size": 10**9}, _ctx()))["total_chars"] == len(text)


def test_binary_files_are_never_sent_to_the_model_as_base64(monkeypatch):
    from app.agent.tools import filesystem_tools as fs

    storage = FakeStorage({f"jobs/{JOB}/outputs/report.xlsx": b"PK\x03\x04" + b"x" * 300_000})
    monkeypatch.setattr(fs, "get_storage_service", lambda: storage)
    result = asyncio.run(fs._read_file_handler({"path": "outputs/report.xlsx", "return_base64": True}, _ctx()))
    assert "content_base64" not in result and "input_files" in result["note"]


def test_input_files_are_loaded_from_the_job_with_limits(monkeypatch):
    from app.agent.tools import code_tools

    storage = FakeStorage({f"jobs/{JOB}/outputs/report.xlsx": b"xlsx-bytes"})
    monkeypatch.setattr(code_tools, "get_storage_service", lambda: storage)
    files, error = code_tools._load_input_files(["outputs/report.xlsx"], _ctx())
    assert error is None and files == {"report.xlsx": b"xlsx-bytes"}
    assert code_tools._load_input_files(["outputs/missing.xlsx"], _ctx())[1] == "File not found: outputs/missing.xlsx"
    assert "Job" in code_tools._load_input_files(["a.xlsx"], SimpleNamespace(job_id=None))[1]
    assert code_tools._load_input_files(["../other/secret.xlsx"], _ctx())[1]


def test_long_skill_procedures_are_served_in_parts(monkeypatch):
    from app.agent.tools import skill_tools

    procedure = "".join(f"Step {i}: do something important.\n" for i in range(700))
    skill = SimpleNamespace(id=uuid.uuid4(), name="audit", scope="user", description="d", procedure=procedure,
                            allowed_tools=None, compatibility=None, metadata_=None, source="db", file_path=None)
    monkeypatch.setattr(skill_tools.crud_skill, "get_by_name", lambda db, **k: skill)
    used = []
    monkeypatch.setattr(skill_tools.crud_skill, "increment_usage", lambda db, skill_id: used.append(skill_id))
    ctx = SimpleNamespace(db=None, user_id=uuid.uuid4(), current_request="run the audit")

    first = asyncio.run(skill_tools._execute_skill_handler({"name": "audit"}, ctx))
    parts = first["procedure_parts"]
    assert parts > 1 and "procedure" not in first and "part=2" in first["instruction"]
    last = asyncio.run(skill_tools._execute_skill_handler({"name": "audit", "part": parts}, ctx))
    assert "Step 699" in last["instruction"] and "part=" not in last["instruction"].split("Procedure")[1].split("Follow")[0][-40:]
    assert len(used) == 1  # counted once per activation


def test_failed_tool_rolls_back_the_shared_session():
    from app.agent.tools.registry import ToolDef, ToolRegistry

    registry = ToolRegistry()

    async def broken(args, context):
        raise RuntimeError("current transaction is aborted")

    registry.register(ToolDef(name="broken", category="document", description="", parameters_schema={}, handler=broken))
    rolled_back = []
    ctx = SimpleNamespace(db=SimpleNamespace(rollback=lambda: rolled_back.append(True)), active_skill_allowed_tools=None)
    result = asyncio.run(registry.execute("broken", {}, ctx))
    assert "RuntimeError" in result["error"] and rolled_back == [True]


def test_missing_search_library_is_a_failed_tool(monkeypatch):
    import builtins
    from app.agent.tools import web_search_tools

    real_import = builtins.__import__

    def no_ddgs(name, *args, **kwargs):
        if name in {"ddgs", "duckduckgo_search"}:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_ddgs)
    result = asyncio.run(web_search_tools._web_search_handler({"query": "thai vat"}, None))
    assert result["unavailable"] is True and "not available" in result["error"]


def test_pending_action_answers_cannot_overwrite_each_other(db):
    from app.crud.crud_agent_pending import agent_pending

    action = agent_pending.create(db, conversation_id=uuid.uuid4(), user_id=uuid.uuid4(),
                                  tool_name="approve_document", tool_arguments={})
    assert agent_pending.resolve(db, action.id, "confirmed") is True
    assert agent_pending.resolve(db, action.id, "rejected") is False  # the late timeout loses
    db.expire_all()
    assert agent_pending.get(db, action.id).status == "confirmed"


def test_a_run_only_shows_its_own_pending_request(db):
    from app.api.v1.endpoints.agent import _agent_run_payload

    conversation, user = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    old = AgentPendingAction(id=uuid.uuid4(), conversation_id=conversation, user_id=user, tool_name="send_to_workflow",
                             tool_arguments={}, status="pending", created_at=now - timedelta(hours=1))
    run = AgentRun(id=uuid.uuid4(), conversation_id=conversation, user_id=user, user_message="hi",
                   status="running", created_at=now)
    db.add_all([old, run])
    db.commit()
    assert _agent_run_payload(db, run)["pending_action"] is None
    run.status = "succeeded"
    assert _agent_run_payload(db, run)["pending_action"] is None


def _document(db, data, schema_fields=None):
    schema = None
    if schema_fields is not None:
        schema = DocumentSchema(id=uuid.uuid4(), name="Invoice", document_type="invoice",
                                fields=[{"name": name, "type": "text"} for name in schema_fields])
        db.add(schema)
    doc = Document(id=uuid.uuid4(), job_id=JOB, filename="a.pdf", file_path="x", extracted_data=data,
                   schema_id=schema.id if schema else None)
    db.add(doc)
    db.commit()
    return doc


def test_update_field_rejects_unknown_fields_and_handles_records(db):
    from app.agent.tools.document_tools import _update_document_field_handler

    ctx = SimpleNamespace(db=db, job_id=JOB)
    doc = _document(db, {"invoice_no": "INV-1"}, ["invoice_no", "total"])
    bad = asyncio.run(_update_document_field_handler({"doc_id": str(doc.id), "field": "invoce_no", "value": "X"}, ctx))
    assert "not a field" in bad["error"]
    ok = asyncio.run(_update_document_field_handler({"doc_id": str(doc.id), "field": "total", "value": 10}, ctx))
    assert ok["verified"] is True

    multi = _document(db, [{"party": "A"}, {"party": "B"}])
    need_index = asyncio.run(_update_document_field_handler({"doc_id": str(multi.id), "field": "party", "value": "C"}, ctx))
    assert "record_index" in need_index["error"]
    done = asyncio.run(_update_document_field_handler(
        {"doc_id": str(multi.id), "field": "party", "value": "C", "record_index": 1}, ctx))
    assert done["verified"] is True and db.get(Document, multi.id).reviewed_data[1]["party"] == "C"
    negative = asyncio.run(_update_document_field_handler(
        {"doc_id": str(multi.id), "field": "party", "value": "Z", "record_index": -1}, ctx))
    assert "record_index must be between" in negative["error"]
    assert "not a valid document id" in asyncio.run(_update_document_field_handler(
        {"doc_id": "abc", "field": "party", "value": 1}, ctx))["error"]


def test_skill_files_stay_inside_the_job(monkeypatch):
    from app.agent.tools import skill_tools

    assert skill_tools._job_scoped_path(SimpleNamespace(job_id=None), "SKILL.md")[1]
    assert skill_tools._job_scoped_path(_ctx(), "../../etc/passwd")[1]
    result = asyncio.run(skill_tools._import_skill_handler({"file_path": "/etc/passwd"}, _ctx()))
    assert "error" in result
    storage = FakeStorage({})
    monkeypatch.setattr("app.services.storage.get_storage_service", lambda: storage)
    written = skill_tools._write_job_file(_ctx(), "outputs/SKILL.md", b"# skill", "text/markdown")
    assert written["ok"] and list(storage.uploaded) == [f"jobs/{JOB}/outputs/SKILL.md"]


SKILL_MD = b"""---
name: invoice-check
description: Check invoice totals against line items.
license: MIT
---
# Steps
1. Read the invoice.
2. Compare totals.
"""


def test_import_skill_succeeds_and_overwrite_keeps_the_skill(monkeypatch):
    from app.agent.tools import skill_tools

    storage = FakeStorage({f"jobs/{JOB}/outputs/SKILL.md": SKILL_MD})
    monkeypatch.setattr("app.services.storage.get_storage_service", lambda: storage)
    created = []
    monkeypatch.setattr(skill_tools.crud_skill, "get_by_name", lambda db, **k: None)
    monkeypatch.setattr(skill_tools.crud_skill, "create",
                        lambda db, **k: created.append(k) or SimpleNamespace(id=uuid.uuid4(), scope="user", created_by="imported", source="imported", **{
                            key: k[key] for key in ("name", "description")}))
    ctx = SimpleNamespace(job_id=JOB, user_id=uuid.uuid4(), db=None)
    result = asyncio.run(skill_tools._import_skill_handler({"file_path": "outputs/SKILL.md"}, ctx))
    assert result.get("ok"), result
    assert created[0]["file_path"] == "outputs/SKILL.md" and "Compare totals" in created[0]["procedure"]

    existing = SimpleNamespace(id=uuid.uuid4(), name="invoice-check", scope="user", created_by="user",
                               description="old", procedure="old steps", license="old-license")
    committed = []
    db = SimpleNamespace(commit=lambda: committed.append(True), refresh=lambda obj: None, rollback=lambda: None)
    monkeypatch.setattr(skill_tools.crud_skill, "get_by_name", lambda db, **k: existing)
    monkeypatch.setattr(skill_tools.crud_skill, "delete_by_id", lambda *a: pytest.fail("must not delete the old skill"))
    replaced = asyncio.run(skill_tools._import_skill_handler({"file_path": "outputs/SKILL.md", "overwrite": True},
                                                             SimpleNamespace(job_id=JOB, user_id=uuid.uuid4(), db=db)))
    assert replaced["replaced"] is True and replaced["id"] == str(existing.id)
    assert "Compare totals" in existing.procedure and committed
    assert existing.license == "MIT" and not hasattr(existing, "license_")  # the real column is updated


def test_requests_left_by_a_run_are_expired_and_never_shown_to_the_next(db):
    from app.api.v1.endpoints.agent import _agent_run_payload
    from app.crud.crud_agent_pending import agent_pending

    conversation, user = uuid.uuid4(), uuid.uuid4()
    old_run = AgentRun(id=uuid.uuid4(), conversation_id=conversation, user_id=user, user_message="a", status="cancelled")
    new_run = AgentRun(id=uuid.uuid4(), conversation_id=conversation, user_id=user, user_message="b", status="running",
                       created_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    db.add_all([old_run, new_run])
    db.commit()
    # The stopped run's worker still created a request after the new run started.
    late = agent_pending.create(db, conversation_id=conversation, user_id=user, tool_name="approve_document",
                                tool_arguments={}, run_id=old_run.id)
    assert _agent_run_payload(db, new_run)["pending_action"] is None
    own = agent_pending.create(db, conversation_id=conversation, user_id=user, tool_name="approve_document",
                               tool_arguments={}, run_id=new_run.id)
    assert _agent_run_payload(db, new_run)["pending_action"]["pending_action_id"] == str(own.id)
    assert agent_pending.expire_for_run(db, old_run.id) == 1
    db.expire_all()
    assert agent_pending.get(db, late.id).status == "rejected" and agent_pending.get(db, own.id).status == "pending"


def test_a_stopped_run_rejects_its_waiting_approval(monkeypatch):
    from app.agent import loop as loop_module

    loop = loop_module.AgentLoop.__new__(loop_module.AgentLoop)
    loop.run_id = uuid.uuid4()
    resolved = []
    loop.db = SimpleNamespace(rollback=lambda: None, expire_all=lambda: None)
    monkeypatch.setattr(loop_module.AgentLoop, "_run_active", lambda self: False)
    monkeypatch.setattr(loop_module.crud_pending, "resolve", lambda db, pid, status: resolved.append(status) or True)
    assert asyncio.run(loop._wait_for_confirmation(uuid.uuid4(), timeout_s=5)) is False
    assert resolved == ["rejected"]


# ── Group 3: honest results, no duplicates, safe errors, history ──────────────

from app.models.agent_message import AgentMessage
from app.models.workflow import Workflow


@pytest.fixture
def db3():
    engine = create_engine("sqlite://")
    AgentRun.metadata.create_all(engine, tables=[Document.__table__, DocumentSchema.__table__,
                                                 AgentMessage.__table__, Workflow.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_repeated_decisions_change_nothing_and_reversals_need_consent(db3, monkeypatch):
    from app.agent.tools import document_tools

    logged = []
    monkeypatch.setattr(document_tools, "log_activity", lambda *a, **k: logged.append(k))
    ctx = SimpleNamespace(db=db3, job_id=JOB, user_id=uuid.uuid4())
    doc = _document(db3, {"total": 1})
    first = asyncio.run(document_tools._approve_document_handler({"doc_id": str(doc.id)}, ctx))
    again = asyncio.run(document_tools._approve_document_handler({"doc_id": str(doc.id)}, ctx))
    assert first["verified"] and again["unchanged"] is True and len(logged) == 1

    assert db3.get(Document, doc.id).review_decision == "confirmed"  # same value as the review page
    refused = asyncio.run(document_tools._reject_document_handler({"doc_id": str(doc.id)}, ctx))
    assert refused["ok"] is False and refused["current_decision"] == "confirmed"
    reversed_ = asyncio.run(document_tools._reject_document_handler(
        {"doc_id": str(doc.id), "reverse_previous_decision": True}, ctx))
    saved = db3.get(Document, doc.id)
    assert reversed_["changed_from"] == "confirmed" and (saved.status, saved.review_decision) == ("rejected", "rejected")
    again = asyncio.run(document_tools._reject_document_handler({"doc_id": str(doc.id)}, ctx))
    assert again["unchanged"] is True and again["status"] == "rejected"  # reports the real status

    legacy = _document(db3, {"total": 2})
    legacy.status, legacy.review_decision = "reviewed", "approved"  # written by the old agent
    db3.commit()
    assert asyncio.run(document_tools._approve_document_handler({"doc_id": str(legacy.id)}, ctx))["unchanged"] is True


def test_bulk_approve_with_nothing_waiting_is_not_a_success(db3):
    from app.agent.tools import document_tools

    ctx = SimpleNamespace(db=db3, job_id=JOB, user_id=uuid.uuid4())
    result = asyncio.run(document_tools._bulk_approve_handler({}, ctx))
    assert result["ok"] is False and result["nothing_to_approve"] is True


def test_saving_the_same_workflow_twice_returns_the_first(db3):
    from app.agent.tools import workflow_tools

    owner = uuid.uuid4()
    definition = {"nodes": [{"id": "n1"}], "edges": []}
    first = Workflow(id=uuid.uuid4(), name="Daily", definition=definition, user_id=owner,
                     created_at=datetime.now(timezone.utc))
    db3.add(first)
    db3.commit()
    assert workflow_tools._recent_duplicate_workflow(db3, owner, "Daily", definition).id == first.id
    assert workflow_tools._recent_duplicate_workflow(db3, owner, "Daily", {"nodes": [], "edges": []}) is None
    assert workflow_tools._recent_duplicate_workflow(db3, uuid.uuid4(), "Daily", definition) is None
    # Saving again with a schedule is a change, not a retry.
    assert workflow_tools._recent_duplicate_workflow(db3, owner, "Daily", definition, schedule_cron="0 8 * * *",
                                                     schedule_enabled=True) is None


@pytest.mark.parametrize("error,expected", [
    (type("AuthenticationError", (Exception,), {"status_code": 401})("Incorrect API key provided: sk-abc...xyz"), "credentials"),
    (type("RateLimitError", (Exception,), {"status_code": 429})("Rate limit reached for org-123"), "limiting"),
    (TimeoutError("Request timed out"), "did not answer in time"),
    (RuntimeError("Selected AI provider rejected the request because the prompt (~900,000 characters) exceeds the model's context window."), "too long"),
    (type("APIConnectionError", (Exception,), {})("Connection error to https://10.0.0.5:8443/v1"), "Could not reach"),
])
def test_provider_errors_are_explained_without_leaking_details(error, expected):
    from app.agent.loop import _user_facing_llm_error

    message = _user_facing_llm_error(error)
    assert expected in message
    assert "sk-abc" not in message and "10.0.0.5" not in message and "org-123" not in message


def test_context_overflow_keeps_the_latest_turn_and_shortens_tool_results():
    from app.agent.loop import _compact_for_context

    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current question"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "x" * 10_000},
    ]
    compacted = _compact_for_context(messages)
    assert [m["role"] for m in compacted] == ["system", "user", "assistant", "tool"]
    assert compacted[1]["content"] == "current question"
    assert len(compacted[3]["content"]) < 2000
    assert _compact_for_context([{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]) is None


def test_history_is_counted_in_user_turns(db3):
    from app.crud.crud_agent_conversation import agent_conversation

    conversation = uuid.uuid4()
    start = datetime.now(timezone.utc) - timedelta(hours=1)
    rows = []
    for turn in range(8):
        rows.append(("user", f"question {turn}"))
        rows += [("tool", "result")] * 15  # a tool-heavy answer
        rows.append(("assistant", f"answer {turn}"))
    for offset, (role, content) in enumerate(rows):
        db3.add(AgentMessage(id=uuid.uuid4(), conversation_id=conversation, role=role, content=content,
                             created_at=start + timedelta(seconds=offset)))
    db3.commit()
    messages = agent_conversation.get_recent_turns(db3, conversation, turns=3, max_messages=500)
    users = [m.content for m in messages if m.role == "user"]
    assert users == ["question 5", "question 6", "question 7"]


def test_agent_runtime_is_capped_below_the_worker_limit():
    from app.agent import loop

    assert loop.AGENT_MAX_RUNTIME_S <= loop.AGENT_MAX_RUNTIME_CEILING_S < 1800


def test_a_stopped_run_cannot_start_another_tool():
    from app.agent.tools.registry import ToolDef, ToolRegistry

    registry = ToolRegistry()
    ran = []

    async def write(args, context):
        ran.append(True)
        return {"ok": True}

    registry.register(ToolDef(name="write_file", category="filesystem", description="", parameters_schema={}, handler=write))
    ctx = SimpleNamespace(db=None, active_skill_allowed_tools=None, run_active_check=lambda: False)
    result = asyncio.run(registry.execute("write_file", {}, ctx))
    assert result["run_stopped"] is True and ran == []


def test_conversation_stays_locked_until_the_stopped_worker_finishes(db, monkeypatch):
    from fastapi import HTTPException
    from app.api.v1.endpoints import agent as endpoint
    from app.tasks.maintenance_tasks import _reconcile_agent_runs

    user = SimpleNamespace(id=uuid.uuid4())
    conversation = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, job_id=None)
    run = AgentRun(id=uuid.uuid4(), conversation_id=conversation.id, user_id=user.id, user_message="hi",
                   status="running", task_id="t1", created_at=datetime.now(timezone.utc))
    db.add(run)
    db.commit()
    monkeypatch.setattr(endpoint.crud_conv, "get", lambda db, cid: conversation)
    monkeypatch.setattr("app.celery_app.celery_app.control.revoke", lambda *a, **k: None)

    stopped = asyncio.run(endpoint.cancel_agent_run(conversation.id, run.id, db=db, current_user=user))
    assert stopped["run"]["status"] == "cancelled" and db.get(AgentRun, run.id).finished_at is None
    with pytest.raises(HTTPException) as blocked:
        asyncio.run(endpoint.send_agent_message(conversation.id, SimpleNamespace(content="again"), db=db, current_user=user))
    assert blocked.value.status_code == 409

    # Queued for long but started recently: still locked (age counts from the start).
    db.get(AgentRun, run.id).created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.get(AgentRun, run.id).started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    assert _reconcile_agent_runs(db, datetime.now(timezone.utc)) == 0
    # A worker that never reports back is released by maintenance.
    db.get(AgentRun, run.id).started_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()
    assert _reconcile_agent_runs(db, datetime.now(timezone.utc)) == 1
    db.commit()
    assert db.get(AgentRun, run.id).finished_at is not None
