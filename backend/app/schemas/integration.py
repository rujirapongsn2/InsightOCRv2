"""Integration schemas for API request/response validation."""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID


class IntegrationConfigBase(BaseModel):
    """Base configuration fields shared across all integration types."""
    # API type fields
    method: Optional[str] = None
    endpoint: Optional[str] = None
    authHeader: Optional[str] = None
    headersJson: Optional[str] = None
    payloadTemplate: Optional[str] = None

    # Workflow type fields
    webhookUrl: Optional[str] = None
    parameters: Optional[str] = None

    # LLM type fields
    model: Optional[str] = None
    apiKey: Optional[str] = None
    baseUrl: Optional[str] = None
    instructions: Optional[str] = None
    reasoningEffort: Optional[str] = None


class IntegrationCreate(BaseModel):
    """Schema for creating a new integration."""
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., pattern="^(api|workflow|llm)$")
    description: Optional[str] = None
    status: str = Field(default="active", pattern="^(active|paused)$")
    config: Dict[str, Any] = Field(default_factory=dict)


class IntegrationUpdate(BaseModel):
    """Schema for updating an integration."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    type: Optional[str] = Field(None, pattern="^(api|workflow|llm)$")
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|paused)$")
    config: Optional[Dict[str, Any]] = None


class IntegrationResponse(BaseModel):
    """Schema for integration response."""
    id: UUID
    user_id: UUID
    name: str
    type: str
    description: Optional[str]
    status: str
    config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class IntegrationListResponse(BaseModel):
    """Schema for list of integrations."""
    integrations: list[IntegrationResponse]
    total: int
