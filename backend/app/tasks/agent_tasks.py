"""Durable background execution for interactive Agent DOC conversations."""

import asyncio
import json
import logging
from datetime import datetime, timezone

from app.agent.loop import AgentLoop
from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.models.agent_conversation import AgentConversation
from app.models.agent_run import AgentRun

logger = logging.getLogger(__name__)


async def _consume_agent_run(
    loop: AgentLoop,
    user_message: str,
) -> tuple[dict | None, str | None]:
    """Run the agent to completion while its persisted messages feed the UI."""
    completed: dict | None = None
    error: str | None = None
    async for event in loop.run(user_message):
        if not event.startswith("data: "):
            continue
        try:
            payload = json.loads(event[6:])
        except json.JSONDecodeError:
            continue
        if payload.get("type") == "error":
            error = str(payload.get("message") or "Agent run failed")
        elif payload.get("type") == "done":
            completed = payload
    return completed, error


@celery_app.task(bind=True, name="app.tasks.agent_tasks.run_agent_task", max_retries=0)
def run_agent_task(self, run_id: str) -> None:
    """Execute a queued AgentRun independently from the requesting browser."""
    from app.api.v1.endpoints.agent import _build_agent_llm_config

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
        )
        completed, error = asyncio.run(_consume_agent_run(loop, run.user_message))

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
        if run and run.status not in {"succeeded", "failed"}:
            run.status = "failed"
            run.error = "Internal error while running Agent DOC"
            run.finished_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()
