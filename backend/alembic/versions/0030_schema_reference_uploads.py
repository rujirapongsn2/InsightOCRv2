"""Track reference PDF uploads before writing objects to storage."""
from alembic import op
import sqlalchemy as sa

revision = "0030_schema_reference_uploads"
down_revision = "0029_schema_reference_pdf"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "schema_reference_uploads",
        sa.Column("storage_path", sa.String(), primary_key=True),
        sa.Column("schema_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_schema_reference_uploads_expires_at", "schema_reference_uploads", ["expires_at"])


def downgrade():
    pending = op.get_bind().execute(sa.text("SELECT count(*) FROM schema_reference_uploads")).scalar()
    if pending:
        raise RuntimeError("Finish pending reference PDF uploads and cleanup before downgrading")
    op.drop_index("ix_schema_reference_uploads_expires_at", table_name="schema_reference_uploads")
    op.drop_table("schema_reference_uploads")
