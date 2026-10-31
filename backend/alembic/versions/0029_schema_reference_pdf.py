"""Persist consented schema reference PDFs independently of test samples."""
from alembic import op
import sqlalchemy as sa

revision = "0029_schema_reference_pdf"
down_revision = "0028_confirmed_review_decision"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("document_schemas", sa.Column("reference_pdf", sa.JSON(), nullable=True))
    op.create_table("schema_reference_deletions",
                    sa.Column("storage_path", sa.String(), primary_key=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))


def downgrade():
    connection = op.get_bind()
    references = connection.execute(sa.text(
        "SELECT count(*) FROM document_schemas WHERE reference_pdf IS NOT NULL "
        "AND CAST(reference_pdf AS TEXT) != 'null'"
    )).scalar()
    pending = connection.execute(sa.text("SELECT count(*) FROM schema_reference_deletions")).scalar()
    if references or pending:
        raise RuntimeError("Remove reference PDFs and finish pending storage cleanup before downgrading")
    op.drop_table("schema_reference_deletions")
    op.drop_column("document_schemas", "reference_pdf")
