from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from app.models.agent_conversation import AgentConversation
from app.models.agent_message import AgentMessage


class CRUDAgentConversation:
    def create(self, db: Session, *, job_id: UUID, user_id: UUID, integration_id: Optional[UUID] = None, max_iterations: int = 15) -> AgentConversation:
        conv = AgentConversation(job_id=job_id, user_id=user_id, integration_id=integration_id, max_iterations=max_iterations)
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return conv

    def get(self, db: Session, conversation_id: UUID) -> Optional[AgentConversation]:
        return db.query(AgentConversation).filter(AgentConversation.id == conversation_id).first()

    def get_by_job(self, db: Session, job_id: UUID, user_id: UUID) -> List[AgentConversation]:
        return db.query(AgentConversation).filter(AgentConversation.job_id == job_id, AgentConversation.user_id == user_id).order_by(AgentConversation.updated_at.desc()).all()

    def get_messages(self, db: Session, conversation_id: UUID, limit: int = 50) -> List[AgentMessage]:
        return db.query(AgentMessage).filter(AgentMessage.conversation_id == conversation_id).order_by(AgentMessage.created_at.asc()).limit(limit).all()

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