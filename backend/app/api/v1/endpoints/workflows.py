import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, selectinload

from app.api import deps
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
)
from app.services.workflow_engine import NODE_TYPES, WORKFLOW_OUTPUT_DIR

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


@router.get("/node-types")
def list_node_types(current_user: User = Depends(deps.get_current_active_user)):
    """Node palette catalog for the workflow builder."""
    return {"node_types": NODE_TYPES}


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
    run_workflow_task.delay(str(run.id))
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
    test_node_task.delay(str(run.id), node_id)
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
    path = os.path.join(WORKFLOW_OUTPUT_DIR, str(run_id), safe_name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Output file not found")
    return FileResponse(path, filename=safe_name)
