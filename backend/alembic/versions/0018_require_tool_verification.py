"""Require a fresh server-side verification for Agent providers."""

from alembic import op


revision = "0018_require_tool_verify"
down_revision = "0017_workflow_provider_caps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Capability flags introduced before verification was server-managed must
    # not be trusted. Admins verify and explicitly assign a provider again.
    op.execute(
        "UPDATE ai_settings "
        "SET supports_tool_calling = false, is_agent_provider = false "
        "WHERE supports_tool_calling = true OR is_agent_provider = true"
    )


def downgrade() -> None:
    # Verification evidence cannot be reconstructed safely.
    pass
