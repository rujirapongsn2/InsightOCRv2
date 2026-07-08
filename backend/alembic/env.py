from logging.config import fileConfig

from alembic import context

from app.core.config import settings
from app.db.base_class import Base

# Import every model module so Base.metadata is fully populated for
# autogenerate and for the baseline migration's create_all.
from app.models import (  # noqa: F401
    activity_log,
    agent_conversation,
    agent_memory,
    agent_message,
    agent_pending_action,
    agent_skill,
    ai_settings,
    api_access_token,
    chat,
    document,
    integration,
    integration_result,
    job,
    schema,
    setting,
    template,
    user,
    workflow,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Reuse the application's engine so pooling/config stay in one place.
    from app.db.session import engine

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
