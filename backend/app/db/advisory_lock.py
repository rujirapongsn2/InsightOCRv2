"""Session-scoped Postgres advisory locks on a dedicated, unpooled connection.

Startup coordination (migrations, one-time seeding) needs a lock that spans
several commits, so a transaction-scoped `pg_advisory_xact_lock` won't do —
it releases at the first commit. The session-scoped `pg_advisory_lock` /
`pg_advisory_unlock` pair is the right tool, but only if the connection
holding it is guaranteed to close (not sit idle in a pool) if anything
prevents the explicit unlock from running. Postgres releases a session-level
advisory lock the instant its owning backend connection closes — but only if
that connection actually closes, which a pooled connection never reliably
does (`session.close()`/`Connection.close()` on `app.db.session.engine`
returns it to the pool for reuse instead).

Multi-worker startup (uvicorn `--workers N`, which also does at least one
extra app-import in its master process to resolve the ASGI callable) has
been observed leaving such a lock held indefinitely on an idle pooled
connection, wedging every other worker in `pg_advisory_lock()` forever. Using
a `NullPool` engine here means `.close()` always closes the real socket, so
even an abnormal process lifecycle can't leak the lock past process exit.
"""
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.core.config import settings

_lock_engine = create_engine(settings.DATABASE_URL, poolclass=NullPool)


@contextmanager
def advisory_lock(lock_id: int):
    conn = _lock_engine.connect()
    try:
        conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": lock_id})
        conn.commit()
        yield
    finally:
        try:
            conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": lock_id})
            conn.commit()
        except Exception:
            pass  # connection close() below releases the lock regardless
        conn.close()
