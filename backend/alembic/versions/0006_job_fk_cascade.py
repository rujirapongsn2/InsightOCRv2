"""Ensure job-owned rows cascade when a job is deleted.

Deleting a job must remove its associated rows instead of asking SQLAlchemy to
null out non-null job_id columns such as integration_results.job_id.
"""
from alembic import op
import sqlalchemy as sa

# NOTE: keep revision ids <=32 chars; alembic_version.version_num is varchar(32).
revision = "0006_job_fk_cascade"
down_revision = "0005_doc_source_file_id"
branch_labels = None
depends_on = None


JOB_FKS = (
    ("documents", "documents_job_id_fkey", False),
    ("integration_results", "integration_results_job_id_fkey", False),
    ("chat_conversations", "chat_conversations_job_id_fkey", False),
    ("agent_conversations", "agent_conversations_job_id_fkey", True),
    ("agent_memories", "agent_memories_job_id_fkey", True),
)


def _column_is_nullable(bind, table_name: str) -> bool:
    return bool(bind.execute(
        sa.text(
            """
            SELECT is_nullable = 'YES'
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = 'job_id'
            """
        ),
        {"table_name": table_name},
    ).scalar())


def upgrade() -> None:
    bind = op.get_bind()
    for table_name, constraint_name, model_allows_null in JOB_FKS:
        nullable = model_allows_null or _column_is_nullable(bind, table_name)
        null_action = "DROP NOT NULL" if nullable else "SET NOT NULL"
        bind.execute(sa.text(
            f"ALTER TABLE IF EXISTS {table_name} "
            f"DROP CONSTRAINT IF EXISTS {constraint_name}"
        ))
        bind.execute(sa.text(
            f"ALTER TABLE IF EXISTS {table_name} "
            f"ADD CONSTRAINT {constraint_name} "
            f"FOREIGN KEY (job_id) REFERENCES jobs(id) "
            f"ON DELETE CASCADE"
        ))
        bind.execute(sa.text(
            f"ALTER TABLE IF EXISTS {table_name} "
            f"ALTER COLUMN job_id {null_action}"
        ))


def downgrade() -> None:
    raise NotImplementedError("0006 is forward-only")
