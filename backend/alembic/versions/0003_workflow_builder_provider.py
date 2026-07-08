"""Dedicated AI provider for the workflow builder.

Adds ai_settings.is_workflow_builder_provider so an admin can pick the most
capable LLM specifically for the AI workflow builder, independent of the
document agent provider. When unset, the builder falls back to the agent
provider / active default.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_workflow_builder_provider"
down_revision = "0002_workflow_ai_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE IF EXISTS ai_settings "
        "ADD COLUMN IF NOT EXISTS is_workflow_builder_provider boolean DEFAULT false"
    ))


def downgrade() -> None:
    raise NotImplementedError("0003 is forward-only")
