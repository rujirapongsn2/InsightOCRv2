"""Check image imports without running migrations, seeds, or external services."""
import importlib
from contextlib import ExitStack
from unittest.mock import patch

import psycopg2
import sqlalchemy
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.db.migrate import BACKEND_DIR
from app.db.session import engine


def main() -> None:
    if engine.dialect.driver != "psycopg2":
        raise RuntimeError("DATABASE_URL must use the psycopg2 driver")
    print(f"SQLAlchemy {sqlalchemy.__version__}; psycopg2 {psycopg2.__version__}; driver {engine.dialect.driver}")

    # Only startup side effects are disabled; route and task imports remain real.
    startup_hooks = (
        "app.db.migrate.run_startup_migrations",
        "app.initial_data.init_db",
        "app.initial_templates.init_system_templates",
        "app.initial_ai_settings.init_ai_settings",
        "app.initial_agent_skills.ensure_system_agent_skills",
        "app.initial_workflows.ensure_sample_workflows",
        "app.initial_integrations.migrate_softnix_integrations",
        "app.services.code_sandbox.ensure_sandbox_image",
    )
    with ExitStack() as stack:
        stack.enter_context(patch("threading.Thread.start"))
        stack.enter_context(patch("app.db.session.SessionLocal"))
        stack.enter_context(patch.object(engine, "connect", side_effect=RuntimeError("Smoke check must not connect to the database")))
        for hook in startup_hooks:
            stack.enter_context(patch(hook))
        importlib.import_module("app.main")
        from app.celery_app import celery_app
        for module in celery_app.conf.include:
            importlib.import_module(module)

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Expected one Alembic head, got {heads}")
    print(f"API, Celery tasks and Alembic imports passed; migration head {heads[0]}")


if __name__ == "__main__":
    main()
