from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field


# Base schema with common fields
class AISettingsBase(BaseModel):
    name: str = Field(..., description="Unique name for this AI provider")
    display_name: str = Field(..., description="Display name for UI")
    api_url: str = Field(..., description="External API endpoint URL")
    api_key: str = Field(..., description="API key for authentication")
    is_active: bool = Field(default=True, description="Whether this setting is active")
    is_default: bool = Field(default=False, description="Whether this is the default provider")
    description: Optional[str] = Field(None, description="Optional description")


# Schema for creating new AI settings
class AISettingsCreate(AISettingsBase):
    pass


# Schema for updating AI settings
class AISettingsUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    api_url: Optional[str] = None
    api_key: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    description: Optional[str] = None


# Schema for reading AI settings (response)
class AISettings(AISettingsBase):
    id: UUID
    created_at: datetime
    updated_at: Optional[datetime]
    created_by: Optional[UUID]

    class Config:
        from_attributes = True


# Schema for reading AI settings without exposing API key
class AISettingsPublic(BaseModel):
    id: UUID
    name: str
    display_name: str
    api_url: str
    is_active: bool
    is_default: bool
    description: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


# Schema for field suggestion request
class FieldSuggestionRequest(BaseModel):
    ocr_content: str = Field(..., description="OCR extracted text content")
    document_type: Optional[str] = Field(None, description="Type of document (invoice, receipt, etc.)")
    ai_provider: Optional[str] = Field(None, description="Specific AI provider to use (uses default if not specified)")


# Schema for suggested field
class SuggestedField(BaseModel):
    name: str = Field(..., description="Suggested field name (snake_case)")
    type: str = Field(..., description="Field type (text, number, date, currency, boolean)")
    description: str = Field(..., description="Field description")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0-1)")
    example_value: Optional[str] = Field(None, description="Example value extracted from document")


# Schema for field suggestion response
class FieldSuggestionResponse(BaseModel):
    suggested_fields: list[SuggestedField]
    confidence_score: float = Field(..., ge=0.0, le=1.0, description="Overall confidence score")
    document_preview: Optional[str] = Field(None, description="Preview of OCR text")
    provider_used: str = Field(..., description="AI provider that was used")
