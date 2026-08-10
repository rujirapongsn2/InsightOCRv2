"""Merge the job cascade and OCR fallback migration branches."""

from alembic import op


revision = "0008_merge_job_fk_ocr"
down_revision = ("0006_job_fk_cascade", "0007_ocr_fallback_api_key")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise NotImplementedError("0008 is forward-only")
