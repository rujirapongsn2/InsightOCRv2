"""Durable background execution for interactive Agent DOC conversations."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from app.agent.loop import AgentLoop
from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.agent_conversation import AgentConversation
from app.models.agent_run import AgentRun

logger = logging.getLogger(__name__)


CANCEL_CHECK_SECONDS = 0.5  # plus a check before every tool call (registry)
INTERRUPTED_ERROR = ("Agent DOC was interrupted because its worker restarted. "
                     "Nothing was repeated; send the message again to continue.")


def _run_status(run_id: str) -> str | None:
    """Current status from a separate session, so the loop's session is untouched."""
    with SessionLocal() as db:
        return db.query(AgentRun.status).filter(AgentRun.id == uuid.UUID(str(run_id))).scalar()


async def _consume_agent_run(
    loop: AgentLoop,
    user_message: str,
    run_id: str | None = None,
) -> tuple[dict | None, str | None]:
    """Run the agent to completion while its persisted messages feed the UI.

    Stops at the next event when the run is no longer ``running`` (the user
    pressed Stop, or maintenance reconciled it).
    """
    completed: dict | None = None
    error: str | None = None
    checked_at = asyncio.get_running_loop().time()
    stream = loop.run(user_message)
    try:
        async for event in stream:
            now = asyncio.get_running_loop().time()
            if run_id and now - checked_at >= CANCEL_CHECK_SECONDS:
                checked_at = now
                if _run_status(run_id) != "running":
                    logger.info("Agent run %s stopped: no longer running", run_id)
                    return completed, error
            if not event.startswith("data: "):
                continue
            completed, error = _read_event(event, completed, error)
    finally:
        await stream.aclose()
    return completed, error


def _read_event(event: str, completed: dict | None, error: str | None) -> tuple[dict | None, str | None]:
    """Track the final ``done`` payload and the last ``error`` message of an SSE stream."""
    try:
        payload = json.loads(event[6:])
    except json.JSONDecodeError:
        return completed, error
    if payload.get("type") == "error":
        error = str(payload.get("message") or "Agent run failed")
    elif payload.get("type") == "done":
        completed = payload
    return completed, error


@celery_app.task(bind=True, name="app.tasks.agent_tasks.run_agent_task", max_retries=0)
def run_agent_task(self, run_id: str) -> None:
    """Execute a queued AgentRun independently from the requesting browser."""
    from app.api.v1.endpoints.agent import _build_agent_llm_config

    run_id = uuid.UUID(str(run_id))
    db = SessionLocal()
    try:
        claimed = (
            db.query(AgentRun)
            .filter(AgentRun.id == run_id, AgentRun.status == "queued")
            .update(
                {
                    "status": "running",
                    "task_id": self.request.id,
                    "started_at": datetime.now(timezone.utc),
                    "error": None,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        if not claimed:
            # Redelivered after the worker died mid-run (acks_late): the row is still
            # "running" with this task's id. Re-running could repeat approved actions,
            # so end it instead of leaving the conversation locked forever.
            interrupted = (
                db.query(AgentRun)
                .filter(AgentRun.id == run_id, AgentRun.status == "running", AgentRun.task_id == self.request.id)
                .update({"status": "failed", "error": INTERRUPTED_ERROR,
                         "finished_at": datetime.now(timezone.utc)}, synchronize_session=False)
            )
            db.commit()
            if interrupted:
                logger.warning("Agent run %s was interrupted by a worker restart", run_id)
            return

        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        conversation = (
            db.query(AgentConversation)
            .filter(
                AgentConversation.id == run.conversation_id,
                AgentConversation.user_id == run.user_id,
            )
            .first()
        )
        if not conversation:
            run.status = "failed"
            run.error = "Conversation no longer exists"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
            return

        loop = AgentLoop(
            db=db,
            conversation_id=conversation.id,
            user_id=run.user_id,
            job_id=conversation.job_id,
            llm_config=_build_agent_llm_config(db, conversation),
            max_iterations=conversation.max_iterations,
            kind=conversation.kind or "document",
            run_id=run.id,
        )
        try:
            completed, error = asyncio.run(_consume_agent_run(loop, run.user_message, str(run.id)))
        finally:
            # Whatever the outcome, nothing this run asked for may stay waiting.
            db.rollback()
            from app.crud.crud_agent_pending import agent_pending
            agent_pending.expire_for_run(db, run.id)

        db.rollback()
        db.refresh(run)
        if run.status != "running":
            return  # stopped by the user or reconciled meanwhile: keep that outcome (finally records the end)
        if error:
            run.status = "failed"
            run.error = error[:2000]
        elif completed is None:
            run.status = "failed"
            run.error = "Agent run ended before a completion event"
        elif completed.get("success") is False:
            run.status = "failed"
            run.error = " ".join(completed.get("failed_steps") or [])[:2000] or "Agent could not complete the request"
        else:
            run.status = "succeeded"
            run.error = None
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        logger.exception("Agent run %s crashed", run_id)
        db.rollback()
        run = db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if run and run.status not in {"succeeded", "failed", "cancelled"}:
            run.status = "failed"
            run.error = "Internal error while running Agent DOC"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        # A stopped run keeps the conversation locked until its worker has really
        # finished (finished_at is set here, not by the Stop button), so a new
        # message cannot run alongside the old worker's last tool call.
        try:
            db.rollback()
            db.query(AgentRun).filter(
                AgentRun.id == run_id, AgentRun.status == "cancelled", AgentRun.finished_at.is_(None)
            ).update({"finished_at": datetime.now(timezone.utc)}, synchronize_session=False)
            db.commit()
        except Exception:  # noqa: BLE001
            logger.warning("Could not record the end of cancelled agent run %s", run_id)
        db.close()
