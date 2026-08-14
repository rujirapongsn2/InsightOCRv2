"""Harden MCP-only token boundaries and idempotent actions."""

from alembic import op
import sqlalchemy as sa


revision = "0013_harden_mcp_actions"
down_revision = "0012_mcp_token_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_access_tokens",
        sa.Column("mcp_access_only", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Preserve the action tokens introduced in phase 2 while keeping all
    # pre-existing tokens compatible with the ordinary REST API.
    op.execute(
        """
        UPDATE api_access_tokens
        SET mcp_access_only = TRUE
        WHERE scopes::jsonb <> '["mcp:read"]'::jsonb
        """
    )
    op.alter_column("api_access_tokens", "mcp_access_only", server_default=None)

    op.add_column("jobs", sa.Column("mcp_idempotency_key", sa.String(length=64), nullable=True))
    op.create_index("ix_jobs_mcp_idempotency_key", "jobs", ["mcp_idempotency_key"], unique=True)

    op.add_column("documents", sa.Column("mcp_idempotency_key", sa.String(length=64), nullable=True))
    op.create_index("ix_documents_mcp_idempotency_key", "documents", ["mcp_idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_documents_mcp_idempotency_key", table_name="documents")
    op.drop_column("documents", "mcp_idempotency_key")
    op.drop_index("ix_jobs_mcp_idempotency_key", table_name="jobs")
    op.drop_column("jobs", "mcp_idempotency_key")
    op.drop_column("api_access_tokens", "mcp_access_only")
