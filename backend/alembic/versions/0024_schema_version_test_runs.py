"""Keep test-set results on each schema version (Schema Studio phase 3)."""
from alembic import op
import sqlalchemy as sa

revision = "0024_schema_version_test_runs"
down_revision = "0023_schema_versions_samples"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("schema_versions", sa.Column("test_runs", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("schema_versions", "test_runs")
