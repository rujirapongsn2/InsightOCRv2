"""Add admin-managed Google OAuth configuration."""

from alembic import op
import sqlalchemy as sa


revision = "0015_google_oauth"
down_revision = "0014_microsoft_oauth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settings", sa.Column("google_oauth_client_id", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("google_oauth_client_secret_encrypted", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("google_oauth_redirect_uri", sa.String(), nullable=True))
    op.add_column("settings", sa.Column("google_oauth_scope", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("settings", "google_oauth_scope")
    op.drop_column("settings", "google_oauth_redirect_uri")
    op.drop_column("settings", "google_oauth_client_secret_encrypted")
    op.drop_column("settings", "google_oauth_client_id")
