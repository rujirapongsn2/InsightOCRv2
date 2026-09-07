from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

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
    ) -> AgentRun:
        run = AgentRun(
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=user_message,
            status="queued",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
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
