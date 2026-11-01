import uuid
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)
    # "text" | "ui_action" (a click on a panel button). A ui_action message's
    # content is display text the server wrote; the model reads ui_action
    # {surface_id, name, document_ids, source_component_id, timestamp}.
    kind = Column(String(16), nullable=False, default="text", server_default="text")
    content = Column(Text, nullable=True)
    ui_action = Column(JSONB, nullable=True)
    tool_calls = Column(JSONB, nullable=True)
    tool_call_id = Column(String(100), nullable=True)
    tool_name = Column(String(100), nullable=True)
    tool_result = Column(JSONB, nullable=True)
    iteration = Column(Integer, nullable=True)
    model_used = Column(String(100), nullable=True)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("AgentConversation", back_populates="messages")