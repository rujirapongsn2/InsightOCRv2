"""Agent approvals used "approved"; the review page and every reader use "confirmed"."""
from alembic import op

revision = "0028_confirmed_review_decision"
down_revision = "0027_integration_sharing"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE documents SET review_decision = 'confirmed' WHERE review_decision = 'approved'")


def downgrade():
    pass  # the old value carried no extra meaning
