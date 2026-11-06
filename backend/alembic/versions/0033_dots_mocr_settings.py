"""Endpoint and default model for the dots.mocr OCR engine."""
from alembic import op
import sqlalchemy as sa

revision = "0033_dots_mocr_settings"
down_revision = "0032_unfinished_call_results"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text("ALTER TABLE settings ADD COLUMN IF NOT EXISTS dots_mocr_endpoint VARCHAR"))
    op.get_bind().execute(sa.text("ALTER TABLE settings ADD COLUMN IF NOT EXISTS dots_mocr_model VARCHAR"))


def downgrade():
    op.drop_column("settings", "dots_mocr_model")
    op.drop_column("settings", "dots_mocr_endpoint")
