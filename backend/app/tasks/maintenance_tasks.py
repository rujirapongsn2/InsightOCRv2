"""Periodic maintenance: reconcile stuck jobs/runs and prune old data.

Two failure modes previously left records stuck forever:
- a row committed as "queued" whose Celery task never arrived (broker down
  at dispatch time, message lost), and
- a row set to "running"/"processing" by a worker that was then SIGKILLed.

`reconcile_stale_states` sweeps both into "failed" so users can retry.
`prune_old_data` enforces retention on workflow run history and on-disk
artifacts (workflow outputs, per-job log files), none of which were ever
cleaned up before.
"""
import logging
import os
import shutil
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.core.config import settings
from app.models.document import Document
from app.models.workflow import WorkflowRun

logger = logging.getLogger(__name__)

# A workflow run is hard-killed at task_time_limit (2100 s); anything still
# "running" well past that is a dead worker. Documents are checked against
# the live Celery task list before being reconciled, so this timeout only
# applies when the task is no longer running (for example after a worker
# restart).
RUN_RUNNING_STALE = timedelta(seconds=2100 + 600)
DOC_PROCESSING_STALE = timedelta(minutes=10)

# Queued rows are NOT failed just because they are old — a large bulk import
# (thousands of files, few workers) legitimately keeps items queued for hours.
# Instead:
#   * older than REDISPATCH and the broker queue is drained  → the message was
#     lost (broker restart / dispatch-time failure) → re-enqueue it. This is
#     safe because both tasks atomically claim by status, so a duplicate is
#     skipped rather than re-run.
#   * older than the (large) absolute STALE deadline         → truly stuck → fail.
RUN_QUEUED_REDISPATCH = timedelta(minutes=10)
RUN_QUEUED_STALE = timedelta(hours=12)
DOC_QUEUED_REDISPATCH = timedelta(minutes=15)
DOC_QUEUED_STALE = timedelta(hours=24)

# Broker queue names (see task_routes in celery_app.py).
DOC_QUEUE = "documents"
WORKFLOW_QUEUE = "workflows"


def _active_document_task_ids() -> Optional[set[str]]:
    """Return active document task ids, or None when worker inspection fails."""
    try:
        active_by_worker = celery_app.control.inspect(timeout=2).active()
        if active_by_worker is None:
            return None
        return {
            task.get("id")
            for tasks in active_by_worker.values()
            for task in (tasks or [])
            if task.get("name") == "app.tasks.document_tasks.process_document_task"
            and task.get("id")
        }
    except Exception:
        logger.warning("Unable to inspect active Celery tasks; skipping stale document recovery", exc_info=True)
        return None


def _broker_queue_len(queue: str) -> Optional[int]:
    """Pending message count for a Celery/Redis queue, or None if unavailable.

    A non-empty queue means workers are still draining a legitimate backlog, so
    queued rows should be left alone. An empty queue with old queued rows means
    their messages were lost and must be re-dispatched.
    """
    try:
        from app.db.redis import get_redis_client
        return get_redis_client().llen(queue)
    except Exception:
        return None


def _redispatch_lost_documents(db, now) -> int:
    # Only when the queue is genuinely drained — otherwise it's a backlog and
    # re-dispatching would pile up duplicates.
    if (_broker_queue_len(DOC_QUEUE) or 0) > 0:
        return 0
    rows = (
        db.query(Document)
        .filter(
            Document.status == "queued",
            Document.processing_started_at.is_(None),
            Document.uploaded_at < now - DOC_QUEUED_REDISPATCH,
            Document.uploaded_at >= now - DOC_QUEUED_STALE,
        )
        .all()
    )
    if not rows:
        return 0
    from app.tasks.document_tasks import process_document_task
    n = 0
    for d in rows:
        try:
            process_document_task.delay(
                str(d.id), str(d.schema_id) if d.schema_id else None
            )
            n += 1
        except Exception:
            logger.exception("Re-dispatch failed for document %s", d.id)
    return n


def _redispatch_lost_runs(db, now) -> int:
    if (_broker_queue_len(WORKFLOW_QUEUE) or 0) > 0:
        return 0
    rows = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.status == "queued",
            WorkflowRun.created_at < now - RUN_QUEUED_REDISPATCH,
            WorkflowRun.created_at >= now - RUN_QUEUED_STALE,
        )
        .all()
    )
    if not rows:
        return 0
    from app.tasks.workflow_tasks import run_workflow_task
    n = 0
    for r in rows:
        try:
            run_workflow_task.delay(str(r.id))
            n += 1
        except Exception:
            logger.exception("Re-dispatch failed for workflow run %s", r.id)
    return n


@celery_app.task
def reconcile_stale_states():
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        stale_running = (
            db.query(WorkflowRun)
            .filter(
                WorkflowRun.status == "running",
                WorkflowRun.started_at.isnot(None),
                WorkflowRun.started_at < now - RUN_RUNNING_STALE,
            )
            .update(
                {
                    "status": "failed",
                    "error": "Run abandoned: worker died or timed out (auto-reconciled)",
                    "finished_at": now,
                },
                synchronize_session=False,
            )
        )
        stale_queued = (
            db.query(WorkflowRun)
            .filter(
                WorkflowRun.status == "queued",
                WorkflowRun.created_at < now - RUN_QUEUED_STALE,
            )
            .update(
                {
                    "status": "failed",
                    "error": "Run was never picked up by a worker (auto-reconciled)",
                    "finished_at": now,
                },
                synchronize_session=False,
            )
        )
        active_document_task_ids = _active_document_task_ids()
        stale_docs = 0
        if active_document_task_ids is not None:
            stale_processing_docs = (
                db.query(Document)
                .filter(
                    Document.status == "processing",
                    Document.processing_started_at.isnot(None),
                    Document.processing_started_at < now - DOC_PROCESSING_STALE,
                )
                .all()
            )
            for document in stale_processing_docs:
                if document.task_id and document.task_id in active_document_task_ids:
                    continue
                document.status = "failed"
                document.processing_error = (
                    "Processing abandoned: worker task is no longer active "
                    "(auto-reconciled after worker restart)"
                )
                db.add(document)
                stale_docs += 1
        stale_queued_docs = (
            db.query(Document)
            .filter(
                Document.status == "queued",
                Document.uploaded_at < now - DOC_QUEUED_STALE,
                # only docs whose task never started
                Document.processing_started_at.is_(None),
            )
            .update(
                {
                    "status": "failed",
                    "processing_error": "Processing was never picked up by a worker (auto-reconciled)",
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if any((stale_running, stale_queued, stale_docs, stale_queued_docs)):
            logger.warning(
                "Reconciled stale states: %s running runs, %s queued runs, "
                "%s processing docs, %s queued docs",
                stale_running, stale_queued, stale_docs, stale_queued_docs,
            )

        # Recover queued rows whose broker message was lost (queue drained but
        # rows still queued) by re-enqueuing — safe under the atomic claim.
        redispatched_docs = _redispatch_lost_documents(db, now)
        redispatched_runs = _redispatch_lost_runs(db, now)
        if redispatched_docs or redispatched_runs:
            logger.warning(
                "Re-dispatched lost queued work: %s documents, %s workflow runs",
                redispatched_docs, redispatched_runs,
            )
    finally:
        db.close()


def _prune_directory(path: str, older_than: timedelta) -> int:
    """Remove files/dirs under `path` whose mtime is older than the cutoff."""
    if not os.path.isdir(path):
        return 0
    cutoff = time.time() - older_than.total_seconds()
    removed = 0
    for name in os.listdir(path):
        target = os.path.join(path, name)
        try:
            if os.path.getmtime(target) >= cutoff:
                continue
            if os.path.isdir(target):
                shutil.rmtree(target, ignore_errors=True)
            else:
                os.remove(target)
            removed += 1
        except OSError:
            continue
    return removed


@celery_app.task
def prune_old_data():
    retention = timedelta(days=settings.RETENTION_DAYS)
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        # workflow_node_runs go with their runs via ON DELETE CASCADE.
        deleted_runs = (
            db.query(WorkflowRun)
            .filter(WorkflowRun.created_at < now - retention)
            .delete(synchronize_session=False)
        )
        db.commit()
    finally:
        db.close()

    # Local-storage paths on the shared volume. (For MinIO/S3, configure a
    # bucket lifecycle rule for the workflow_outputs/ prefix instead.)
    removed_outputs = _prune_directory("/app/uploads/workflow_outputs", retention)
    removed_logs = _prune_directory("/app/uploads/logs/jobs", retention)

    if deleted_runs or removed_outputs or removed_logs:
        logger.info(
            "Retention pass: deleted %s workflow runs, %s output dirs, %s log files",
            deleted_runs, removed_outputs, removed_logs,
        )
