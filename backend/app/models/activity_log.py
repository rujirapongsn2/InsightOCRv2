import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class ActivityLog(Base):
    """
    Activity Log model for audit purposes.
    Tracks user activities including login/logout and resource operations.
    """
    __tablename__ = "activity_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    
    # Action type: login, logout, upload_document, process_document, create_job, etc.
    action = Column(String, nullable=False, index=True)
    
    # Resource information (optional)
    resource_type = Column(String, nullable=True)  # document, job, schema, user
    resource_id = Column(UUID(as_uuid=True), nullable=True)
    
    # Additional details as JSON
    details = Column(JSONB, nullable=True)
    
    # Client information
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    
    # Timestamp
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationship
    user = relationship("User")
