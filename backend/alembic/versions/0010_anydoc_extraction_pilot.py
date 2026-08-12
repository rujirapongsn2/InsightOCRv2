"""Add opt-in AnyDoc extraction profiles and document metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0010_anydoc_pilot"
down_revision = "0009_softnix_genai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_schemas",
        sa.Column("extraction_profile", sa.String(), nullable=False, server_default="legacy"),
    )
    op.add_column("documents", sa.Column("extraction_metadata", sa.JSON(), nullable=True))
    op.alter_column("document_schemas", "extraction_profile", server_default=None)


def downgrade() -> None:
    op.drop_column("documents", "extraction_metadata")
    op.drop_column("document_schemas", "extraction_profile")
