"""Store the latest automatic Agent-tools verification result.

Revision ID: 0019_agent_tools_status
Revises: 0018_require_tool_verify
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_agent_tools_status"
down_revision = "0018_require_tool_verify"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_settings", sa.Column("agent_tools_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_settings", sa.Column("agent_tools_verification_error", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_settings", "agent_tools_verification_error")
    op.drop_column("ai_settings", "agent_tools_checked_at")
