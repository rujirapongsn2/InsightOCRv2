from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Definition pieces ────────────────────────────────────────────────
class WorkflowNode(BaseModel):
    id: str
    type: str
    position: Dict[str, float] = Field(default_factory=dict)
    data: Dict[str, Any] = Field(default_factory=dict)  # {label, config: {...}}


class WorkflowEdge(BaseModel):
    id: str
    source: str
    target: str
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None


class WorkflowDefinition(BaseModel):
    nodes: List[WorkflowNode] = Field(default_factory=list)
    edges: List[WorkflowEdge] = Field(default_factory=list)


# ── Workflow CRUD ────────────────────────────────────────────────────
class WorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None
    definition: Optional[WorkflowDefinition] = None
    schedule_cron: Optional[str] = None
    schedule_enabled: bool = False
    is_active: bool = True


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    definition: Optional[WorkflowDefinition] = None
    schedule_cron: Optional[str] = None
    schedule_enabled: Optional[bool] = None
    is_active: Optional[bool] = None


class WorkflowResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    definition: Dict[str, Any]
    is_active: bool
    schedule_cron: Optional[str] = None
    schedule_enabled: bool = False
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    webhook_enabled: bool = False
    webhook_secret_created_at: Optional[datetime] = None
    webhook_last_triggered_at: Optional[datetime] = None
    user_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkflowListResponse(BaseModel):
    workflows: List[WorkflowResponse]
    total: int


# ── Export / Import ──────────────────────────────────────────────────
class WorkflowExport(BaseModel):
    schema_version: int = 1
    name: str
    description: Optional[str] = None
    schedule_cron: Optional[str] = None
    schedule_enabled: bool = False
    definition: Dict[str, Any] = Field(default_factory=dict)


class WorkflowImportRequest(WorkflowExport):
    pass


class WorkflowValidationIssue(BaseModel):
    node_id: str = ""
    level: str = "error"        # error | warning
    field: Optional[str] = None
    message: str


class WorkflowImportResponse(BaseModel):
    workflow: WorkflowResponse
    warnings: List[WorkflowValidationIssue] = Field(default_factory=list)


# ── Runs ─────────────────────────────────────────────────────────────
class WorkflowRunRequest(BaseModel):
    input: Optional[Dict[str, Any]] = None


class WorkflowNodeRunResponse(BaseModel):
    id: UUID
    node_id: str
    node_type: str
    node_label: Optional[str] = None
    status: str
    input: Optional[Any] = None
    output: Optional[Any] = None
    logs: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkflowRunResponse(BaseModel):
    id: UUID
    workflow_id: UUID
    status: str
    trigger_type: str
    trigger_input: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    result_node_id: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    node_runs: List[WorkflowNodeRunResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class WorkflowRunListItem(BaseModel):
    id: UUID
    workflow_id: UUID
    status: str
    trigger_type: str
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkflowRunListResponse(BaseModel):
    runs: List[WorkflowRunListItem]
    total: int


class WorkflowWebhookSecretResponse(BaseModel):
    webhook_enabled: bool
    webhook_url: str
    secret: str
    secret_created_at: datetime


class WorkflowWebhookResultResponse(BaseModel):
    run_id: UUID
    workflow_id: UUID
    status: str
    result: Optional[Any] = None
    result_node_id: Optional[str] = None
    error: Optional[str] = None
    created_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


# ── AI variable finder ───────────────────────────────────────────────
class VariableCandidate(BaseModel):
    token: str                       # e.g. "{{jobs_1.records.0.Invoice_No}}"
    label: Optional[str] = None      # human label e.g. "เลขที่ใบแจ้งหนี้"
    sample: Optional[str] = None     # sample value from last run
    type: Optional[str] = None       # string | number | object | array | ...


class SuggestVariablesRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    candidates: List[VariableCandidate] = Field(default_factory=list)
    integration_id: Optional[str] = None


class VariableSuggestion(BaseModel):
    token: str
    reason: str = ""
    confidence: str = "medium"       # high | medium | low


class SuggestVariablesResponse(BaseModel):
    suggestions: List[VariableSuggestion] = Field(default_factory=list)
