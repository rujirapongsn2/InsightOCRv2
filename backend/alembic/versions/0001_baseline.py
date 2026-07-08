"""Baseline: bring any database (fresh or legacy) to the current model state.

This project historically ran ``Base.metadata.create_all`` plus hand-written
``ALTER TABLE ... IF NOT EXISTS`` statements at import time in ``app/main.py``.
This migration replaces that block:

1. ``create_all(checkfirst=True)`` creates any missing tables (fresh DBs get
   everything, including the new indexes declared on the models).
2. The legacy idempotent ALTERs bring pre-existing databases up to date.
3. ``CREATE INDEX IF NOT EXISTS`` adds the hot-path indexes to databases whose
   tables already existed before the indexes were declared on the models.
4. Key foreign keys are rebuilt with explicit ON DELETE behaviour so deletes
   that bypass the ORM cannot orphan rows.

Every statement is idempotent, so re-running against any state is safe.
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


LEGACY_ALTERS = [
    "ALTER TABLE IF EXISTS document_schemas ADD COLUMN IF NOT EXISTS created_by uuid NULL",
    "ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS api_endpoint varchar",
    "ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS api_token varchar",
    "ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS verify_ssl boolean DEFAULT false",
    "ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS ocr_endpoint varchar",
    "ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS structured_output_endpoint varchar",
    "ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS schema_suggestion_endpoint varchar",
    "ALTER TABLE IF EXISTS settings ADD COLUMN IF NOT EXISTS test_endpoint varchar",
    "ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS schema_id uuid NULL",
    "ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS task_id varchar NULL",
    "ALTER TABLE IF EXISTS document_schemas ADD COLUMN IF NOT EXISTS template_id uuid NULL",
    "ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS page_count integer NULL",
    "ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS ocr_pages jsonb NULL",
    "ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS processing_error varchar NULL",
    "ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS review_decision varchar NULL",
    "ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS reviewed_at timestamptz NULL",
    "ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS reviewed_by uuid NULL",
    "ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS processing_started_at timestamptz NULL",
    "ALTER TABLE IF EXISTS jobs ADD COLUMN IF NOT EXISTS user_id uuid NULL",
    "ALTER TABLE IF EXISTS integration_results ADD COLUMN IF NOT EXISTS integration_type varchar(20) NULL",
    "ALTER TABLE IF EXISTS integration_results ADD COLUMN IF NOT EXISTS integration_name varchar(255) NULL",
    "ALTER TABLE IF EXISTS workflows ADD COLUMN IF NOT EXISTS webhook_enabled boolean DEFAULT false",
    "ALTER TABLE IF EXISTS workflows ADD COLUMN IF NOT EXISTS webhook_secret_hash text NULL",
    "ALTER TABLE IF EXISTS workflows ADD COLUMN IF NOT EXISTS webhook_secret_created_at timestamptz NULL",
    "ALTER TABLE IF EXISTS workflows ADD COLUMN IF NOT EXISTS webhook_last_triggered_at timestamptz NULL",
    "ALTER TABLE IF EXISTS workflow_runs ADD COLUMN IF NOT EXISTS result jsonb NULL",
    "ALTER TABLE IF EXISTS workflow_runs ADD COLUMN IF NOT EXISTS result_node_id varchar(100) NULL",
    "ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS scope varchar(20) DEFAULT 'user'",
    "ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS license varchar(100)",
    "ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS compatibility varchar(500)",
    "ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS metadata jsonb",
    "ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS allowed_tools text",
    "ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS source varchar(20) DEFAULT 'db'",
    "ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS file_path varchar(500)",
    "ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS version varchar(20)",
    "ALTER TABLE IF EXISTS agent_skills ADD COLUMN IF NOT EXISTS user_id uuid NULL",
    "ALTER TABLE IF EXISTS agent_skills ALTER COLUMN name TYPE varchar(64)",
    "ALTER TABLE IF EXISTS ai_settings ADD COLUMN IF NOT EXISTS model varchar DEFAULT 'gpt-4o-mini'",
    "ALTER TABLE IF EXISTS ai_settings ADD COLUMN IF NOT EXISTS is_agent_provider boolean DEFAULT false",
    "ALTER TABLE IF EXISTS ai_settings ADD COLUMN IF NOT EXISTS provider_type varchar DEFAULT 'completion_messages'",
    """
    UPDATE settings
    SET ocr_endpoint = api_endpoint
    WHERE ocr_endpoint IS NULL
      AND api_endpoint IS NOT NULL
      AND api_endpoint != ''
    """,
]

# Hot-path indexes (names match SQLAlchemy's ix_<table>_<column> convention so
# fresh create_all and this migration converge on identical schemas).
INDEXES = [
    ("ix_documents_job_id", "documents", "job_id"),
    ("ix_documents_status", "documents", "status"),
    ("ix_documents_schema_id", "documents", "schema_id"),
    ("ix_jobs_status", "jobs", "status"),
    ("ix_jobs_user_id", "jobs", "user_id"),
    ("ix_jobs_created_at", "jobs", "created_at"),
    ("ix_workflows_next_run_at", "workflows", "next_run_at"),
    ("ix_workflows_user_id", "workflows", "user_id"),
    ("ix_workflow_runs_status", "workflow_runs", "status"),
    ("ix_workflow_runs_created_at", "workflow_runs", "created_at"),
    ("ix_integrations_user_id", "integrations", "user_id"),
    ("ix_integration_results_integration_id", "integration_results", "integration_id"),
    ("ix_integration_results_user_id", "integration_results", "user_id"),
    ("ix_integration_results_created_at", "integration_results", "created_at"),
    ("ix_agent_pending_actions_conversation_id", "agent_pending_actions", "conversation_id"),
    ("ix_agent_pending_actions_user_id", "agent_pending_actions", "user_id"),
    ("ix_agent_pending_actions_status", "agent_pending_actions", "status"),
]

# (table, column, referenced_table, on_delete) — constraints rebuilt with
# explicit ON DELETE so non-ORM deletes cannot orphan child rows.
FK_ON_DELETE = [
    ("documents", "job_id", "jobs", "CASCADE"),
    ("workflow_runs", "workflow_id", "workflows", "CASCADE"),
    ("workflow_node_runs", "run_id", "workflow_runs", "CASCADE"),
    ("jobs", "user_id", "users", "SET NULL"),
]

FK_REBUILD_SQL = """
DO $$
DECLARE
    conname text;
BEGIN
    SELECT tc.constraint_name INTO conname
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
     AND tc.table_schema = kcu.table_schema
    WHERE tc.table_name = '{table}'
      AND tc.constraint_type = 'FOREIGN KEY'
      AND kcu.column_name = '{column}'
    LIMIT 1;
    IF conname IS NOT NULL THEN
        EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', conname);
    END IF;
    ALTER TABLE {table}
        ADD CONSTRAINT {table}_{column}_fkey
        FOREIGN KEY ({column}) REFERENCES {ref_table}(id) ON DELETE {on_delete};
END $$;
"""


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create any missing tables from the current models.
    from app.db.base_class import Base
    Base.metadata.create_all(bind=bind, checkfirst=True)

    # 2. Legacy column additions for pre-existing databases.
    for stmt in LEGACY_ALTERS:
        bind.execute(sa.text(stmt))

    # 3. Hot-path indexes (no-ops where create_all already made them).
    for name, table, column in INDEXES:
        bind.execute(sa.text(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"
        ))

    # 4. Rebuild key FKs with explicit ON DELETE behaviour.
    for table, column, ref_table, on_delete in FK_ON_DELETE:
        bind.execute(sa.text(FK_REBUILD_SQL.format(
            table=table, column=column, ref_table=ref_table, on_delete=on_delete
        )))

    # 5. integrations timestamps: naive → timezone-aware (UTC).
    for col in ("created_at", "updated_at"):
        bind.execute(sa.text(f"""
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'integrations'
                      AND column_name = '{col}'
                      AND data_type = 'timestamp without time zone'
                ) THEN
                    ALTER TABLE integrations
                        ALTER COLUMN {col} TYPE timestamptz
                        USING {col} AT TIME ZONE 'UTC';
                END IF;
            END $$;
        """))


def downgrade() -> None:
    raise NotImplementedError("Baseline migration cannot be downgraded")
