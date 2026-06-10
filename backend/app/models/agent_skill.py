import uuid
from sqlalchemy import Column, String, Text, Integer, Float, DateTime, ForeignKey, func, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class AgentSkill(Base):
    """Agent skill following the agentskills.io specification.

    Skills can be DB-native (created via conversation) or file-backed (loaded from SKILL.md).
    """
    __tablename__ = "agent_skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    scope = Column(String(20), nullable=False, default="user", index=True)  # "user" | "system" | "team"

    # ── agentskills.io frontmatter fields ──
    name = Column(String(64), nullable=False)            # lowercase, hyphens, 1-64 chars
    description = Column(Text, nullable=False)            # what + when to use, 1-1024 chars
    license = Column(String(100), nullable=True)          # license name or reference
    compatibility = Column(String(500), nullable=True)    # environment requirements
    metadata_ = Column("metadata", JSONB, nullable=True)  # arbitrary key-value

    # ── Instruction body ──
    procedure = Column(Text, nullable=False)              # markdown body (the SKILL.md content)

    # ── Tool gating (agentskills.io experimental) ──
    allowed_tools = Column(Text, nullable=True)           # space-separated tool names
    tools_used = Column(JSONB, nullable=True)             # tools referenced in procedure

    # ── Activation hint (InsightDOC extension) ──
    trigger_hint = Column(Text, nullable=True)            # when to suggest this skill

    # ── Tracking ──
    success_count = Column(Integer, default=0)
    created_by = Column(String(20), default="user")       # "user" | "agent" | "imported"
    source = Column(String(20), default="db")             # "db" | "file" | "imported"
    file_path = Column(String(500), nullable=True)        # path to SKILL.md on disk (for file-backed)
    version = Column(String(20), nullable=True)           # semver from metadata

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ── Constraints ──
    __table_args__ = (
        # user scope: one skill name per user
        UniqueConstraint("user_id", "name", "scope", name="uq_agent_skill_user_name_scope"),
        # system scope: one skill name globally (user_id is NULL)
        Index("idx_agent_skill_system_name", "name", "scope", unique=True,
              postgresql_where=(user_id.is_(None))),
    )
