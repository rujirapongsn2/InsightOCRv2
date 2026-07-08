import uuid
from sqlalchemy import Column, String, Integer, Float, JSON, DateTime, ForeignKey, func, Index, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False) # Path in MinIO/S3
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)

    # Origin file id when imported from an external source (Google Drive /
    # OneDrive item id). Used to dedup re-imports of the same folder — a
    # scheduled import must not re-ingest (and re-OCR) files it already pulled.
    source_file_id = Column(String, nullable=True)

    status = Column(String, default="uploaded", index=True) # uploaded, ocr_processing, ocr_completed, extraction_pending, extraction_completed, reviewed, failed
    
    ocr_text = Column(String, nullable=True)
    ocr_confidence = Column(Float, nullable=True)

    # Multi-page OCR support
    page_count = Column(Integer, nullable=True)
    ocr_pages = Column(JSON, nullable=True)
    processing_error = Column(String, nullable=True)

    extracted_data = Column(JSON, nullable=True)
    reviewed_data = Column(JSON, nullable=True)
    review_decision = Column(String, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    extraction_confidence = Column(Float, nullable=True)
    
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    schema_id = Column(UUID(as_uuid=True), ForeignKey("document_schemas.id"), nullable=True, index=True)
    task_id = Column(String, nullable=True)

    # Relationships
    job = relationship("Job", back_populates="documents")
    schema = relationship("DocumentSchema")

    __table_args__ = (
        # Hard guarantee against a file being imported into the same job twice,
        # even under two concurrent import runs (the in-memory skip covers the
        # common case; this covers the race). Partial index so manual uploads,
        # which have no source_file_id, are unaffected.
        Index(
            "uq_documents_job_source_file",
            "job_id",
            "source_file_id",
            unique=True,
            postgresql_where=text("source_file_id IS NOT NULL"),
        ),
    )
