import uuid
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.crud.crud_agent_message import agent_message
from app.models.agent_run import AgentRun


ACTIVE_AGENT_RUN_STATUSES = ("queued", "running")


class CRUDAgentRun:
    def create(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: UUID,
        user_message: str,
        ui_action: Optional[dict] = None,
    ) -> AgentRun:
        """Insert a queued run together with the user turn it answers; the caller commits.

        The turn is in the conversation from the moment the request is
        accepted, so every reload shows it; the worker does not record it again.
        The rows are flushed, so later statements in the transaction may reference the run.
        """
        run = AgentRun(
            id=uuid.uuid4(),
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=user_message,
            ui_action=ui_action,
            status="queued",
        )
        db.add(run)
        agent_message.add_user_turn(db, conversation_id=conversation_id, content=user_message, ui_action=ui_action)
        db.flush()
        return run

    def get(self, db: Session, run_id: UUID) -> Optional[AgentRun]:
        return db.query(AgentRun).filter(AgentRun.id == run_id).first()

    def get_active_for_conversation(
        self,
        db: Session,
        *,
        conversation_id: UUID,
        user_id: UUID,
    ) -> Optional[AgentRun]:
        return (
            db.query(AgentRun)
            .filter(
                AgentRun.conversation_id == conversation_id,
                AgentRun.user_id == user_id,
                AgentRun.status.in_(ACTIVE_AGENT_RUN_STATUSES),
            )
            .order_by(AgentRun.created_at.desc())
            .first()
        )


agent_run = CRUDAgentRun()
