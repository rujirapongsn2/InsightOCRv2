import uuid
from sqlalchemy import Column, String, JSON, DateTime, Integer, Text, func, ForeignKey, UniqueConstraint
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
    # Internal compatibility metadata. Supported documents use AnyDoc hybrid.
    extraction_profile = Column(String, nullable=False, default="anydoc_hybrid")
    
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
    
    current_version = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class SchemaVersion(Base):
    """Immutable snapshot of a schema's fields; documents record the one used."""

    __tablename__ = "schema_versions"
    __table_args__ = (UniqueConstraint("schema_id", "version", name="uq_schema_versions_schema_version"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_id = Column(UUID(as_uuid=True), ForeignKey("document_schemas.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    fields = Column(JSON, nullable=False)
    fields_hash = Column(String(64), nullable=False)
    note = Column(String, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    creator = relationship("User")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SchemaSample(Base):
    """A sample document kept (with consent) as the schema's test set.

    ``expected`` holds the values a person confirmed as correct, keyed by field
    name; ``last_run`` the most recent test-set comparison for this sample.
    """

    __tablename__ = "schema_samples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    schema_id = Column(UUID(as_uuid=True), ForeignKey("document_schemas.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    storage_path = Column(String, nullable=False)
    text = Column(Text, nullable=False)
    expected = Column(JSON, nullable=False, default=dict)
    last_run = Column(JSON, nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
