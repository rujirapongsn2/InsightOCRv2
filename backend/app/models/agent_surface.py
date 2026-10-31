from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.db.base_class import Base


class AgentSurface(Base):
    """A panel shown in a conversation, with the state only the server decides.

    status: a panel with actions is "active" until the user clicks one of them
    ("answered") or a newer panel appears in the conversation ("superseded").
    A panel without actions stays "active": nothing on it can go stale in a
    way a click could act on.

    A row of its own rather than fields on the tool result: a status change is
    a conditional update of one small row (two clicks cannot both win), and a
    conversation's statuses are read without loading its messages.
    """

    __tablename__ = "agent_surfaces"

    surface_id = Column(String(64), primary_key=True)
    conversation_id = Column(
        UUID(as_uuid=True), ForeignKey("agent_conversations.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    tool_name = Column(String(100), nullable=False)
    # [{"component_id": "approve", "name": "approve_documents"}]: the buttons the panel offered.
    actions = Column(JSONB, nullable=False, default=list)
    # The documents a click may name: the panel's rows, resolved against the job when it was shown.
    document_ids = Column(JSONB, nullable=False, default=list)
    status = Column(String(16), nullable=False, default="active")
    # When the panel's data was computed; the UI shows it as "ข้อมูล ณ ...".
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    answered_at = Column(DateTime(timezone=True), nullable=True)
