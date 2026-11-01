"""Store the unfinished result of every tool call a finished run left without one.

Data only (idempotent; a second run changes nothing). Before this revision a
run that was stopped or died mid-call stored no result for that call, so the
chat showed it running forever. Runs still active (queued, running, or
cancelled while their worker is still finishing) are skipped: their worker
stores the results itself (app.agent.unfinished).

Downgrade keeps the rows: they are true, and the previous revision's code
reads them as an ordinary error result.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.agent.unfinished import close_unfinished_calls

revision = "0032_unfinished_call_results"
down_revision = "0031_agent_ui_actions"
branch_labels = None
depends_on = None

_runs = sa.table(
    "agent_runs",
    sa.column("id", sa.Uuid()), sa.column("status", sa.String()),
    sa.column("finished_at", sa.DateTime(timezone=True)),
)


def upgrade_data(bind) -> int:
    ended = bind.execute(sa.select(_runs.c.id).where(
        _runs.c.status.notin_(("queued", "running")),
        sa.or_(_runs.c.status != "cancelled", _runs.c.finished_at.isnot(None)),
    )).scalars().all()
    return close_unfinished_calls(bind, ended)


def upgrade():
    upgrade_data(op.get_bind())


def downgrade():
    pass
