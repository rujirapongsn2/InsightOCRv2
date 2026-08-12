"""Make AnyDoc hybrid the schema default and retire shadow mode."""

from alembic import op
import sqlalchemy as sa


revision = "0011_standardize_anydoc"
down_revision = "0010_anydoc_pilot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE document_schemas "
        "SET extraction_profile = 'anydoc_hybrid' "
        "WHERE extraction_profile IN ('legacy', 'anydoc_shadow') OR extraction_profile IS NULL"
    )
    op.alter_column(
        "document_schemas",
        "extraction_profile",
        existing_type=sa.String(),
        server_default="anydoc_hybrid",
    )


def downgrade() -> None:
    op.alter_column(
        "document_schemas",
        "extraction_profile",
        existing_type=sa.String(),
        server_default=None,
    )
