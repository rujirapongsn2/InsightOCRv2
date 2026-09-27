from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.agent_conversation import AgentConversation
from app.models.agent_message import AgentMessage


class CRUDAgentConversation:
    def create(self, db: Session, *, job_id: Optional[UUID] = None, user_id: UUID, integration_id: Optional[UUID] = None, max_iterations: int = 15, kind: str = "document") -> AgentConversation:
        conv = AgentConversation(job_id=job_id, user_id=user_id, integration_id=integration_id, max_iterations=max_iterations, kind=kind)
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return conv

    def get_by_user_kind(self, db: Session, user_id: UUID, kind: str) -> List[AgentConversation]:
        return (
            db.query(AgentConversation)
            .filter(AgentConversation.user_id == user_id, AgentConversation.kind == kind)
            .order_by(AgentConversation.updated_at.desc())
            .all()
        )

    def get(self, db: Session, conversation_id: UUID) -> Optional[AgentConversation]:
        return db.query(AgentConversation).filter(AgentConversation.id == conversation_id).first()

    def get_by_job(self, db: Session, job_id: UUID, user_id: UUID) -> List[AgentConversation]:
        return db.query(AgentConversation).filter(AgentConversation.job_id == job_id, AgentConversation.user_id == user_id).order_by(AgentConversation.updated_at.desc()).all()

    def get_recent_turns(self, db: Session, conversation_id: UUID, turns: int = 6,
                         max_messages: int = 120) -> List[AgentMessage]:
        """Messages from the last ``turns`` user messages onward (capped), oldest first."""
        starts = (
            db.query(AgentMessage.created_at)
            .filter(AgentMessage.conversation_id == conversation_id, AgentMessage.role == "user")
            .order_by(AgentMessage.created_at.desc())
            .limit(turns)
            .all()
        )
        query = db.query(AgentMessage).filter(AgentMessage.conversation_id == conversation_id)
        if starts:
            query = query.filter(AgentMessage.created_at >= starts[-1][0])
        messages = query.order_by(AgentMessage.created_at.desc()).limit(max_messages).all()
        return list(reversed(messages))

    def get_messages(self, db: Session, conversation_id: UUID, limit: int = 50) -> List[AgentMessage]:
        # Keep the newest messages in context while preserving chronological order.
        # The previous ASC + LIMIT query returned the oldest messages, so long
        # conversations lost recent user intent and tool results.
        messages = (
            db.query(AgentMessage)
            .filter(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.created_at.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(messages))

    def delete(self, db: Session, conversation_id: UUID) -> bool:
        conv = self.get(db, conversation_id)
        if not conv:
            return False
        db.delete(conv)
        db.commit()
        return True

    def update_title(self, db: Session, conversation_id: UUID, title: str) -> None:
        conv = self.get(db, conversation_id)
        if conv:
            conv.title = title
            db.commit()


agent_conversation = CRUDAgentConversation()