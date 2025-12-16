import uuid
from sqlalchemy import Column, String, JSON, DateTime, Boolean, Integer, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class SchemaTemplate(Base):
    __tablename__ = "schema_templates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(String, nullable=True)
    document_type = Column(String, nullable=False)  # e.g., "invoice", "receipt", "po", "contract"
    category = Column(String, default="general")  # e.g., "financial", "legal", "hr"

    # True for built-in system templates, False for user-created templates
    is_system_template = Column(Boolean, default=False, nullable=False)

    # Optional thumbnail/preview image URL
    thumbnail_url = Column(String, nullable=True)

    # Track how many times this template has been used
    usage_count = Column(Integer, default=0, nullable=False)

    # Pre-configured field definitions (same structure as DocumentSchema.fields)
    # [
    #   {
    #     "name": "total_amount",
    #     "type": "currency",
    #     "description": "Total amount including VAT",
    #     "required": true,
    #     "validation_rules": {},
    #     "help_text": "The final total including all taxes",
    #     "example": "1,234.56",
    #     "order": 1
    #   }
    # ]
    fields = Column(JSON, default=[], nullable=False)

    # User who created this template (null for system templates)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    creator = relationship("User")

    # Active/inactive flag for soft delete
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
