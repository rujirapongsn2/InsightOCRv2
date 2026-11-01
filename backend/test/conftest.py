"""Shared fixtures.

postgres_engine is a throwaway Postgres database with every model's table,
foreign key and index (Base.metadata.create_all), for behavior SQLite does not
have: foreign keys checked per statement, row locks, conditional updates
racing. (alembic upgrade head cannot build an empty database: the baseline
migration creates today's tables, so 0010 then adds a column that exists.)

Where it comes from: TEST_POSTGRES_URL, else DATABASE_URL when it names a
Postgres server (inside the backend image it is the compose ``db`` service).
The fixture connects to that server's ``postgres`` maintenance database,
creates ``insightocr_test_<random>``, and drops it when the session ends. It
never writes to the database the URL names, so the app's data is untouched.

When no Postgres server is reachable the tests that use it are skipped, so a
laptop without Docker still runs the rest. Set REQUIRE_POSTGRES=1 to turn
that skip into a failure; the documented backend test command does, so those
tests cannot silently stop running.
"""
import importlib
import os
import pkgutil
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

TEST_DATABASE_PREFIX = "insightocr_test_"


def _unavailable(reason: str):
    if os.environ.get("REQUIRE_POSTGRES") == "1":
        pytest.fail(f"REQUIRE_POSTGRES=1 but {reason}")
    pytest.skip(reason)


@pytest.fixture(scope="session")
def postgres_url():
    raw = os.environ.get("TEST_POSTGRES_URL") or os.environ.get("DATABASE_URL") or ""
    if not raw.startswith("postgresql"):
        _unavailable("no Postgres server: set TEST_POSTGRES_URL (or a postgresql DATABASE_URL)")
    server = make_url(raw)
    name = f"{TEST_DATABASE_PREFIX}{uuid.uuid4().hex[:12]}"
    admin = create_engine(server.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    except OperationalError as error:
        admin.dispose()
        _unavailable(f"Postgres is unreachable: {error.orig}")
    try:
        yield server.set(database=name)
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def _postgres_session_engine(postgres_url):
    import app.models
    from app.db.base_class import Base

    for module in pkgutil.iter_modules(app.models.__path__):
        importlib.import_module(f"app.models.{module.name}")
    engine = create_engine(postgres_url)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def postgres_engine(_postgres_session_engine):
    """The test database, emptied after each test."""
    engine = _postgres_session_engine
    yield engine
    with engine.begin() as connection:
        tables = connection.execute(text(
            "SELECT quote_ident(tablename) FROM pg_tables "
            "WHERE schemaname = 'public'")).scalars().all()
        connection.execute(text(f"TRUNCATE {', '.join(tables)} CASCADE"))
