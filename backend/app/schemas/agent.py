from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime
from uuid import UUID

from app.agent.ui_actions import UiActionName


class AgentConversationCreate(BaseModel):
    job_id: UUID
    integration_id: Optional[UUID] = None
    max_iterations: Optional[int] = 15


class AgentMessageCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)


class AgentUiActionCreate(BaseModel):
    """A click on a panel button; the server checks it against the panel it recorded."""
    model_config = ConfigDict(extra="forbid")

    surface_id: str = Field(..., min_length=1, max_length=64)
    name: UiActionName
    source_component_id: str = Field(..., min_length=1, max_length=64)
    document_ids: list[str] = Field(..., min_length=1, max_length=200)


class ConfirmActionRequest(BaseModel):
    approved: bool
    # Sensitive actions must be approved from an explicit user confirmation UI,
    # even when the session's general auto-confirm mode is enabled.
    explicit_confirmation: bool = False


class ResolveCredentialRequest(BaseModel):
    """The frontend saved the key directly to /integrations or /ai-settings and
    reports only the resulting id here — never the secret."""
    integration_id: Optional[UUID] = None
    ai_provider_id: Optional[UUID] = None
    name: Optional[str] = None


class AgentConversationResponse(BaseModel):
    id: UUID
    job_id: UUID
    integration_id: Optional[UUID] = None
    title: Optional[str] = None
    max_iterations: int = 15
    created_at: datetime
    message_count: int = 0

    class Config:
        from_attributes = True


class AgentMessageResponse(BaseModel):
    id: UUID
    role: str
    content: Optional[str] = None
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_result: Optional[dict] = None
    iteration: Optional[int] = None
    model_used: Optional[str] = None
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AgentConversationDetailResponse(AgentConversationResponse):
    messages: list[AgentMessageResponse] = []


# ── Agent Skill Schemas ──────────────────────────────────────────────────────

class AgentSkillCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field(..., min_length=1, max_length=1024)
    procedure: str = Field(..., min_length=1)
    scope: Optional[str] = "user"
    trigger_hint: Optional[str] = None
    tools_used: Optional[list[str]] = None
    allowed_tools: Optional[str] = None
    license: Optional[str] = Field(None, max_length=100)
    compatibility: Optional[str] = Field(None, max_length=500)
    metadata: Optional[dict] = None


class AgentSkillUpdate(BaseModel):
    description: Optional[str] = Field(None, min_length=1, max_length=1024)
    procedure: Optional[str] = Field(None, min_length=1)
    trigger_hint: Optional[str] = None
    tools_used: Optional[list[str]] = None
    allowed_tools: Optional[str] = None
    license: Optional[str] = Field(None, max_length=100)
    compatibility: Optional[str] = Field(None, max_length=500)
    metadata: Optional[dict] = None


class AgentSkillResponse(BaseModel):
    id: UUID
    name: str
    scope: str
    description: str
    procedure: str
    trigger_hint: Optional[str] = None
    tools_used: Optional[list] = None
    allowed_tools: Optional[str] = None
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: Optional[dict] = None
    success_count: int = 0
    created_by: str = "user"
    source: str = "db"
    file_path: Optional[str] = None
    version: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AgentSkillImportRequest(BaseModel):
    file_path: str = Field(..., min_length=1)
    scope: Optional[str] = "user"
    overwrite: bool = False
