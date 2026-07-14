"""Add the configurable OCR fallback switch.

The fallback provider credential stays in the backend environment. This
column only controls whether the provider may be used when the primary OCR
request fails.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_ocr_fallback_provider"
down_revision = "0005_doc_source_file_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.get_bind().execute(sa.text(
        "ALTER TABLE IF EXISTS settings "
        "ADD COLUMN IF NOT EXISTS ocr_fallback_enabled boolean NOT NULL DEFAULT false"
    ))


def downgrade() -> None:
    raise NotImplementedError("0006 is forward-only")
