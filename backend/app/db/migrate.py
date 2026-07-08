"""Run Alembic migrations once at startup, serialized across processes.

Replaces the import-time ``create_all`` + hand-written ALTER block that used
to live in ``app/main.py`` and raced across uvicorn workers. A Postgres
advisory lock guarantees only one process applies DDL; the others wait and
then find the schema already at head.
"""
import logging
from pathlib import Path

from sqlalchemy import text

from app.db.advisory_lock import advisory_lock
from app.db.session import engine

logger = logging.getLogger(__name__)

MIGRATION_LOCK_ID = 2026070501
BACKEND_DIR = Path(__file__).resolve().parents[2]


def _upgrade_to_head() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


def _extend_integration_type_enum() -> None:
    # ALTER TYPE ... ADD VALUE must run outside a transaction (AUTOCOMMIT),
    # so it cannot live inside an Alembic migration.
    with engine.connect() as conn:
        autocommit = conn.execution_options(isolation_level="AUTOCOMMIT")
        for label in ("GDRIVE", "ONEDRIVE"):
            try:
                autocommit.execute(text(
                    f"ALTER TYPE integrationtype ADD VALUE IF NOT EXISTS '{label}'"
                ))
            except Exception as exc:  # pragma: no cover — enum may not exist yet
                logger.warning("Skip enum migration for %s: %s", label, exc)


def run_startup_migrations() -> None:
    with advisory_lock(MIGRATION_LOCK_ID):
        _upgrade_to_head()
        _extend_integration_type_enum()
