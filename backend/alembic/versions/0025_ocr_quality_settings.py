"""Admin toggles for OCR quality routing and the Jev readability check."""
from alembic import op
import sqlalchemy as sa

revision = "0025_ocr_quality_settings"
down_revision = "0024_schema_version_test_runs"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text("ALTER TABLE settings ADD COLUMN IF NOT EXISTS ocr_quality_routing BOOLEAN"))
    op.get_bind().execute(sa.text("ALTER TABLE settings ADD COLUMN IF NOT EXISTS ocr_quality_jev BOOLEAN"))


def downgrade():
    op.drop_column("settings", "ocr_quality_jev")
    op.drop_column("settings", "ocr_quality_routing")
