"""Tie each Agent DOC approval request to the run that made it."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0026_pending_action_run"
down_revision = "0025_ocr_quality_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agent_pending_actions", sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_agent_pending_actions_run", "agent_pending_actions", "agent_runs",
                          ["run_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_agent_pending_actions_run_id", "agent_pending_actions", ["run_id"])


def downgrade():
    op.drop_index("ix_agent_pending_actions_run_id", table_name="agent_pending_actions")
    op.drop_constraint("fk_agent_pending_actions_run", "agent_pending_actions", type_="foreignkey")
    op.drop_column("agent_pending_actions", "run_id")
