import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    # "document" (job-scoped assistant) | "workflow_builder" (not job-scoped)
    kind = Column(String(32), nullable=False, default="document")
    # Nullable: workflow-builder conversations are not tied to a Job.
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=True)
    system_prompt = Column(Text, nullable=True)
    max_iterations = Column(Integer, default=15)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    messages = relationship("AgentMessage", back_populates="conversation", cascade="all, delete-orphan", order_by="AgentMessage.created_at")
    job = relationship("Job", back_populates="agent_conversations")
    user = relationship("User")
    integration = relationship("Integration")