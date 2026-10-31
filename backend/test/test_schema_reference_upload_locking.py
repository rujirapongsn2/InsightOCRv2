"""Optional PostgreSQL smoke check, isolated from application tables and objects."""
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateSchema, DropSchema

from app.db.session import engine
from app.models.schema import SchemaReferenceUpload


@pytest.mark.skipif(os.getenv("RUN_POSTGRES_LOCK_TEST") != "1", reason="Opt-in PostgreSQL lock check")
def test_active_upload_is_skipped_until_its_transaction_ends():
    namespace = f"test_reference_upload_{uuid4().hex}"
    isolated = engine.execution_options(schema_translate_map={None: namespace})
    with engine.begin() as connection:
        connection.execute(CreateSchema(namespace))
    try:
        with isolated.begin() as connection:
            SchemaReferenceUpload.__table__.create(connection)
        with Session(isolated) as upload, Session(isolated) as cleanup:
            path = "isolated-expired-upload.pdf"
            upload.add(SchemaReferenceUpload(storage_path=path, schema_id=uuid4(),
                expires_at=datetime.now(timezone.utc) - timedelta(hours=1)))
            upload.commit()
            assert upload.query(SchemaReferenceUpload).with_for_update().first() is not None
            expired = cleanup.query(SchemaReferenceUpload).filter(
                SchemaReferenceUpload.expires_at <= datetime.now(timezone.utc)
            )
            assert expired.with_for_update(skip_locked=True).all() == []
            upload.rollback()
            assert [row.storage_path for row in expired.with_for_update(skip_locked=True).all()] == [path]
            cleanup.rollback()
    finally:
        # Only the uniquely named test namespace is removed, never public tables.
        with engine.begin() as connection:
            connection.execute(DropSchema(namespace, cascade=True))
