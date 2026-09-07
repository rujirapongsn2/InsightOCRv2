"""Configure field mapping independently from OCR."""
from alembic import op
import sqlalchemy as sa

revision = "0020_mapping_policy"
down_revision = "0019_agent_tools_status"
branch_labels = None
depends_on = None


def upgrade():
    for definition in (
        "mapping_engine VARCHAR NOT NULL DEFAULT 'auto'",
        "mapping_fallback_provider_id VARCHAR",
        "mapping_fallback_enabled BOOLEAN NOT NULL DEFAULT true",
    ):
        op.get_bind().execute(sa.text("ALTER TABLE settings ADD COLUMN IF NOT EXISTS " + definition))


def downgrade():
    raise NotImplementedError("Mapping policy migration is forward-only")
