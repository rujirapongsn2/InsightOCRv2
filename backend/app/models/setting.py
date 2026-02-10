import uuid
from sqlalchemy import Column, String, Boolean
from sqlalchemy.dialects.postgresql import UUID
from app.db.base_class import Base

class Setting(Base):
    __tablename__ = "settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    ocr_engine = Column(String, default="default")
    model = Column(String, default="default")

    # Separate endpoints for different purposes
    ocr_endpoint = Column(String, default="https://111.223.37.41:9001/ai-process-file")
    test_endpoint = Column(String, default="https://111.223.37.41:9001/me")

    # Legacy field for backward compatibility (will be removed in future)
    api_endpoint = Column(String, nullable=True)

    api_token = Column(String, nullable=True)
    verify_ssl = Column(Boolean, default=False)
