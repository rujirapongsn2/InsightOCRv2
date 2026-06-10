from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import update
from app.models.agent_memory import AgentMemory


def _not_expired():
    """Filter clause: either no expiration or not yet expired."""
    now = datetime.now(timezone.utc)
    return (AgentMemory.expires_at.is_(None)) | (AgentMemory.expires_at > now)


class CRUDAgentMemory:
    def upsert(self, db: Session, *, user_id: UUID, job_id: Optional[UUID], scope: str, memory_type: str, key: str, content: str, importance: float = 1.0, expires_at: Optional[datetime] = None) -> AgentMemory:
        existing = db.query(AgentMemory).filter(
            AgentMemory.user_id == user_id,
            AgentMemory.scope == scope,
            AgentMemory.key == key,
            AgentMemory.job_id == job_id,
        ).first()
        if existing:
            existing.content = content
            existing.memory_type = memory_type
            existing.importance = importance
            existing.expires_at = expires_at
            db.commit()
            db.refresh(existing)
            return existing
        mem = AgentMemory(
            user_id=user_id, job_id=job_id, scope=scope,
            memory_type=memory_type, key=key, content=content,
            importance=importance, expires_at=expires_at,
        )
        db.add(mem)
        db.commit()
        db.refresh(mem)
        return mem

    def search(self, db: Session, *, user_id: UUID, job_id: Optional[UUID] = None, query: str = "", limit: int = 10) -> List[AgentMemory]:
        q = db.query(AgentMemory).filter(AgentMemory.user_id == user_id, _not_expired())
        if job_id:
            q = q.filter((AgentMemory.job_id == job_id) | (AgentMemory.scope == "user"))
        else:
            q = q.filter(AgentMemory.scope == "user")
        if query:
            q = q.filter(AgentMemory.key.ilike(f"%{query}%") | AgentMemory.content.ilike(f"%{query}%"))
        results = q.order_by(AgentMemory.importance.desc()).limit(limit).all()

        # Atomic access_count increment — avoids lost updates under concurrency
        if results:
            ids = [m.id for m in results]
            db.execute(
                update(AgentMemory)
                .where(AgentMemory.id.in_(ids))
                .values(access_count=AgentMemory.access_count + 1)
            )
            db.commit()
            # Refresh in-memory objects so callers see the new count
            for m in results:
                db.refresh(m)
        return results

    def list_by_scope(self, db: Session, *, user_id: UUID, scope: str, job_id: Optional[UUID] = None) -> List[AgentMemory]:
        q = db.query(AgentMemory).filter(AgentMemory.user_id == user_id, AgentMemory.scope == scope, _not_expired())
        if scope == "job" and job_id:
            q = q.filter(AgentMemory.job_id == job_id)
        return q.all()

    def delete(self, db: Session, *, user_id: UUID, key: str, scope: str, job_id: Optional[UUID] = None) -> bool:
        mem = db.query(AgentMemory).filter(AgentMemory.user_id == user_id, AgentMemory.scope == scope, AgentMemory.key == key, AgentMemory.job_id == job_id).first()
        if not mem:
            return False
        db.delete(mem)
        db.commit()
        return True


agent_memory = CRUDAgentMemory()