"""Agent DOC reliability: interrupted/stuck runs, Stop, integration scoping, non-blocking sandbox."""
import asyncio
import importlib
import pkgutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models

for _module in pkgutil.iter_modules(app.models.__path__):
    importlib.import_module(f"app.models.{_module.name}")

from app.models.agent_run import AgentRun


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    AgentRun.metadata.create_all(engine, tables=[AgentRun.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _run(db, status="running", task_id="task-1", started=None, created=None):
    run = AgentRun(id=uuid.uuid4(), conversation_id=uuid.uuid4(), user_id=uuid.uuid4(), user_message="hi",
                   status=status, task_id=task_id, started_at=started, created_at=created)
    db.add(run)
    db.commit()
    return run


def test_redelivered_task_ends_the_interrupted_run_instead_of_rerunning(db, monkeypatch):
    from app.tasks import agent_tasks

    run = _run(db, status="running", task_id="task-1", started=datetime.now(timezone.utc))
    monkeypatch.setattr(agent_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(agent_tasks, "AgentLoop", lambda **k: pytest.fail("must not run the agent again"))

    agent_tasks.run_agent_task.push_request(id="task-1")
    try:
        agent_tasks.run_agent_task.run(str(run.id))
    finally:
        agent_tasks.run_agent_task.pop_request()

    db.refresh(run)
    assert run.status == "failed" and "worker restarted" in run.error


def test_another_tasks_duplicate_leaves_a_live_run_alone(db, monkeypatch):
    from app.tasks import agent_tasks

    run = _run(db, status="running", task_id="task-1", started=datetime.now(timezone.utc))
    monkeypatch.setattr(agent_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    agent_tasks.run_agent_task.push_request(id="other-task")
    try:
        agent_tasks.run_agent_task.run(str(run.id))
    finally:
        agent_tasks.run_agent_task.pop_request()
    db.refresh(run)
    assert run.status == "running"


class _SlowLoop:
    async def run(self, _message):
        for index in range(50):
            await asyncio.sleep(0)
            yield f'data: {{"type":"thinking","iteration":{index}}}\n\n'
        yield 'data: {"type":"done","success":true}\n\n'


@pytest.mark.asyncio
async def test_stop_is_noticed_between_steps(monkeypatch):
    from app.tasks import agent_tasks

    monkeypatch.setattr(agent_tasks, "CANCEL_CHECK_SECONDS", 0.0)
    monkeypatch.setattr(agent_tasks, "_run_status", lambda run_id: "cancelled")
    completed, error = await agent_tasks._consume_agent_run(_SlowLoop(), "hi", "run-1")
    assert completed is None and error is None


def test_reaper_fails_stuck_runs_only(db):
    from app.tasks.maintenance_tasks import _reconcile_agent_runs

    now = datetime.now(timezone.utc)
    stuck = _run(db, status="running", started=now - timedelta(hours=2))
    live = _run(db, status="running", started=now - timedelta(minutes=5))
    lost = _run(db, status="queued", task_id=None, created=now - timedelta(hours=3))
    waiting = _run(db, status="queued", task_id=None, created=now - timedelta(minutes=2))

    assert _reconcile_agent_runs(db, now) == 2
    db.commit()
    statuses = {run.id: db.get(AgentRun, run.id).status for run in (stuck, live, lost, waiting)}
    assert statuses == {stuck.id: "failed", live.id: "running", lost.id: "failed", waiting.id: "queued"}


def _integration(name, owner, itype="api"):
    return SimpleNamespace(id=uuid.uuid4(), name=name, user_id=owner, type=itype, status="active",
                           description=None, config={"baseUrl": "https://erp.invalid", "authHeader": "Authorization: secret"})


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *args):
        return self

    def all(self):
        return self.rows


def test_integrations_of_other_users_are_invisible(monkeypatch):
    from app.agent.tools import integration_tools as tools

    me, other = uuid.uuid4(), uuid.uuid4()
    mine = _integration("ERP", me)
    theirs = _integration("ERP", other)
    stranger = _integration("CRM", other)
    db = SimpleNamespace(query=lambda model: _FakeQuery([theirs, mine, stranger]))
    monkeypatch.setattr(tools.crud_integration, "get",
                        lambda db, integration_id: next(i for i in (mine, theirs, stranger) if str(i.id) == str(integration_id)))

    assert tools._find_integration(db, me, integration_name="erp") is mine  # never the other user's "ERP"
    assert tools._find_integration(db, me, integration_name="CRM") is None
    assert tools._find_integration(db, me, integration_id=str(stranger.id)) is None
    listed = asyncio.run(tools._list_integrations_handler({}, SimpleNamespace(db=db, user_id=me)))
    assert [item["id"] for item in listed["integrations"]] == [str(mine.id)]
    assert "config" not in listed["integrations"][0]


def test_calling_another_users_integration_by_id_fails(monkeypatch):
    from app.agent.tools import integration_tools as tools

    theirs = _integration("ERP", uuid.uuid4())
    monkeypatch.setattr(tools.crud_integration, "get", lambda db, integration_id: theirs)
    result = asyncio.run(tools._call_api_integration_handler(
        {"integration_id": str(theirs.id), "path": "/stock"}, SimpleNamespace(db=None, user_id=uuid.uuid4())))
    assert result["error"].startswith("Integration not found")


def test_one_list_tool_serves_both_agents_and_duplicates_are_refused():
    from app.agent.tools.registry import ToolDef, tool_registry
    import app.agent.tools.workflow_tools  # noqa: F401 — registers the workflow tools too

    workflow_tools = {s["function"]["name"] for s in tool_registry.get_openai_schemas(categories=["workflow", "web"])}
    assert "list_integrations" in workflow_tools and "call_api_integration" not in workflow_tools
    with pytest.raises(ValueError):
        tool_registry.register(ToolDef(name="list_integrations", category="workflow", description="x",
                                       parameters_schema={}, handler=lambda args, context: None))


@pytest.mark.asyncio
async def test_sandbox_runs_docker_off_the_event_loop(monkeypatch):
    from app.services import code_sandbox

    monkeypatch.setattr(code_sandbox, "_run_in_docker", lambda *args: time.sleep(0.3) or {"result": 1})
    ticks = 0

    async def ticker():
        nonlocal ticks
        for _ in range(10):
            await asyncio.sleep(0.02)
            ticks += 1

    result, _ = await asyncio.gather(code_sandbox.execute_python("result = 1"), ticker())
    assert result == {"result": 1} and ticks == 10  # the loop kept running while Docker "worked"


def test_non_timeout_docker_errors_are_not_called_timeouts():
    from app.services import code_sandbox

    import requests
    from urllib3.exceptions import ReadTimeoutError

    assert code_sandbox._is_timeout(TimeoutError()) is True
    # What docker's container.wait(timeout) raises when the time is up.
    wrapped = requests.exceptions.ConnectionError(ReadTimeoutError(None, "/containers/x/wait", "Read timed out."))
    assert code_sandbox._is_timeout(wrapped) is True
    assert code_sandbox._is_timeout(requests.exceptions.ReadTimeout()) is True
    # The daemon going away is a failure, not a timeout.
    assert code_sandbox._is_timeout(requests.exceptions.ConnectionError("Connection aborted: socket reset")) is False
    assert code_sandbox._is_timeout(RuntimeError("500 Server Error: no such image")) is False
