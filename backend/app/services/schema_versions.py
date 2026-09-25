"""Immutable schema versions.

Processing always uses the schema's current fields; every mapped document
records which version that was, so results stay traceable after edits. A new
version is created whenever the fields' hash changes, whichever code path
changed them (editor, import, template), because mapping calls
``ensure_current_version`` before it records the version.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError

from app.models.schema import DocumentSchema, SchemaVersion

logger = logging.getLogger(__name__)


def fields_hash(fields: Any) -> str:
    return hashlib.sha256(json.dumps(fields or [], sort_keys=True).encode()).hexdigest()


def latest_version(db: Any, schema_id: Any) -> Optional[SchemaVersion]:
    return (
        db.query(SchemaVersion)
        .filter(SchemaVersion.schema_id == schema_id)
        .order_by(SchemaVersion.version.desc())
        .first()
    )


def ensure_current_version(db: Any, schema: DocumentSchema, user_id: Any = None,
                           note: Optional[str] = None) -> SchemaVersion:
    """Return the version matching the schema's fields, creating it if needed.

    Runs in a savepoint so a concurrent writer claiming the same version
    number only costs a retry, not the caller's transaction.
    """
    digest = fields_hash(schema.fields)
    for _attempt in range(3):
        latest = latest_version(db, schema.id)
        if latest is not None and latest.fields_hash == digest:
            if schema.current_version != latest.version:
                schema.current_version = latest.version
            return latest
        version = SchemaVersion(
            schema_id=schema.id,
            version=(latest.version if latest else 0) + 1,
            fields=schema.fields or [],
            fields_hash=digest,
            note=note,
            created_by=user_id,
        )
        try:
            with db.begin_nested():
                db.add(version)
                db.flush()
        except IntegrityError:
            logger.info("Schema %s version %s was created concurrently; retrying", schema.id, version.version)
            continue
        schema.current_version = version.version
        return version
    raise RuntimeError(f"Could not record a version for schema {schema.id}")


def record_document_version(db: Any, document: Any, schema: DocumentSchema) -> None:
    """Stamp the version whose fields this mapping actually used.

    ``schema`` may be the copy a long-running job loaded before someone edited
    the schema, so match by the hash of the fields used rather than assuming
    they are current, and never move ``current_version`` from a stale copy.
    Never blocks the mapping itself.
    """
    try:
        used_hash = fields_hash(schema.fields)
        match = (
            db.query(SchemaVersion)
            .filter(SchemaVersion.schema_id == schema.id, SchemaVersion.fields_hash == used_hash)
            .order_by(SchemaVersion.version.desc())
            .first()
        )
        if match is not None:
            document.schema_version_id = match.id
            return
        # Column query: reads the committed row, not the job's identity-map copy.
        current_fields = db.query(DocumentSchema.fields).filter(DocumentSchema.id == schema.id).scalar()
        if fields_hash(current_fields) == used_hash:
            document.schema_version_id = ensure_current_version(db, schema).id
        else:
            logger.warning("Schema %s changed while document %s was processed; version not recorded",
                           schema.id, getattr(document, "id", None))
    except Exception:  # noqa: BLE001 — traceability must not fail document processing
        logger.warning("Could not record schema version for document %s", getattr(document, "id", None),
                       exc_info=True)
