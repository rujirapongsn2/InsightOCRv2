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
    user_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkflowListResponse(BaseModel):
    workflows: List[WorkflowResponse]
    total: int


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
