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
import uuid
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


MAX_TEST_RUNS = 10


def summarize_test_run(results: list[dict[str, Any]], *, engine: str, trigger: str, run_at: str) -> dict[str, Any]:
    """Aggregate one test-set run (``run_schema_samples_task`` entries) per field."""
    fields: dict[str, dict[str, int]] = {}
    checked = matched = errors = 0
    for entry in results:
        if entry.get("error"):
            errors += 1
            continue
        comparison = entry.get("comparison") or {}
        checked += comparison.get("checked", 0)
        matched += comparison.get("matched", 0)
        for name, detail in (comparison.get("fields") or {}).items():
            stats = fields.setdefault(name, {"checked": 0, "matched": 0})
            stats["checked"] += 1
            stats["matched"] += int(bool(detail.get("match")))
    return {"run_at": run_at, "engine": engine, "trigger": trigger, "samples": len(results),
            "errors": errors, "checked": checked, "matched": matched, "fields": fields}


def append_test_run(db: Any, schema_id: Any, version: int, summary: dict[str, Any]) -> None:
    """Keep the latest runs on the tested version (row-locked so parallel runs don't overwrite)."""
    schema_uuid = schema_id if isinstance(schema_id, uuid.UUID) else uuid.UUID(str(schema_id))
    row = (db.query(SchemaVersion)
           .filter(SchemaVersion.schema_id == schema_uuid, SchemaVersion.version == version)
           .with_for_update().first())
    if row is None:
        return
    row.test_runs = (list(row.test_runs or []) + [summary])[-MAX_TEST_RUNS:]


def compare_test_runs(previous: Optional[dict[str, Any]], current: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Fields whose match rate went up or down between two runs, for fields tested in both."""
    if not previous or not current:
        return None
    improved, regressed = [], []
    for name, now in (current.get("fields") or {}).items():
        before = (previous.get("fields") or {}).get(name)
        if not before or not before.get("checked") or not now.get("checked"):
            continue
        delta = now["matched"] / now["checked"] - before["matched"] / before["checked"]
        if delta > 1e-9:
            improved.append(name)
        elif delta < -1e-9:
            regressed.append(name)
    return {"previous_run_at": previous.get("run_at"), "previous_engine": previous.get("engine"),
            "previous_matched": previous.get("matched"), "previous_checked": previous.get("checked"),
            "improved": sorted(improved), "regressed": sorted(regressed)}


def version_test_history(versions: list[SchemaVersion]) -> dict[int, dict[str, Any]]:
    """Latest run per version and its comparison with the run just before it (any version)."""
    runs = sorted(((run.get("run_at") or "", row.version, run) for row in versions for run in (row.test_runs or [])),
                  key=lambda item: (item[0], item[1]))
    history: dict[int, dict[str, Any]] = {}
    for position, (_run_at, version, run) in enumerate(runs):
        previous = runs[position - 1] if position else None
        history[version] = {
            "latest": run,
            "runs": sum(1 for _at, other, _run in runs if other == version),
            "compared_with_version": previous[1] if previous else None,
            "comparison": compare_test_runs(previous[2] if previous else None, run),
        }
    return history
