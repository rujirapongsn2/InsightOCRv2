"""Panel clicks are structured messages checked by the server, and panel status lives on the server.

Covers: the ui-actions endpoint's checks, the display text in the chat and the
title, the action the model reads, supersede/answer transitions, message
paging, and migration 0031's conversion of legacy text-encoded clicks.
"""
import asyncio
import importlib.util
import json
import pkgutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
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


import app.agent.loop as loop_mod  # noqa: E402 — registers every agent tool
from app.agent.context import AgentContext  # noqa: E402
from app.agent.tools.registry import tool_registry  # noqa: E402
from app.api.v1.endpoints import agent as agent_api  # noqa: E402
from app.crud.crud_agent_surface import agent_surface  # noqa: E402
from app.models.agent_conversation import AgentConversation  # noqa: E402
from app.models.agent_message import AgentMessage  # noqa: E402
from app.models.agent_pending_action import AgentPendingAction  # noqa: E402
from app.models.agent_run import AgentRun  # noqa: E402
from app.models.agent_surface import AgentSurface  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.schemas.agent import AgentUiActionCreate  # noqa: E402

JOB = uuid.UUID("6f1c2d3e-0000-4000-8000-000000000001")
USER = SimpleNamespace(id=uuid.UUID("6f1c2d3e-0000-4000-8000-0000000000aa"))
FIXTURES = Path(__file__).resolve().parents[2] / "frontend" / "test" / "fixtures" / "a2ui"
TABLES = [AgentConversation, AgentMessage, AgentRun, AgentSurface, AgentPendingAction, Document]


def _load_migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0031_agent_ui_actions.py"
    spec = importlib.util.spec_from_file_location("migration_0031", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load_migration()


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    Document.metadata.create_all(engine, tables=[model.__table__ for model in TABLES])
    return engine


@pytest.fixture
def db(engine):
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def api(monkeypatch):
    """The endpoints with job access granted and a queue that accepts every task."""
    from app.tasks import agent_tasks

    monkeypatch.setattr(agent_api, "_ensure_job_access", lambda db, job_id, user: None)
    monkeypatch.setattr(agent_tasks.run_agent_task, "delay", lambda run_id: SimpleNamespace(id=f"task-{run_id}"))
    return agent_api


def _conversation(db):
    conversation = AgentConversation(id=uuid.uuid4(), job_id=JOB, user_id=USER.id)
    db.add(conversation)
    db.commit()
    return conversation.id


def _docs(db, *names):
    ids = []
    for name in names:
        doc = Document(id=uuid.uuid4(), job_id=JOB, filename=name, file_path="x", status="extraction_completed")
        db.add(doc)
        ids.append(str(doc.id))
    db.commit()
    return ids


def _panel(db, conversation_id, tool, args):
    context = SimpleNamespace(db=db, job_id=JOB, user_id=USER.id, conversation_id=conversation_id)
    result = asyncio.run(tool_registry.execute(tool, args, context))
    assert result["ok"], result
    return result["panel_id"]


def _documents_panel(db, conversation_id, ids, actions=("approve", "reject")):
    return _panel(db, conversation_id, "show_documents",
                  {"documents": [{"document_id": i} for i in ids], "actions": list(actions)})


def _metrics_panel(db, conversation_id, ids):
    return _panel(db, conversation_id, "show_metrics",
                  {"metrics": [{"label": "ยอดรวม", "kind": "money", "value": 10}], "sources": ids[:1]})


def _status(db, surface_id):
    """The status the server reports for the panel."""
    db.expire_all()
    return agent_surface.states(db, db.get(AgentSurface, surface_id).conversation_id)[surface_id]["status"]


def _click(api, db, conversation_id, surface_id, ids, name="approve_documents", component="approve"):
    data = AgentUiActionCreate(surface_id=surface_id, name=name, source_component_id=component, document_ids=ids)
    response = asyncio.run(api.send_agent_ui_action(conversation_id, data, db=db, current_user=USER))
    return json.loads(response.body)


def _refused(api, db, conversation_id, surface_id, ids, **kwargs):
    with pytest.raises(HTTPException) as refused:
        _click(api, db, conversation_id, surface_id, ids, **kwargs)
    return refused.value.status_code, refused.value.detail


# ── Surface status ─────────────────────────────────────────────────────────

def test_only_a_new_panel_with_buttons_supersedes_panels_with_buttons(db):
    conversation = _conversation(db)
    ids = _docs(db, "a.pdf", "b.pdf")
    listing = _documents_panel(db, conversation, ids)
    metrics = _metrics_panel(db, conversation, ids)
    assert (_status(db, listing), _status(db, metrics)) == ("active", "active")

    newer = _documents_panel(db, conversation, ids)
    assert (_status(db, listing), _status(db, metrics), _status(db, newer)) == ("superseded", "active", "active")
    other = _conversation(db)
    _documents_panel(db, other, ids)
    assert _status(db, newer) == "active"  # another conversation's panel changes nothing here

    surface = db.get(AgentSurface, newer)
    assert surface.actions == [{"component_id": "approve", "name": "approve_documents"},
                               {"component_id": "reject", "name": "reject_documents"}]
    assert surface.document_ids == ids
    assert db.get(AgentSurface, metrics).actions == []


# ── The ui-actions endpoint ────────────────────────────────────────────────

def test_an_accepted_click_answers_its_panel_and_runs_with_the_structured_action(api, db):
    conversation = _conversation(db)
    ids = _docs(db, "a.pdf", "b.pdf", "c.pdf")
    panel = _documents_panel(db, conversation, ids)

    body = _click(api, db, conversation, panel, [ids[1].upper(), ids[0], ids[1]])
    run = db.get(AgentRun, uuid.UUID(body["run"]["id"]))
    assert run.user_message == "อนุมัติเอกสาร 2 รายการที่เลือก"
    assert {k: run.ui_action[k] for k in ("surface_id", "name", "document_ids", "source_component_id")} == {
        "surface_id": panel, "name": "approve_documents", "document_ids": [ids[1], ids[0]],
        "source_component_id": "approve"}
    assert run.ui_action["timestamp"]
    assert _status(db, panel) == "answered"


def test_clicks_the_panel_did_not_offer_are_refused_with_a_reason(api, db):
    conversation, other = _conversation(db), _conversation(db)
    ids = _docs(db, "a.pdf", "b.pdf", "c.pdf")
    foreign = _documents_panel(db, other, ids)
    approve_only = _documents_panel(db, conversation, ids[:2], actions=("approve",))

    assert _refused(api, db, conversation, foreign, ids[:1])[0] == 404
    assert _refused(api, db, conversation, "jobs-unknown", ids[:1])[0] == 404
    code, reason = _refused(api, db, conversation, approve_only, ids[:1], name="reject_documents", component="reject")
    assert code == 422 and "reject_documents" in reason
    assert _refused(api, db, conversation, approve_only, ids[:1], component="reject")[0] == 422
    code, reason = _refused(api, db, conversation, approve_only, [ids[0], ids[2]])
    assert code == 422 and ids[2] in reason
    assert _refused(api, db, conversation, approve_only, ["not-a-uuid"])[0] == 422
    assert _status(db, approve_only) == "active"  # a refused click changes nothing
    assert db.query(AgentRun).count() == 0

    with pytest.raises(ValidationError):
        AgentUiActionCreate(surface_id=approve_only, name="delete_documents", source_component_id="x", document_ids=ids)
    with pytest.raises(ValidationError):
        AgentUiActionCreate(surface_id=approve_only, name="approve_documents", source_component_id="approve",
                            document_ids=[])


def test_answered_and_superseded_panels_refuse_clicks(api, db):
    conversation = _conversation(db)
    ids = _docs(db, "a.pdf", "b.pdf")
    old = _documents_panel(db, conversation, ids)
    current = _documents_panel(db, conversation, ids)
    code, reason = _refused(api, db, conversation, old, ids[:1])
    assert code == 409 and "ไม่ใช่แผงล่าสุด" in reason

    run = uuid.UUID(_click(api, db, conversation, current, ids[:1])["run"]["id"])
    _finish(db, run, "succeeded", confirmation="confirmed")
    code, reason = _refused(api, db, conversation, current, ids[:1])
    assert code == 409 and "ส่งคำสั่งไปแล้ว" in reason


def _finish(db, run_id, status, confirmation=None):
    """End a click's run, after the user answered (or never answered) the request it made."""
    run = db.get(AgentRun, run_id)
    if confirmation is not None:
        db.add(AgentPendingAction(conversation_id=run.conversation_id, user_id=run.user_id, run_id=run.id,
                                  tool_name="bulk_approve", tool_arguments={}, status=confirmation))
    run.status, run.finished_at = status, datetime.now(timezone.utc)
    db.commit()


@pytest.mark.parametrize("status, confirmation", [
    ("failed", None), ("cancelled", None), ("cancelled", "expired"),
    ("succeeded", "rejected"), ("succeeded", "expired"), ("succeeded", None),
])
def test_a_click_whose_run_did_nothing_reopens_its_panel(api, db, status, confirmation):
    conversation = _conversation(db)
    ids = _docs(db, "a.pdf", "b.pdf")
    panel = _documents_panel(db, conversation, ids)
    first = uuid.UUID(_click(api, db, conversation, panel, ids)["run"]["id"])
    assert _status(db, panel) == "answered"

    _finish(db, first, status, confirmation)
    assert _status(db, panel) == "active"
    second = uuid.UUID(_click(api, db, conversation, panel, ids[:1])["run"]["id"])
    assert _status(db, panel) == "answered" and db.get(AgentSurface, panel).answered_by_run_id == second


def test_a_click_whose_action_was_confirmed_keeps_its_panel_answered_even_if_the_run_then_failed(api, db):
    conversation = _conversation(db)
    ids = _docs(db, "a.pdf")
    panel = _documents_panel(db, conversation, ids)
    run = uuid.UUID(_click(api, db, conversation, panel, ids)["run"]["id"])
    _finish(db, run, "failed", confirmation="confirmed")
    assert _status(db, panel) == "answered"
    assert _refused(api, db, conversation, panel, ids)[0] == 409


def test_a_reopened_panel_is_superseded_by_a_newer_panel_with_buttons(api, db):
    conversation = _conversation(db)
    ids = _docs(db, "a.pdf")
    panel = _documents_panel(db, conversation, ids)
    run = uuid.UUID(_click(api, db, conversation, panel, ids)["run"]["id"])
    _documents_panel(db, conversation, ids)  # the click's run showed a fresh panel, then failed
    _finish(db, run, "failed")
    assert _status(db, panel) == "superseded"
    code, reason = _refused(api, db, conversation, panel, ids)
    assert code == 409 and "ไม่ใช่แผงล่าสุด" in reason


def test_a_click_whose_run_cannot_start_leaves_the_panel_usable(api, db, monkeypatch):
    from app.tasks import agent_tasks

    conversation = _conversation(db)
    ids = _docs(db, "a.pdf")
    panel = _documents_panel(db, conversation, ids)

    def queue_down(run_id):
        raise ConnectionError("broker down")

    monkeypatch.setattr(agent_tasks.run_agent_task, "delay", queue_down)
    assert _refused(api, db, conversation, panel, ids)[0] == 503
    assert _status(db, panel) == "active"


# ── What the chat, the title and the model see ─────────────────────────────

def test_the_chat_and_title_show_display_text_and_the_model_reads_the_action(db):
    conversation = _conversation(db)
    ids = _docs(db, "a.pdf", "b.pdf")
    action = {"surface_id": "jobs-abc", "name": "reject_documents", "document_ids": ids,
              "source_component_id": "reject", "timestamp": "2026-10-31T07:05:00+00:00"}
    loop = loop_mod.AgentLoop(db=db, conversation_id=conversation, user_id=USER.id, job_id=JOB,
                              llm_config={}, skip_planning=True)

    async def drain():
        return [event async for event in loop.run("ปฏิเสธเอกสาร 2 รายการที่เลือก", action)]

    asyncio.run(drain())  # no API key: stops right after recording the turn
    db.expire_all()
    message = db.query(AgentMessage).filter(AgentMessage.role == "user").one()
    assert (message.kind, message.content, message.ui_action) == ("ui_action", "ปฏิเสธเอกสาร 2 รายการที่เลือก", action)
    assert db.get(AgentConversation, conversation).title == "ปฏิเสธเอกสาร 2 รายการที่เลือก"

    # SQLite's CURRENT_TIMESTAMP text does not compare with a bound datetime; Postgres has no such gap.
    message.created_at = datetime.now(timezone.utc)
    db.commit()
    history = asyncio.run(AgentContext(db, USER.id, JOB, conversation).load_history())
    seen = history[-1]["content"]
    assert seen.startswith("[ui_action] ")
    assert json.loads(seen.removeprefix("[ui_action] ")) == {
        "surface_id": "jobs-abc", "name": "reject_documents", "document_ids": ids}


def test_a_turn_is_in_the_conversation_once_accepted_and_the_worker_does_not_record_it_again(api, db):
    from app.schemas.agent import AgentMessageCreate
    from app.tasks.agent_tasks import _consume_agent_run

    conversation = _conversation(db)
    ids = _docs(db, "a.pdf", "b.pdf")
    panel = _documents_panel(db, conversation, ids)
    run = db.get(AgentRun, uuid.UUID(_click(api, db, conversation, panel, ids)["run"]["id"]))

    def user_turns():
        body = asyncio.run(api.get_agent_conversation(conversation, before=None, limit=50, db=db, current_user=USER))
        return [(m["kind"], m["content"], m["ui_action"]) for m in body["messages"] if m["role"] == "user"], \
            body["conversation"]["title"]

    turns, title = user_turns()  # before any worker ran
    assert turns == [("ui_action", "อนุมัติเอกสาร 2 รายการที่เลือก", run.ui_action)]
    assert title == "อนุมัติเอกสาร 2 รายการที่เลือก"

    loop = loop_mod.AgentLoop(db=db, conversation_id=conversation, user_id=USER.id, job_id=JOB, llm_config={},
                              skip_planning=True)
    asyncio.run(_consume_agent_run(loop, run.user_message, None, run.ui_action))  # no API key: stops at once
    assert user_turns()[0] == turns

    _finish(db, run.id, "succeeded", confirmation="confirmed")
    asyncio.run(api.send_agent_message(conversation, AgentMessageCreate(content="สรุปยอดรวม"), db=db,
                                       current_user=USER))
    after, title = user_turns()
    # SQLite stamps both turns in the same second, so their order here is not the point.
    assert sorted(after, key=str) == sorted(turns + [("text", "สรุปยอดรวม", None)], key=str)
    assert title == "สรุปยอดรวม"


# ── Paging ─────────────────────────────────────────────────────────────────

def test_paging_walks_back_through_history_and_statuses_do_not_depend_on_the_page(api, db):
    conversation = _conversation(db)
    ids = _docs(db, "a.pdf")
    first_panel = _documents_panel(db, conversation, ids)
    _documents_panel(db, conversation, ids)
    start = datetime(2026, 10, 31, 7, 0, tzinfo=timezone.utc)
    messages = [AgentMessage(id=uuid.uuid4(), conversation_id=conversation, role="user", content=f"m{n}",
                             created_at=start + timedelta(minutes=n // 2)) for n in range(7)]
    db.add_all(messages)
    db.commit()

    def page(before=None):
        return asyncio.run(api.get_agent_conversation(conversation, before=before, limit=3, db=db, current_user=USER))

    seen, before, surfaces = [], None, []
    while True:
        body = page(before)
        seen = [m["content"] for m in body["messages"]] + seen
        surfaces.append(body["surfaces"])
        if not body["has_more"]:
            break
        before = uuid.UUID(body["messages"][0]["id"])
    assert sorted(seen) == [f"m{n}" for n in range(7)] and len(set(seen)) == 7  # none skipped or repeated
    assert len(surfaces) == 3 and all(s == surfaces[0] for s in surfaces)
    assert surfaces[0][first_panel]["status"] == "superseded" and surfaces[0][first_panel]["actionable"] is True
    assert surfaces[0][first_panel]["generated_at"]
    assert page()["messages"][-1]["kind"] == "text"


# ── Migration 0031 ─────────────────────────────────────────────────────────

LEGACY_IDS = ["9c1d1a52-0000-4000-8000-000000000001", "9c1d1a52-0000-4000-8000-000000000002"]


def _legacy_content(surface_id):
    """What the phase-A frontend sent for a click (actionMessage)."""
    action = {"name": "approve_documents", "surfaceId": surface_id, "sourceComponentId": "approve",
              "timestamp": "2026-10-30T09:00:00.000Z", "context": {"document_ids": LEGACY_IDS}}
    return f"อนุมัติเอกสาร 2 รายการที่เลือก\n\n```a2ui-action\n{json.dumps(action)}\n```"


def test_legacy_action_parses_the_text_encoding_and_ignores_ordinary_text():
    display, action = migration.legacy_action(_legacy_content("jobs-1"))
    assert display == "อนุมัติเอกสาร 2 รายการที่เลือก"
    assert action == {"surface_id": "jobs-1", "name": "approve_documents", "document_ids": LEGACY_IDS,
                      "source_component_id": "approve", "timestamp": "2026-10-30T09:00:00.000Z"}
    assert migration.legacy_action("สรุปยอดรวม") is None
    assert migration.legacy_action("x\n\n```a2ui-action\nnot json\n```") is None
    assert migration.legacy_action(migration.legacy_text(display, action)) == (display, action)


def _seed_legacy(db):
    """A phase-A conversation: two document panels, a click on the second, a third document panel, metrics last."""
    conversation = _conversation(db)
    fixture = json.loads((FIXTURES / "show_documents.json").read_text())["result"]
    t0 = datetime(2026, 10, 30, 9, 0, tzinfo=timezone.utc)

    def panel(surface_id, minutes, tool="show_documents", result=None):
        result = json.loads(json.dumps(result or fixture).replace(fixture["panel_id"], surface_id))
        db.add(AgentMessage(id=uuid.uuid4(), conversation_id=conversation, role="tool", tool_name=tool,
                            tool_result=result, created_at=t0 + timedelta(minutes=minutes)))

    panel("jobs-old", 0)
    panel("jobs-clicked", 1)
    content = _legacy_content("jobs-clicked")
    db.add(AgentMessage(id=uuid.uuid4(), conversation_id=conversation, role="user", content=content,
                        created_at=t0 + timedelta(minutes=2)))
    db.add(AgentMessage(id=uuid.uuid4(), conversation_id=conversation, role="user", content="สรุปยอดรวม",
                        created_at=t0 + timedelta(minutes=3)))
    panel("jobs-pending", 3.5)
    metrics = json.loads((FIXTURES / "show_metrics.json").read_text())["result"]
    panel("jobs-metrics", 4, "show_metrics", {**metrics, "panel_id": "x"})
    db.add(AgentRun(id=uuid.uuid4(), conversation_id=conversation, user_id=USER.id, user_message=content,
                    status="succeeded"))
    db.get(AgentConversation, conversation).title = content[:60]
    db.commit()
    return conversation, metrics["panel_id"]


def _snapshot(db):
    db.expire_all()
    return (sorted((m.kind, m.content, json.dumps(m.ui_action, sort_keys=True)) for m in db.query(AgentMessage)
                   if m.role == "user"),
            [(r.user_message, r.ui_action) for r in db.query(AgentRun)],
            [c.title for c in db.query(AgentConversation)],
            sorted((s.surface_id, s.status, json.dumps(s.actions), json.dumps(s.document_ids))
                   for s in db.query(AgentSurface)))


def test_migration_converts_legacy_clicks_fixes_titles_and_backfills_statuses(engine, db):
    conversation, metrics_id = _seed_legacy(db)
    with engine.begin() as connection:
        migration.upgrade_data(connection)
    after = _snapshot(db)

    click = db.query(AgentMessage).filter(AgentMessage.kind == "ui_action").one()
    assert click.content == "อนุมัติเอกสาร 2 รายการที่เลือก" and "```" not in click.content
    assert click.ui_action["surface_id"] == "jobs-clicked" and click.ui_action["document_ids"] == LEGACY_IDS
    assert db.query(AgentMessage).filter(AgentMessage.content == "สรุปยอดรวม").one().kind == "text"
    run = db.query(AgentRun).one()
    assert run.user_message == click.content and run.ui_action == click.ui_action
    assert db.get(AgentConversation, conversation).title == "อนุมัติเอกสาร 2 รายการที่เลือก"

    statuses = {s.surface_id: s.status for s in db.query(AgentSurface)}
    assert statuses == {"jobs-old": "superseded", "jobs-clicked": "answered", "jobs-pending": "active",
                        metrics_id: "active"}
    clicked = db.get(AgentSurface, "jobs-clicked")
    assert [a["name"] for a in clicked.actions] == ["approve_documents", "reject_documents"]
    assert clicked.document_ids and db.get(AgentSurface, metrics_id).document_ids == []

    with engine.begin() as connection:
        migration.upgrade_data(connection)
    assert _snapshot(db) == after  # idempotent


def test_migration_downgrade_restores_the_text_encoding(engine, db):
    _seed_legacy(db)
    with engine.begin() as connection:
        migration.upgrade_data(connection)
        migration.downgrade_data(connection)
    db.expire_all()
    restored = [m.content for m in db.query(AgentMessage) if m.role == "user" and "```" in (m.content or "")]
    assert len(restored) == 1
    display, action = migration.legacy_action(restored[0])
    assert display == "อนุมัติเอกสาร 2 รายการที่เลือก" and action["surface_id"] == "jobs-clicked"
