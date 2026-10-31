from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.agent_surface import AgentSurface


class CRUDAgentSurface:
    def register(self, db: Session, *, conversation_id: UUID, surface_id: str, tool_name: str,
                 actions: list[dict], document_ids: list[str]) -> AgentSurface:
        """Record a new panel. A panel with buttons supersedes every older panel whose buttons still worked."""
        if actions:
            for older in (db.query(AgentSurface)
                          .filter(AgentSurface.conversation_id == conversation_id, AgentSurface.status == "active")):
                if older.actions:
                    older.status = "superseded"
        surface = AgentSurface(surface_id=surface_id, conversation_id=conversation_id, tool_name=tool_name,
                               actions=actions, document_ids=document_ids, status="active",
                               created_at=datetime.now(timezone.utc))
        db.add(surface)
        db.commit()
        return surface

    def get(self, db: Session, surface_id: str) -> Optional[AgentSurface]:
        return db.query(AgentSurface).filter(AgentSurface.surface_id == surface_id).first()

    def claim(self, db: Session, surface_id: str) -> bool:
        """Mark an active panel answered; False when it no longer was. The caller commits."""
        return bool(
            db.query(AgentSurface)
            .filter(AgentSurface.surface_id == surface_id, AgentSurface.status == "active")
            .update({"status": "answered", "answered_at": datetime.now(timezone.utc)}, synchronize_session=False)
        )

    def reopen(self, db: Session, surface_id: str) -> None:
        """Undo a claim whose run never started."""
        (db.query(AgentSurface)
         .filter(AgentSurface.surface_id == surface_id, AgentSurface.status == "answered")
         .update({"status": "active", "answered_at": None}, synchronize_session=False))
        db.commit()

    def states(self, db: Session, conversation_id: UUID) -> dict[str, dict]:
        """Every panel of the conversation, whatever page of messages the client holds."""
        rows = (db.query(AgentSurface.surface_id, AgentSurface.status, AgentSurface.actions, AgentSurface.created_at)
                .filter(AgentSurface.conversation_id == conversation_id))
        return {row.surface_id: {"status": row.status, "actionable": bool(row.actions),
                                 "generated_at": row.created_at.isoformat() if row.created_at else None}
                for row in rows}


agent_surface = CRUDAgentSurface()
