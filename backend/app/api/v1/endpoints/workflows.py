import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, selectinload

from app.api import deps
from app.core import security
from app.core.config import settings
from app.models.user import User
from app.models.workflow import Workflow, WorkflowRun
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowListResponse,
    WorkflowRunRequest,
    WorkflowRunResponse,
    WorkflowRunListResponse,
    WorkflowWebhookSecretResponse,
    SuggestVariablesRequest,
    SuggestVariablesResponse,
    WorkflowExport,
    WorkflowImportRequest,
    WorkflowImportResponse,
)
from app.services.workflow_validation import validate_workflow_definition
from app.services.storage import get_storage_service
from app.services.workflow_engine import (
    NODE_TYPES,
    WORKFLOW_OUTPUT_DIR,
    NodeExecutionError,
    suggest_variables,
)

router = APIRouter()


def _is_admin(user: User) -> bool:
    return getattr(user, "role", None) == "admin" or getattr(user, "is_superuser", False)


def _get_workflow_or_404(db: Session, workflow_id: UUID, user: User) -> Workflow:
    wf = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if not _is_admin(user) and wf.user_id and wf.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not allowed to access this workflow")
    return wf


def _validate_cron(expr: Optional[str]) -> None:
    if not expr:
        return
    from croniter import croniter
    if not croniter.is_valid(expr):
        raise HTTPException(status_code=422, detail=f"Invalid cron expression: {expr}")


def _webhook_url(request: Request, workflow_id: UUID, secret: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}{settings.API_V1_STR}/external/workflows/{workflow_id}/webhook/{secret}"


@router.get("/node-types")
def list_node_types(current_user: User = Depends(deps.get_current_active_user)):
    """Node palette catalog for the workflow builder."""
    return {"node_types": NODE_TYPES}


@router.post("/{workflow_id}/suggest-variables", response_model=SuggestVariablesResponse)
def suggest_variables_endpoint(
    workflow_id: UUID,
    payload: SuggestVariablesRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """AI variable finder: rank the supplied variable candidates against a
    natural-language description. The LLM only selects from `candidates`;
    sample values are rendered client-side from real run data."""
    _get_workflow_or_404(db, workflow_id, current_user)
    if not payload.candidates:
        return {"suggestions": []}
    try:
        suggestions = suggest_variables(
            db,
            query=payload.query,
            candidates=[c.model_dump() for c in payload.candidates],
            integration_id=payload.integration_id,
            owner_user_id=str(current_user.id),
        )
    except NodeExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface LLM/transport errors cleanly
        raise HTTPException(status_code=502, detail=f"AI ค้นหาตัวแปรไม่สำเร็จ: {exc}")
    return {"suggestions": suggestions}


@router.get("/", response_model=WorkflowListResponse)
def list_workflows(
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    query = db.query(Workflow)
    if not _is_admin(current_user):
        query = query.filter(Workflow.user_id == current_user.id)
    workflows = query.order_by(Workflow.created_at.desc()).all()
    return {"workflows": workflows, "total": len(workflows)}


@router.get("/{workflow_id}/export", response_model=WorkflowExport)
def export_workflow(
    workflow_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Portable JSON of a workflow (definition + metadata) for import elsewhere."""
    wf = _get_workflow_or_404(db, workflow_id, current_user)
    return WorkflowExport(
        name=wf.name,
        description=wf.description,
        schedule_cron=wf.schedule_cron,
        schedule_enabled=bool(wf.schedule_enabled),
        definition=wf.definition or {"nodes": [], "edges": []},
    )


@router.post("/import", response_model=WorkflowImportResponse, status_code=201)
def import_workflow(
    payload: WorkflowImportRequest,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Import a workflow JSON. Created INACTIVE. Any node whose references don't
    resolve in this environment (missing job/integration/provider) or whose
    required config is absent is returned as a warning for the user to fix
    manually in the builder."""
    definition = payload.definition or {"nodes": [], "edges": []}
    issues = validate_workflow_definition(db, definition, current_user)
    _validate_cron(payload.schedule_cron)
    wf = Workflow(
        name=payload.name,
        description=payload.description,
        definition=definition,
        schedule_cron=payload.schedule_cron,
        schedule_enabled=bool(payload.schedule_enabled),
        is_active=False,  # imported workflows start disabled until reviewed
        user_id=current_user.id,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return WorkflowImportResponse(workflow=wf, warnings=issues)


@router.post("/", response_model=WorkflowResponse, status_code=201)
def create_workflow(
    payload: WorkflowCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    _validate_cron(payload.schedule_cron)
    wf = Workflow(
        name=payload.name,
        description=payload.description,
        definition=payload.definition.model_dump() if payload.definition else {"nodes": [], "edges": []},
        schedule_cron=payload.schedule_cron,
        schedule_enabled=payload.schedule_enabled,
        is_active=payload.is_active,
        user_id=current_user.id,
    )
    if wf.schedule_enabled and wf.schedule_cron:
        from app.tasks.workflow_tasks import compute_next_run
        wf.next_run_at = compute_next_run(wf.schedule_cron, datetime.now(timezone.utc))
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    workflow_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    return _get_workflow_or_404(db, workflow_id, current_user)


@router.put("/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    workflow_id: UUID,
    payload: WorkflowUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    wf = _get_workflow_or_404(db, workflow_id, current_user)
    data = payload.model_dump(exclude_unset=True)
    if "schedule_cron" in data:
        _validate_cron(data["schedule_cron"])
    if "definition" in data and data["definition"] is not None:
        data["definition"] = payload.definition.model_dump()
    for key, value in data.items():
        setattr(wf, key, value)

    # Recompute the next scheduled run whenever scheduling fields change
    if "schedule_cron" in data or "schedule_enabled" in data:
        if wf.schedule_enabled and wf.schedule_cron:
            from app.tasks.workflow_tasks import compute_next_run
            wf.next_run_at = compute_next_run(wf.schedule_cron, datetime.now(timezone.utc))
        else:
            wf.next_run_at = None

    db.commit()
    db.refresh(wf)
    return wf


@router.post("/{workflow_id}/webhook-secret", response_model=WorkflowWebhookSecretResponse)
def rotate_workflow_webhook_secret(
    workflow_id: UUID,
    request: Request,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Enable webhook trigger and reveal a newly generated secret URL once."""
    wf = _get_workflow_or_404(db, workflow_id, current_user)
    secret = security.generate_workflow_webhook_secret()
    now = datetime.now(timezone.utc)
    wf.webhook_enabled = True
    wf.webhook_secret_hash = security.hash_workflow_webhook_secret(secret)
    wf.webhook_secret_created_at = now
    db.commit()
    db.refresh(wf)
    return WorkflowWebhookSecretResponse(
        webhook_enabled=True,
        webhook_url=_webhook_url(request, wf.id, secret),
        secret=secret,
        secret_created_at=now,
    )


@router.delete("/{workflow_id}/webhook-secret", status_code=204)
def disable_workflow_webhook_secret(
    workflow_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    wf = _get_workflow_or_404(db, workflow_id, current_user)
    wf.webhook_enabled = False
    wf.webhook_secret_hash = None
    wf.webhook_secret_created_at = None
    db.commit()


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(
    workflow_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    wf = _get_workflow_or_404(db, workflow_id, current_user)
    db.delete(wf)
    db.commit()


@router.post("/{workflow_id}/run", response_model=WorkflowRunResponse, status_code=202)
def run_workflow(
    workflow_id: UUID,
    payload: WorkflowRunRequest | None = None,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    wf = _get_workflow_or_404(db, workflow_id, current_user)
    if not wf.is_active:
        raise HTTPException(status_code=400, detail="Workflow is inactive")
    nodes = (wf.definition or {}).get("nodes") or []
    if not nodes:
        raise HTTPException(status_code=400, detail="Workflow has no nodes")

    run = WorkflowRun(
        workflow_id=wf.id,
        status="queued",
        trigger_type="manual",
        trigger_input=(payload.input if payload else None) or {},
        definition_snapshot=wf.definition,
        triggered_by=current_user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    from app.tasks.workflow_tasks import run_workflow_task
    try:
        run_workflow_task.delay(str(run.id))
    except Exception:
        run.status = "failed"
        run.error = "Failed to enqueue workflow run (task broker unavailable)"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=503, detail="Task queue unavailable, please retry")
    return run


@router.post("/{workflow_id}/nodes/{node_id}/test", response_model=WorkflowRunResponse, status_code=202)
def test_node(
    workflow_id: UUID,
    node_id: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Run a single node in isolation, reusing data from the last full run."""
    wf = _get_workflow_or_404(db, workflow_id, current_user)
    nodes = (wf.definition or {}).get("nodes") or []
    if not any(n.get("id") == node_id for n in nodes):
        raise HTTPException(status_code=404, detail="Node not found in workflow")

    run = WorkflowRun(
        workflow_id=wf.id,
        status="queued",
        trigger_type="node_test",
        trigger_input={"node_id": node_id},
        definition_snapshot=wf.definition,
        triggered_by=current_user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    from app.tasks.workflow_tasks import test_node_task
    try:
        test_node_task.delay(str(run.id), node_id)
    except Exception:
        run.status = "failed"
        run.error = "Failed to enqueue node test (task broker unavailable)"
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=503, detail="Task queue unavailable, please retry")
    return run


@router.get("/{workflow_id}/runs", response_model=WorkflowRunListResponse)
def list_runs(
    workflow_id: UUID,
    limit: int = 20,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    _get_workflow_or_404(db, workflow_id, current_user)
    runs = (
        db.query(WorkflowRun)
        .filter(WorkflowRun.workflow_id == workflow_id)
        .order_by(WorkflowRun.created_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    return {"runs": runs, "total": len(runs)}


@router.get("/runs/{run_id}", response_model=WorkflowRunResponse)
def get_run(
    run_id: UUID,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    run = (
        db.query(WorkflowRun)
        .options(selectinload(WorkflowRun.node_runs))
        .filter(WorkflowRun.id == run_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _get_workflow_or_404(db, run.workflow_id, current_user)
    # Stable activity order: by start time, pending last
    run.node_runs.sort(key=lambda nr: (nr.started_at is None, nr.started_at or nr.id))
    return run


@router.get("/runs/{run_id}/outputs/{filename}")
def download_run_output(
    run_id: UUID,
    filename: str,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _get_workflow_or_404(db, run.workflow_id, current_user)

    safe_name = os.path.basename(filename)
    storage_key = f"{WORKFLOW_OUTPUT_DIR}/{run_id}/{safe_name}"
    storage = get_storage_service()
    if not storage.exists(storage_key):
        raise HTTPException(status_code=404, detail="Output file not found")
    with storage.get_local_path(storage_key) as local_path:
        data = open(local_path, "rb").read()
    # HTTP headers are latin-1 only, so a non-ASCII (e.g. Thai) filename must use
    # RFC 5987 `filename*=UTF-8''…`, with an ASCII fallback for old clients.
    from urllib.parse import quote
    ascii_fallback = safe_name.encode("ascii", "ignore").decode() or "download"
    if ascii_fallback.startswith("."):  # Thai name reduced to just its extension
        ascii_fallback = "download" + ascii_fallback
    disposition = (
        f"attachment; filename=\"{ascii_fallback}\"; "
        f"filename*=UTF-8''{quote(safe_name)}"
    )
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )
