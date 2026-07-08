"""Restore DB-level defaults on integration timestamp columns.

The Integration / IntegrationResult models were switched from a Python-side
``default=datetime.utcnow`` to ``server_default=func.now()``. On a freshly
created table that emits ``DEFAULT now()``, but pre-existing tables kept their
old (default-less) columns — so inserts sent NULL into these NOT NULL columns
and failed (e.g. "Failed to create integration"). This sets the DB default on
existing tables. Idempotent.
"""
from alembic import op
import sqlalchemy as sa

# NOTE: keep revision ids ≤32 chars — alembic_version.version_num is varchar(32).
revision = "0004_integ_ts_defaults"
down_revision = "0003_workflow_builder_provider"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE IF EXISTS integrations ALTER COLUMN created_at SET DEFAULT now()",
    "ALTER TABLE IF EXISTS integrations ALTER COLUMN updated_at SET DEFAULT now()",
    "ALTER TABLE IF EXISTS integration_results ALTER COLUMN created_at SET DEFAULT now()",
]


def upgrade() -> None:
    bind = op.get_bind()
    for stmt in STATEMENTS:
        bind.execute(sa.text(stmt))


def downgrade() -> None:
    raise NotImplementedError("0004 is forward-only")
