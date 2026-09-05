from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.db.base_class import Base


class AISettings(Base):
    """AI/LLM Settings for field suggestion feature"""
    __tablename__ = "ai_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)  # e.g., "softnix_genai"
    display_name = Column(String, nullable=False)  # e.g., "Softnix GenAI"
    api_url = Column(String, nullable=False)  # External API endpoint
    api_key = Column(String, nullable=False)  # API Key for authentication
    is_active = Column(Boolean, default=True)  # Enable/disable this setting
    is_default = Column(Boolean, default=False)  # Default AI provider (OCR/suggestion)

    # Agent-specific fields
    model = Column(String, default="gpt-4o-mini")
    is_agent_provider = Column(Boolean, default=False)  # Use as Agent's LLM backend
    # A provider may support chat completions without supporting the native
    # function/tool calls required by workflow Agent nodes.
    supports_tool_calling = Column(Boolean, default=False)
    # Result of the server-side capability check performed when a provider is
    # saved.  Keeping the failure reason prevents administrators from having
    # to guess why Agent mode is unavailable.
    agent_tools_checked_at = Column(DateTime(timezone=True), nullable=True)
    agent_tools_verification_error = Column(String, nullable=True)
    # Dedicated backend for the AI workflow builder. When unset, the builder
    # falls back to the agent provider / active default (same as the rest of the system).
    is_workflow_builder_provider = Column(Boolean, default=False)
    provider_type = Column(String, default="completion_messages")  # "openai_compatible" | "completion_messages"

    # Additional settings (JSON-like format in description)
    description = Column(String)  # Optional description

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(UUID(as_uuid=True))  # User who created this setting

    def __repr__(self):
        return f"<AISettings {self.name}>"
