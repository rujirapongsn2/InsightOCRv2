"""Schema versions and stored sample documents (Schema Studio phase 2)."""
import hashlib
import json
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0023_schema_versions_samples"
down_revision = "0022_typesafe_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schema_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("schema_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("fields_hash", sa.String(length=64), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["schema_id"], ["document_schemas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("schema_id", "version", name="uq_schema_versions_schema_version"),
    )
    op.create_index("ix_schema_versions_schema_id", "schema_versions", ["schema_id"])

    op.create_table(
        "schema_samples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("schema_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("expected", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("last_run", sa.JSON(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["schema_id"], ["document_schemas.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_schema_samples_schema_id", "schema_samples", ["schema_id"])
    op.create_index("ix_schema_samples_expires_at", "schema_samples", ["expires_at"])

    op.add_column("document_schemas", sa.Column("current_version", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("schema_version_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_documents_schema_version_id", "documents", "schema_versions",
                          ["schema_version_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_documents_schema_version_id", "documents", ["schema_version_id"])

    # Every existing schema starts at version 1 with its current fields.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, fields, created_by FROM document_schemas")).fetchall()
    for schema_id, fields, created_by in rows:
        fields = fields if fields is not None else []
        if isinstance(fields, str):
            fields = json.loads(fields)
        bind.execute(
            sa.text(
                "INSERT INTO schema_versions (id, schema_id, version, fields, fields_hash, note, created_by) "
                "VALUES (:id, :schema_id, 1, CAST(:fields AS JSON), :hash, 'Existing schema', :created_by)"
            ),
            {
                "id": uuid.uuid4(),
                "schema_id": schema_id,
                "fields": json.dumps(fields),
                "hash": hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest(),
                "created_by": created_by,
            },
        )
    bind.execute(sa.text("UPDATE document_schemas SET current_version = 1"))


def downgrade() -> None:
    op.drop_index("ix_documents_schema_version_id", table_name="documents")
    op.drop_constraint("fk_documents_schema_version_id", "documents", type_="foreignkey")
    op.drop_column("documents", "schema_version_id")
    op.drop_column("document_schemas", "current_version")
    op.drop_table("schema_samples")
    op.drop_table("schema_versions")
