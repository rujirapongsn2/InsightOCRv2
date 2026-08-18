"""Add admin-managed Microsoft OAuth configuration."""

from alembic import op
import sqlalchemy as sa


revision = "0014_microsoft_oauth"
down_revision = "0013_harden_mcp_actions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("microsoft_oauth_client_id", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("microsoft_oauth_client_secret_encrypted", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("microsoft_oauth_tenant", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("microsoft_oauth_redirect_uri", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("microsoft_oauth_scope", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("settings", "microsoft_oauth_scope")
    op.drop_column("settings", "microsoft_oauth_redirect_uri")
    op.drop_column("settings", "microsoft_oauth_tenant")
    op.drop_column("settings", "microsoft_oauth_client_secret_encrypted")
    op.drop_column("settings", "microsoft_oauth_client_id")
