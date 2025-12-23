"""Integration model for storing integration configurations."""

from sqlalchemy import Column, String, Text, DateTime, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, JSONB
from datetime import datetime
import uuid
import enum

from app.db.base_class import Base


class IntegrationType(str, enum.Enum):
    """Integration types."""
    API = "api"
    WORKFLOW = "workflow"
    LLM = "llm"


class IntegrationStatus(str, enum.Enum):
    """Integration status."""
    ACTIVE = "active"
    PAUSED = "paused"


class Integration(Base):
    """Integration configuration model."""

    __tablename__ = "integrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    type = Column(SQLEnum(IntegrationType), nullable=False)
    description = Column(Text)
    status = Column(SQLEnum(IntegrationStatus), default=IntegrationStatus.ACTIVE, nullable=False)

    # Configuration stored as JSON (encrypted sensitive fields will be handled separately)
    config = Column(JSONB, nullable=False, default={})

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="integrations")

    def __repr__(self):
        return f"<Integration(id={self.id}, name={self.name}, type={self.type}, status={self.status})>"
