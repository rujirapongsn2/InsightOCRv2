import uuid
from sqlalchemy import Column, String, JSON, DateTime, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class DocumentSchema(Base):
    __tablename__ = "document_schemas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String, index=True, nullable=False)
    description = Column(String, nullable=True)
    document_type = Column(String, nullable=False) # e.g., "invoice", "receipt"
    ocr_engine = Column(String, default="tesseract")
    
    # List of fields definition
    # [
    #   {
    #     "name": "total_amount",
    #     "type": "currency",
    #     "description": "Total amount including VAT",
    #     "required": true
    #   }
    # ]
    fields = Column(JSON, default=[])

    # Reference to template if created from a template (optional)
    template_id = Column(UUID(as_uuid=True), ForeignKey("schema_templates.id"), nullable=True)

    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    creator = relationship("User")
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
