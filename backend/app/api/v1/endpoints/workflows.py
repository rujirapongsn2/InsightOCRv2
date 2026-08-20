import os
from mimetypes import guess_type
from pathlib import PurePosixPath
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload

from app.api import deps
from app.api.permissions import can_access_job
from app.core import security
from app.core.config import settings
from app.models.user import User
from app.models.job import Job
from app.models.workflow import Workflow, WorkflowRun, WorkflowNodeRun
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
    MAX_WORKFLOW_ARTIFACT_BYTES,
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


def _ensure_runnable_definition(
    db: Session,
    definition: dict,
    user: User,
    *,
    refresh_skill_fingerprints: bool = False,
) -> None:
    # The builder creates an empty draft before the first node is placed.
    # Keep that editing flow available; run/activate still validates the graph.
    if not (definition or {}).get("nodes"):
        return
    issues = validate_workflow_definition(
        db,
        definition,
        user,
        allow_unresolved_references=False,
        refresh_skill_fingerprints=refresh_skill_fingerprints,
    )
    errors = [issue for issue in issues if issue["level"] == "error"]
    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Workflow configuration is not runnable",
                "issues": errors,
            },
        )


def _webhook_url(request: Request, workflow_id: UUID, secret: str) -> str:
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}{settings.API_V1_STR}/external/workflows/{workflow_id}/webhook/{secret}"


def _download_storage_file(
    storage_key: str,
    filename: str,
    mime_type: Optional[str] = None,
) -> StreamingResponse:
    """Stream one already-authorized storage object as a browser download."""
    storage = get_storage_service()
    if not storage.exists(storage_key):
        raise HTTPException(status_code=404, detail="Output file not found")
    with storage.get_local_path(storage_key) as local_path:
        size = os.path.getsize(local_path)
    if size > MAX_WORKFLOW_ARTIFACT_BYTES:
        raise HTTPException(status_code=413, detail="Output file exceeds the 50 MB download limit")

    # HTTP headers are latin-1 only, so a non-ASCII (e.g. Thai) filename must use
    # RFC 5987 `filename*=UTF-8''…`, with an ASCII fallback for old clients.
    from urllib.parse import quote
    safe_name = os.path.basename(filename)
    ascii_fallback = safe_name.encode("ascii", "ignore").decode() or "download"
    if ascii_fallback.startswith("."):
        ascii_fallback = "download" + ascii_fallback
    disposition = (
        f"attachment; filename=\"{ascii_fallback}\"; "
        f"filename*=UTF-8''{quote(safe_name)}"
    )
    def file_chunks():
        # Reopen the storage context inside the iterator so temporary paths
        # returned by remote storage stay alive through the response stream.
        with storage.get_local_path(storage_key) as local_path:
            with open(local_path, "rb") as output_file:
                while chunk := output_file.read(1024 * 1024):
                    yield chunk

    return StreamingResponse(
        file_chunks(),
        media_type=mime_type or guess_type(safe_name)[0] or "application/octet-stream",
        headers={"Content-Disposition": disposition, "Content-Length": str(size)},
    )


def _job_artifact_key(job_id: UUID, path: str) -> str:
    """Resolve a path recorded by a verified Agent artifact without traversal."""
    clean_path = str(path or "").strip().replace("\\", "/").lstrip("/")
    current_prefix = f"jobs/{job_id}/"
    if clean_path.startswith(current_prefix):
        clean_path = clean_path[len(current_prefix):]
    elif clean_path.startswith("jobs/"):
        raise HTTPException(status_code=400, detail="Artifact path references another Job")

    parts = PurePosixPath(clean_path).parts
    if not parts or parts[0] != "outputs" or len(parts) < 2 or ".." in parts:
        raise HTTPException(status_code=400, detail="Artifact path is invalid")
    return f"jobs/{job_id}/{clean_path}"


def _upstream_job_id_from_definition(run: WorkflowRun, node_id: str) -> Optional[str]:
    """Recover a single Job context from an older node-test run snapshot.

    Earlier Agent runs did not persist the inferred Job id on the node output.
    Their immutable workflow snapshot still records the upstream Jobs or
    Document Source node, which is enough to recover an unambiguous context.
    """
    definition = run.definition_snapshot if isinstance(run.definition_snapshot, dict) else {}
    nodes = definition.get("nodes") or []
    edges = definition.get("edges") or []
    parents: dict[str, list[str]] = {}
    node_by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source and target:
            parents.setdefault(str(target), []).append(str(source))

    job_ids: set[str] = set()
    visited: set[str] = set()
    queue = list(parents.get(node_id) or [])
    while queue:
        source_id = queue.pop(0)
        if source_id in visited:
            continue
        visited.add(source_id)
        node = node_by_id.get(source_id) or {}
        config = (node.get("data") or {}).get("config") or {}
        job_id = config.get("job_id")
        if job_id:
            job_ids.add(str(job_id))
        queue.extend(parents.get(source_id) or [])

    return next(iter(job_ids)) if len(job_ids) == 1 else None


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
    issues = validate_workflow_definition(
        db, definition, current_user, refresh_skill_fingerprints=True
    )
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
    definition = payload.definition.model_dump() if payload.definition else {"nodes": [], "edges": []}
    _ensure_runnable_definition(
        db, definition, current_user, refresh_skill_fingerprints=True
    )
    wf = Workflow(
        name=payload.name,
        description=payload.description,
        definition=definition,
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
    if "definition" in data or data.get("is_active"):
        _ensure_runnable_definition(
            db,
            data.get("definition") or wf.definition or {},
            current_user,
            refresh_skill_fingerprints=True,
        )
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
    _ensure_runnable_definition(db, wf.definition or {}, current_user)

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
    _ensure_runnable_definition(db, wf.definition or {}, current_user)

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
    return _download_storage_file(storage_key, safe_name)


@router.get("/runs/{run_id}/artifacts/{node_run_id}/{artifact_index}")
def download_run_artifact(
    run_id: UUID,
    node_run_id: UUID,
    artifact_index: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_active_user),
):
    """Download a verified artifact produced by any node in an authorized run.

    Agent artifacts remain owned by their Job until a Publish Artifact node copies
    them into the Workflow-run namespace. This route understands both scopes and
    only resolves metadata persisted on the node run, never a client supplied
    storage path.
    """
    if artifact_index < 0:
        raise HTTPException(status_code=404, detail="Artifact not found")
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _get_workflow_or_404(db, run.workflow_id, current_user)

    node_run = (
        db.query(WorkflowNodeRun)
        .filter(WorkflowNodeRun.id == node_run_id, WorkflowNodeRun.run_id == run.id)
        .first()
    )
    if not node_run:
        raise HTTPException(status_code=404, detail="Node run not found")

    output = node_run.output if isinstance(node_run.output, dict) else {}
    artifacts = output.get("artifacts") or []
    if not isinstance(artifacts, list) or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="Artifact not found")
    artifact = artifacts[artifact_index]
    if not isinstance(artifact, dict) or artifact.get("verified") is not True:
        raise HTTPException(status_code=404, detail="Verified artifact not found")

    filename = os.path.basename(str(artifact.get("filename") or artifact.get("path") or "download"))
    if not filename:
        raise HTTPException(status_code=400, detail="Artifact filename is invalid")
    storage_key = artifact.get("storage_key")
    if storage_key:
        expected_prefix = f"{WORKFLOW_OUTPUT_DIR}/{run.id}/"
        key_parts = PurePosixPath(str(storage_key)).parts
        if (
            not isinstance(storage_key, str)
            or not storage_key.startswith(expected_prefix)
            or ".." in key_parts
        ):
            raise HTTPException(status_code=400, detail="Artifact storage path is invalid")
        return _download_storage_file(storage_key, filename, artifact.get("mime_type"))

    node_input = node_run.input if isinstance(node_run.input, dict) else {}
    job_id = (
        artifact.get("job_id")
        or output.get("job_id")
        or node_input.get("job_id")
        or node_input.get("_inferred_job_id")
        or _upstream_job_id_from_definition(run, node_run.node_id)
    )
    try:
        job_uuid = UUID(str(job_id))
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="Artifact Job context is unavailable")
    job = db.query(Job).filter(Job.id == job_uuid).first()
    if not job or not can_access_job(current_user, job):
        raise HTTPException(status_code=404, detail="Artifact source is unavailable")

    storage_key = _job_artifact_key(job_uuid, str(artifact.get("path") or ""))
    return _download_storage_file(storage_key, filename, artifact.get("mime_type"))
