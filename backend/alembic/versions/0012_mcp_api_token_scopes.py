"""Add scopes to Personal API Tokens for controlled MCP actions."""

from alembic import op
import sqlalchemy as sa


revision = "0012_mcp_token_scopes"
down_revision = "0011_standardize_anydoc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "api_access_tokens",
        sa.Column(
            "scopes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[\"mcp:read\"]'::json"),
        ),
    )
    op.alter_column("api_access_tokens", "scopes", server_default=None)


def downgrade() -> None:
    op.drop_column("api_access_tokens", "scopes")
