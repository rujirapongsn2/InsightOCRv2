from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.models.agent_skill import AgentSkill


class CRUDAgentSkill:
    def create(self, db: Session, *, user_id: Optional[UUID], scope: str = "user",
               name: str, description: str, procedure: str,
               trigger_hint: Optional[str] = None,
               tools_used: Optional[list] = None,
               allowed_tools: Optional[str] = None,
               license_: Optional[str] = None,
               compatibility: Optional[str] = None,
               metadata_: Optional[dict] = None,
               created_by: str = "user",
               source: str = "db",
               file_path: Optional[str] = None,
               version: Optional[str] = None) -> AgentSkill:
        skill = AgentSkill(
            user_id=user_id,
            scope=scope,
            name=name,
            description=description,
            procedure=procedure,
            trigger_hint=trigger_hint,
            tools_used=tools_used,
            allowed_tools=allowed_tools,
            license=license_,
            compatibility=compatibility,
            metadata_=metadata_,
            created_by=created_by,
            source=source,
            file_path=file_path,
            version=version,
        )
        db.add(skill)
        db.commit()
        db.refresh(skill)
        return skill

    def get_by_name(self, db: Session, *, user_id: Optional[UUID], name: str, scope: str = "user") -> Optional[AgentSkill]:
        q = db.query(AgentSkill).filter(AgentSkill.name == name, AgentSkill.scope == scope)
        if scope == "user":
            q = q.filter(AgentSkill.user_id == user_id)
        else:
            q = q.filter(AgentSkill.user_id.is_(None))
        return q.first()

    def list_by_user(self, db: Session, *, user_id: UUID, include_system: bool = True) -> List[AgentSkill]:
        """List user-scoped skills + optionally system-scoped skills."""
        if include_system:
            return (
                db.query(AgentSkill)
                .filter(
                    or_(
                        (AgentSkill.user_id == user_id) & (AgentSkill.scope == "user"),
                        (AgentSkill.user_id.is_(None)) & (AgentSkill.scope == "system"),
                    )
                )
                .order_by(AgentSkill.scope.asc(), AgentSkill.success_count.desc())
                .all()
            )
        return (
            db.query(AgentSkill)
            .filter(AgentSkill.user_id == user_id, AgentSkill.scope == "user")
            .order_by(AgentSkill.success_count.desc())
            .all()
        )

    def list_by_scope(self, db: Session, *, scope: str) -> List[AgentSkill]:
        return db.query(AgentSkill).filter(AgentSkill.scope == scope).all()

    def list_file_backed(self, db: Session) -> List[AgentSkill]:
        return db.query(AgentSkill).filter(AgentSkill.source == "file").all()

    def update(self, db: Session, skill_id: UUID, **kwargs) -> Optional[AgentSkill]:
        skill = db.query(AgentSkill).filter(AgentSkill.id == skill_id).first()
        if not skill:
            return None
        for k, v in kwargs.items():
            if hasattr(skill, k):
                setattr(skill, k, v)
        db.commit()
        db.refresh(skill)
        return skill

    def increment_usage(self, db: Session, skill_id: UUID) -> None:
        skill = db.query(AgentSkill).filter(AgentSkill.id == skill_id).first()
        if skill:
            skill.success_count = (skill.success_count or 0) + 1
            db.commit()

    def delete(self, db: Session, *, user_id: Optional[UUID], name: str, scope: str = "user") -> bool:
        skill = self.get_by_name(db, user_id=user_id, name=name, scope=scope)
        if not skill:
            return False
        db.delete(skill)
        db.commit()
        return True

    def delete_by_id(self, db: Session, skill_id: UUID) -> bool:
        skill = db.query(AgentSkill).filter(AgentSkill.id == skill_id).first()
        if not skill:
            return False
        db.delete(skill)
        db.commit()
        return True

    def upsert_file_skill(self, db: Session, *, user_id: Optional[UUID], scope: str,
                          name: str, description: str, procedure: str,
                          file_path: str, **kwargs) -> AgentSkill:
        """Insert or update a file-backed skill (discovered from filesystem)."""
        existing = db.query(AgentSkill).filter(
            AgentSkill.source == "file",
            AgentSkill.file_path == file_path,
        ).first()
        if existing:
            existing.description = description
            existing.procedure = procedure
            existing.scope = scope
            for k, v in kwargs.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            db.commit()
            db.refresh(existing)
            return existing
        return self.create(
            db, user_id=user_id, scope=scope,
            name=name, description=description, procedure=procedure,
            source="file", file_path=file_path, created_by="imported", **kwargs,
        )


agent_skill = CRUDAgentSkill()
