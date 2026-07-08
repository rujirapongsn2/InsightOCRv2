import uuid
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, func, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class Workflow(Base):
    """A user-defined deterministic workflow (DAG of nodes + edges)."""
    __tablename__ = "workflows"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String, nullable=True)
    # Full builder definition: {"nodes": [...], "edges": [...]}
    definition = Column(JSONB, nullable=False, default=dict)
    is_active = Column(Boolean, default=True)

    # Scheduling (cron expression, e.g. "*/15 * * * *"); null = manual only
    schedule_cron = Column(String(100), nullable=True)
    schedule_enabled = Column(Boolean, default=False)
    next_run_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)

    # Inbound webhook trigger (secret is only revealed once when generated)
    webhook_enabled = Column(Boolean, default=False)
    webhook_secret_hash = Column(Text, nullable=True)
    webhook_secret_created_at = Column(DateTime(timezone=True), nullable=True)
    webhook_last_triggered_at = Column(DateTime(timezone=True), nullable=True)

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User")
    runs = relationship("WorkflowRun", back_populates="workflow", cascade="all, delete-orphan")


class WorkflowRun(Base):
    """One execution of a workflow."""
    __tablename__ = "workflow_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), default="queued", index=True)  # queued, running, succeeded, failed, cancelled
    trigger_type = Column(String(20), default="manual")  # manual, schedule
    # Optional input payload provided at trigger time
    trigger_input = Column(JSONB, nullable=True)
    # Snapshot of the definition at run time (so edits don't affect history)
    definition_snapshot = Column(JSONB, nullable=True)
    result = Column(JSONB, nullable=True)
    result_node_id = Column(String(100), nullable=True)
    error = Column(Text, nullable=True)
    task_id = Column(String, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    triggered_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)

    workflow = relationship("Workflow", back_populates="runs")
    node_runs = relationship("WorkflowNodeRun", back_populates="run", cascade="all, delete-orphan")


class WorkflowNodeRun(Base):
    """Per-node activity within a run — powers the interactive activity view."""
    __tablename__ = "workflow_node_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("workflow_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    node_id = Column(String(100), nullable=False)
    node_type = Column(String(50), nullable=False)
    node_label = Column(String(255), nullable=True)
    status = Column(String(20), default="pending")  # pending, running, succeeded, failed, skipped
    input = Column(JSONB, nullable=True)
    output = Column(JSONB, nullable=True)
    logs = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    run = relationship("WorkflowRun", back_populates="node_runs")
