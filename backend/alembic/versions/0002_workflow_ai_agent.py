"""AI-agent workflow builder: conversation kind + credential-request pending actions.

- agent_conversations gains a ``kind`` discriminator ("document" | "workflow_builder")
  and ``job_id`` becomes nullable so a workflow-builder conversation isn't tied to a Job.
- agent_pending_actions gains a ``kind`` ("confirmation" | "credential_request") and a
  ``result`` JSONB so the credential-card flow can hand a created integration/provider id
  back to the blocked agent loop without the secret ever entering chat.

All statements are idempotent so re-running against any state is safe.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_workflow_ai_agent"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


STATEMENTS = [
    "ALTER TABLE IF EXISTS agent_conversations ADD COLUMN IF NOT EXISTS kind varchar(32) DEFAULT 'document'",
    "ALTER TABLE IF EXISTS agent_conversations ALTER COLUMN job_id DROP NOT NULL",
    "ALTER TABLE IF EXISTS agent_pending_actions ADD COLUMN IF NOT EXISTS kind varchar(32) DEFAULT 'confirmation'",
    "ALTER TABLE IF EXISTS agent_pending_actions ADD COLUMN IF NOT EXISTS result jsonb",
]


def upgrade() -> None:
    bind = op.get_bind()
    for stmt in STATEMENTS:
        bind.execute(sa.text(stmt))


def downgrade() -> None:
    raise NotImplementedError("0002 is forward-only")
