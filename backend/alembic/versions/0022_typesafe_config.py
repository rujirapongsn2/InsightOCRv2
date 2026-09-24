"""Add TypeSafe (Jev) configuration to settings."""
from alembic import op
import sqlalchemy as sa

revision = "0022_typesafe_config"
down_revision = "0021_agent_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(
        sa.text("ALTER TABLE settings ADD COLUMN IF NOT EXISTS typesafe_endpoint VARCHAR")
    )
    op.get_bind().execute(
        sa.text("ALTER TABLE settings ADD COLUMN IF NOT EXISTS typesafe_api_key VARCHAR")
    )


def downgrade():
    raise NotImplementedError("TypeSafe config migration is forward-only")
