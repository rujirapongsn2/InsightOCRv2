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


def test_admin_shared_integrations_are_usable_by_everyone(monkeypatch):
    from app.agent.tools import integration_tools as tools
    from app.services.integration_access import integration_usable_by

    me, admin = uuid.uuid4(), uuid.uuid4()
    shared = _integration("ERP", admin)
    shared.is_shared = True
    private = _integration("Payroll", admin)
    private.is_shared = False
    mine = _integration("ERP", me)
    mine.is_shared = False
    assert integration_usable_by(shared, me) and not integration_usable_by(private, me)

    db = SimpleNamespace(query=lambda model: _FakeQuery([shared, private, mine]))
    assert tools._find_integration(db, me, integration_name="erp") is mine  # own first when names clash
    db = SimpleNamespace(query=lambda model: _FakeQuery([shared, private]))
    assert tools._find_integration(db, me, integration_name="erp") is shared
    listed = asyncio.run(tools._list_integrations_handler({}, SimpleNamespace(db=db, user_id=me)))
    assert [(item["name"], item["shared"]) for item in listed["integrations"]] == [("ERP", True)]


def test_workflows_may_use_shared_integrations_only():
    from app.services import workflow_engine

    owner = str(uuid.uuid4())
    shared = SimpleNamespace(name="ERP", user_id=uuid.uuid4(), is_shared=True)
    private = SimpleNamespace(name="Payroll", user_id=uuid.uuid4(), is_shared=False)
    workflow_engine._ensure_integration_owner(shared, owner)  # no error
    with pytest.raises(workflow_engine.NodeExecutionError, match="not shared"):
        workflow_engine._ensure_integration_owner(private, owner)


def test_only_admins_can_share_an_integration():
    from fastapi import HTTPException
    from app.api.v1.endpoints import integrations as endpoint
    from app.schemas.integration import IntegrationCreate

    manager = SimpleNamespace(id=uuid.uuid4(), role="manager", is_superuser=False)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(endpoint.create_integration(
            IntegrationCreate(name="ERP", type="api", config={}, is_shared=True), db=None, current_user=manager))
    assert refused.value.status_code == 403


def _api_integration(owner, shared):
    from app.models.integration import IntegrationStatus, IntegrationType

    return SimpleNamespace(id=uuid.uuid4(), name="ERP", user_id=owner, is_shared=shared,
                           status=IntegrationStatus.ACTIVE, type=IntegrationType.API, config={}, user=None)


def test_send_page_follows_the_sharing_rule(monkeypatch):
    from fastapi import HTTPException
    from app.api.v1.endpoints import integrations as endpoint

    monkeypatch.setattr(endpoint, "_is_llm_integration", lambda integration: False)
    user = SimpleNamespace(id=uuid.uuid4(), role="user", is_superuser=False)
    endpoint._authorize_send_target(None, user, _api_integration(uuid.uuid4(), True), None)  # shared: allowed
    with pytest.raises(HTTPException) as refused:
        endpoint._authorize_send_target(None, user, _api_integration(uuid.uuid4(), False), None)
    assert refused.value.status_code == 403


def test_group_managers_cannot_change_an_admin_shared_integration(monkeypatch):
    from fastapi import HTTPException
    from app.api.v1.endpoints import integrations as endpoint
    from app.schemas.integration import IntegrationUpdate

    shared = _api_integration(uuid.uuid4(), True)
    monkeypatch.setattr(endpoint.crud_integration, "get", lambda db, integration_id: shared)
    monkeypatch.setattr(endpoint, "can_manage_group_resource", lambda user, owner: True)
    manager = SimpleNamespace(id=uuid.uuid4(), role="manager", is_superuser=False)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(endpoint.update_integration(shared.id, IntegrationUpdate(description="changed"), db=None,
                                                current_user=manager))
    assert refused.value.status_code == 403 and "shared" in refused.value.detail
    with pytest.raises(HTTPException) as refused_delete:
        asyncio.run(endpoint.delete_integration(shared.id, db=None, current_user=manager))
    assert refused_delete.value.status_code == 403


def test_mcp_lists_own_and_shared_integrations(monkeypatch):
    from app.api.v1.endpoints import mcp

    filters = []

    class Query:
        def filter(self, *criteria):
            filters.extend(str(item.compile(compile_kwargs={"literal_binds": False})) for item in criteria)
            return self

        def order_by(self, *args):
            return self

        def limit(self, *args):
            return self

        def all(self):
            return []

    monkeypatch.setattr(mcp, "is_admin_user", lambda user: False)
    mcp._list_integrations({}, SimpleNamespace(query=lambda model: Query()), SimpleNamespace(id=uuid.uuid4()))
    assert any("is_shared" in item and "user_id" in item for item in filters)


def test_shared_cloud_and_llm_integrations_are_protected_from_non_owners():
    from app.api.v1.endpoints import integrations as endpoint

    shared = _api_integration(uuid.uuid4(), True)
    manager = SimpleNamespace(id=uuid.uuid4(), role="manager", is_superuser=False)
    admin = SimpleNamespace(id=uuid.uuid4(), role="admin", is_superuser=False)
    owner = SimpleNamespace(id=shared.user_id, role="manager", is_superuser=False)
    assert endpoint._can_manage_cloud(manager, shared) is False
    assert endpoint._can_manage_cloud(admin, shared) is True
    assert endpoint._can_manage_cloud(owner, shared) is False  # the folder is part of the shared connection
    shared.is_shared = False
    assert endpoint._can_manage_cloud(manager, shared) is True  # unchanged for unshared integrations


def test_ownerless_integrations_are_not_treated_as_shared():
    from app.services.integration_access import integration_usable_by

    assert integration_usable_by(SimpleNamespace(user_id=None, is_shared=False), uuid.uuid4()) is False
    assert integration_usable_by(SimpleNamespace(user_id=None, is_shared=True), uuid.uuid4()) is True


def test_owner_cannot_repoint_a_shared_integration_without_an_admin(monkeypatch):
    from fastapi import HTTPException
    from app.api.v1.endpoints import integrations as endpoint
    from app.schemas.integration import IntegrationUpdate

    owner = SimpleNamespace(id=uuid.uuid4(), role="manager", is_superuser=False)
    shared = _api_integration(owner.id, True)
    monkeypatch.setattr(endpoint.crud_integration, "get", lambda db, integration_id: shared)
    with pytest.raises(HTTPException) as refused:
        asyncio.run(endpoint.update_integration(shared.id, IntegrationUpdate(config={"endpoint": "https://elsewhere"}),
                                                db=None, current_user=owner))
    assert refused.value.status_code == 403 and "admin" in refused.value.detail


def test_null_sharing_value_is_rejected_cleanly():
    from pydantic import ValidationError
    from app.schemas.integration import IntegrationUpdate

    with pytest.raises(ValidationError):
        IntegrationUpdate(is_shared=None)
    assert "is_shared" not in IntegrationUpdate(name="x").model_dump(exclude_unset=True)


def test_reconnecting_a_shared_cloud_account_needs_an_admin(monkeypatch):
    from app.api.v1.endpoints import integrations as endpoint
    from app.models.integration import IntegrationType
    import app.services.cloud_oauth as cloud_oauth

    manager = SimpleNamespace(id=uuid.uuid4(), role="manager", is_superuser=False, is_active=True)
    shared = SimpleNamespace(id=uuid.uuid4(), user_id=manager.id, is_shared=True, type=IntegrationType.GDRIVE,
                             name="Google Drive · a@x", status="paused",
                             config={"auth_mode": "oauth", "provider": "google", "account_id": "acc-1",
                                     "refresh_token_encrypted": "old-token", "folder_id": "shared-folder"})

    class Query:
        def __init__(self, rows):
            self.rows = rows

        def filter(self, *a):
            return self

        def first(self):
            return self.rows[0]

        def all(self):
            return self.rows

    db = SimpleNamespace(query=lambda model: Query([manager] if model.__name__ == "User" else [shared]),
                         commit=lambda: pytest.fail("must not save"), add=lambda obj: None, flush=lambda: None)
    monkeypatch.setattr(cloud_oauth, "consume_state", lambda state, provider: str(manager.id))
    monkeypatch.setattr(cloud_oauth, "resolve_public_app_url", lambda request: "https://app.invalid")
    monkeypatch.setattr(cloud_oauth, "complete_authorization", lambda *a, **k: {
        "account_id": "acc-1", "account_email": "a@x", "refresh_token_encrypted": "new-token"})
    monkeypatch.setattr(endpoint, "_cloud_redirect_url", lambda request, **params: "/integrations?" + "&".join(
        f"{k}={v}" for k, v in params.items()))

    response = asyncio.run(endpoint.complete_cloud_oauth("google", SimpleNamespace(), code="c", state="s", db=db))

    assert "oauth=error" in response.headers["location"]
    assert shared.config["refresh_token_encrypted"] == "old-token" and shared.status == "paused"
