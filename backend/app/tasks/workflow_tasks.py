"""
Celery tasks for workflow execution and cron scheduling.

- run_workflow_task: executes a single WorkflowRun (concurrent runs are
  handled naturally by multiple celery workers).
- dispatch_scheduled_workflows: beat task (every 30s) that enqueues runs
  for workflows whose cron schedule is due.
"""
import logging
from datetime import datetime, timezone

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.workflow import Workflow, WorkflowRun

logger = logging.getLogger(__name__)


def compute_next_run(cron_expr: str, base: datetime) -> datetime:
    from croniter import croniter
    return croniter(cron_expr, base).get_next(datetime)


@celery_app.task(bind=True, max_retries=0)
def run_workflow_task(self, run_id: str):
    from app.services.workflow_engine import execute_workflow_run

    db = SessionLocal()
    try:
        run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if not run:
            logger.error("WorkflowRun not found: %s", run_id)
            return
        if run.status not in ("queued", "running"):
            logger.info("WorkflowRun %s already in status %s — skipping", run_id, run.status)
            return
        run.task_id = self.request.id
        db.commit()
        execute_workflow_run(db, run)

        workflow = db.query(Workflow).filter(Workflow.id == run.workflow_id).first()
        if workflow:
            workflow.last_run_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        logger.exception("Workflow run %s crashed", run_id)
        db.rollback()
        run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if run and run.status not in ("succeeded", "failed"):
            run.status = "failed"
            run.error = "Internal error while executing workflow"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=0)
def test_node_task(self, run_id: str, node_id: str):
    """Execute a single node in isolation for debugging (Test this node)."""
    from app.services.workflow_engine import execute_single_node

    db = SessionLocal()
    try:
        run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if not run:
            logger.error("WorkflowRun not found: %s", run_id)
            return
        if run.status not in ("queued", "running"):
            logger.info("WorkflowRun %s already in status %s — skipping", run_id, run.status)
            return
        run.task_id = self.request.id
        db.commit()
        execute_single_node(db, run, node_id)
    except Exception:
        logger.exception("Node test %s/%s crashed", run_id, node_id)
        db.rollback()
        run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).first()
        if run and run.status not in ("succeeded", "failed"):
            run.status = "failed"
            run.error = "Internal error while testing node"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


@celery_app.task
def dispatch_scheduled_workflows():
    """Enqueue runs for active workflows whose cron schedule is due."""
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        workflows = (
            db.query(Workflow)
            .filter(
                Workflow.is_active.is_(True),
                Workflow.schedule_enabled.is_(True),
                Workflow.schedule_cron.isnot(None),
            )
            .all()
        )
        for wf in workflows:
            try:
                if wf.next_run_at is None:
                    wf.next_run_at = compute_next_run(wf.schedule_cron, now)
                    db.commit()
                    continue
                if wf.next_run_at > now:
                    continue

                run = WorkflowRun(
                    workflow_id=wf.id,
                    status="queued",
                    trigger_type="schedule",
                    trigger_input={"scheduled_at": now.isoformat()},
                    definition_snapshot=wf.definition,
                )
                db.add(run)
                wf.next_run_at = compute_next_run(wf.schedule_cron, now)
                db.commit()
                run_workflow_task.delay(str(run.id))
                logger.info("Scheduled workflow %s → run %s", wf.id, run.id)
            except Exception:
                logger.exception("Failed to dispatch scheduled workflow %s", wf.id)
                db.rollback()
    finally:
        db.close()
