import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.base_class import Base


class AgentPendingAction(Base):
    __tablename__ = "agent_pending_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # "confirmation" (approve/reject a tool) | "credential_request" (collect a key via card)
    kind = Column(String(32), nullable=False, default="confirmation")
    tool_name = Column(String(100), nullable=False)
    tool_arguments = Column(JSONB, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(20), default="pending", index=True)
    # Carries the resolution payload back to the blocked loop (e.g. the created
    # integration_id/ai_provider_id for a credential_request). Never holds a secret.
    result = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)