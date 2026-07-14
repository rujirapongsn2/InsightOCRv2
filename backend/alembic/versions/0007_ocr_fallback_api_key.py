"""Add an optional UI-managed OCR fallback API key."""
from alembic import op
import sqlalchemy as sa

revision = "0007_ocr_fallback_api_key"
down_revision = "0006_ocr_fallback_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE IF EXISTS settings "
        "ADD COLUMN IF NOT EXISTS ocr_fallback_api_key VARCHAR"
    ))


def downgrade() -> None:
    raise NotImplementedError("0007 is forward-only")
