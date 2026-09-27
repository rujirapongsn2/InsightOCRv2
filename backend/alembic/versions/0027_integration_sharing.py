"""Let admins share an integration with every user."""
from alembic import op
import sqlalchemy as sa

revision = "0027_integration_sharing"
down_revision = "0026_pending_action_run"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("integrations", sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("integrations", "is_shared")
