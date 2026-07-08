"""Add documents.source_file_id + partial unique index for import dedup.

Cloud-drive imports now record the origin file id so a repeated or scheduled
import of the same folder does not re-ingest (and re-OCR) files it already
pulled. The partial unique index on (job_id, source_file_id) makes the dedup
race-safe across concurrent import runs; manual uploads (source_file_id NULL)
are unaffected. Idempotent.
"""
from alembic import op
import sqlalchemy as sa

# NOTE: keep revision ids ≤32 chars — alembic_version.version_num is varchar(32).
revision = "0005_doc_source_file_id"
down_revision = "0004_integ_ts_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS source_file_id VARCHAR"
    ))
    bind.execute(sa.text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_job_source_file "
        "ON documents (job_id, source_file_id) WHERE source_file_id IS NOT NULL"
    ))


def downgrade() -> None:
    raise NotImplementedError("0005 is forward-only")
