"""Add the Softnix GenAI integration type."""

from alembic import op


revision = "0009_softnix_genai"
down_revision = "0008_merge_job_fk_ocr"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE integrationtype ADD VALUE IF NOT EXISTS 'SOFTNIX_GENAI'"
        )


def downgrade() -> None:
    raise NotImplementedError("PostgreSQL enum values are forward-only")
