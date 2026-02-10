import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=True)
    description = Column(String, nullable=True)
    status = Column(String, default="draft") # draft, processing, review, completed, failed
    schema_id = Column(UUID(as_uuid=True), ForeignKey("document_schemas.id"), nullable=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    schema = relationship("DocumentSchema")
    documents = relationship("Document", back_populates="job", cascade="all, delete-orphan")
    user = relationship("User")
