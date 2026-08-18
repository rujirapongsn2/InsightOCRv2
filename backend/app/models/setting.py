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
    ocr_endpoint = Column(String, default="https://111.223.37.41:9001/v3/ai-process-file")
    structured_output_endpoint = Column(String, default="https://111.223.37.41:9001/structured-output")
    schema_suggestion_endpoint = Column(String, default="https://111.223.37.41:9001/suggest-schema")
    test_endpoint = Column(String, default="https://111.223.37.41:9001/me")

    # Legacy field for backward compatibility (will be removed in future)
    api_endpoint = Column(String, nullable=True)

    api_token = Column(String, nullable=True)
    verify_ssl = Column(Boolean, default=False)
    ocr_fallback_enabled = Column(Boolean, default=False, nullable=False)
    ocr_fallback_api_key = Column(String, nullable=True)

    # Admin-managed Microsoft delegated OAuth configuration. The secret is
    # encrypted with the application SECRET_KEY before it reaches the DB.
    microsoft_oauth_client_id = Column(String, nullable=True)
    microsoft_oauth_client_secret_encrypted = Column(String, nullable=True)
    microsoft_oauth_tenant = Column(String, nullable=True)
    microsoft_oauth_redirect_uri = Column(String, nullable=True)
    microsoft_oauth_scope = Column(String, nullable=True)

    # Admin-managed Google delegated OAuth configuration. The secret is
    # encrypted with the application SECRET_KEY before it reaches the DB.
    google_oauth_client_id = Column(String, nullable=True)
    google_oauth_client_secret_encrypted = Column(String, nullable=True)
    google_oauth_redirect_uri = Column(String, nullable=True)
    google_oauth_scope = Column(String, nullable=True)
