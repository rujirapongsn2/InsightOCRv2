from typing import Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.models.agent_pending_action import AgentPendingAction


class CRUDAgentPending:
    def create(self, db: Session, *, conversation_id: UUID, user_id: UUID, tool_name: str, tool_arguments: dict, description: Optional[str] = None, kind: str = "confirmation", expires_minutes: int = 5) -> AgentPendingAction:
        action = AgentPendingAction(conversation_id=conversation_id, user_id=user_id, tool_name=tool_name, tool_arguments=tool_arguments, description=description, status="pending", kind=kind, expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_minutes))
        db.add(action)
        db.commit()
        db.refresh(action)
        return action

    def get(self, db: Session, pending_id: UUID) -> Optional[AgentPendingAction]:
        return db.query(AgentPendingAction).filter(AgentPendingAction.id == pending_id).first()

    def resolve(self, db: Session, pending_id: UUID, status: str) -> bool:
        action = self.get(db, pending_id)
        if not action:
            return False
        action.status = status
        action.resolved_at = datetime.now(timezone.utc)
        db.commit()
        return True

    def resolve_with_result(self, db: Session, pending_id: UUID, status: str, result: Optional[dict]) -> bool:
        action = self.get(db, pending_id)
        if not action:
            return False
        action.status = status
        action.result = result
        action.resolved_at = datetime.now(timezone.utc)
        db.commit()
        return True


agent_pending = CRUDAgentPending()