"""IntegrationResult model for storing integration output history."""

import uuid
import enum
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.base_class import Base


class IntegrationResultStatus(str, enum.Enum):
    SUCCESS = "success"
    ERROR = "error"


class IntegrationResult(Base):
    """Stores the output of each integration run so users can review history."""

    __tablename__ = "integration_results"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(UUID(as_uuid=True), ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    integration_type = Column(String(20), nullable=True)  # llm, api, workflow
    integration_name = Column(String(255), nullable=True)
    status = Column(String(20), default="success", nullable=False)
    output = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    model_used = Column(String(100), nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    job = relationship("Job", backref="integration_results")
    integration = relationship("Integration")
    user = relationship("User")

    def __repr__(self):
        return f"<IntegrationResult(id={self.id}, job_id={self.job_id}, status={self.status})>"
