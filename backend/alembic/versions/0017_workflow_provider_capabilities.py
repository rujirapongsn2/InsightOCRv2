"""Record whether an AI provider supports native workflow Agent tools."""

from alembic import op
import sqlalchemy as sa


# The existing alembic_version column is VARCHAR(32), so keep this identifier
# within that deployed database constraint.
revision = "0017_workflow_provider_caps"
down_revision = "0016_add_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_settings",
        sa.Column(
            "supports_tool_calling",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("ai_settings", "supports_tool_calling", server_default=None)


def downgrade() -> None:
    op.drop_column("ai_settings", "supports_tool_calling")
