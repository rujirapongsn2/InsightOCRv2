import uuid
from sqlalchemy import Column, String, Integer, Float, JSON, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False) # Path in MinIO/S3
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    
    status = Column(String, default="uploaded") # uploaded, ocr_processing, ocr_completed, extraction_pending, extraction_completed, reviewed, failed
    
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
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    schema_id = Column(UUID(as_uuid=True), ForeignKey("document_schemas.id"), nullable=True)
    task_id = Column(String, nullable=True)

    # Relationships
    job = relationship("Job", back_populates="documents")
    schema = relationship("DocumentSchema")
