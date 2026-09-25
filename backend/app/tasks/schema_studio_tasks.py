"""Background test runs for Schema Studio.

Running the real mapping engines on several samples can take minutes (one LLM
mapping of a two-page quotation took ~2 minutes), longer than the API proxy
allows, so runs happen here and report progress through Redis.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Optional

from app.celery_app import celery_app
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

RUN_TTL_SECONDS = 7200
SAMPLE_BUDGET_SECONDS = 240
MAX_PARALLEL_SAMPLES = 3


def run_key(user_id: Any, run_id: str) -> str:
    return f"schema_run:{user_id}:{run_id}"


def initial_state(total: int) -> dict[str, Any]:
    return {"status": "queued", "total": total, "done": 0, "samples": [], "error": None}


def _write(client: Any, key: str, state: dict[str, Any]) -> None:
    client.set(key, json.dumps(state, default=str), ex=RUN_TTL_SECONDS)


def _map_one(text: str, fields: list[dict[str, Any]], engine: Optional[str]) -> dict[str, Any]:
    from app.services.field_mapping import map_fields
    from app.services.schema_studio import dry_run_report

    db = SessionLocal()
    try:
        values, report = map_fields(text, SimpleNamespace(name="schema_test", fields=fields), db,
                                    engine=engine, budget_seconds=SAMPLE_BUDGET_SECONDS)
        return {"values": values, "report": dry_run_report(values, report)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.schema_studio_tasks.run_schema_samples_task",
                 soft_time_limit=900, time_limit=960)
def run_schema_samples_task(user_id: str, run_id: str, samples: list[dict[str, Any]],
                            fields: list[dict[str, Any]], engine: Optional[str] = None,
                            schema_id: Optional[str] = None, schema_version: Optional[int] = None) -> None:
    """Map every sample with the given fields and compare with confirmed values.

    ``samples`` items: {index, filename, text?, sample_id?, expected?}. Stored
    samples (``sample_id``) are read from the database and get ``last_run``
    updated so the schema page can show the latest result.
    """
    import redis
    from app.core.config import settings
    from app.models.schema import SchemaSample
    from app.services.schema_studio import compare_with_expected

    client = redis.from_url(settings.REDIS_URL)
    key = run_key(user_id, run_id)
    state: dict[str, Any] = {"status": "running", "total": len(samples), "done": 0, "samples": [], "error": None}
    field_names = {field.get("name") for field in fields}
    try:
        _write(client, key, state)
        stored: dict[str, Any] = {}
        if schema_id:
            with SessionLocal() as db:
                ids = [s["sample_id"] for s in samples if s.get("sample_id")]
                for row in db.query(SchemaSample).filter(SchemaSample.id.in_(ids),
                                                          SchemaSample.schema_id == schema_id).all():
                    stored[str(row.id)] = {"text": row.text, "expected": row.expected or {}}
        jobs = []
        for sample in samples:
            source = stored.get(str(sample.get("sample_id"))) if sample.get("sample_id") else None
            text = source["text"] if source else sample.get("text") or ""
            expected = source["expected"] if source else sample.get("expected") or {}
            jobs.append((sample, text, expected))

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SAMPLES) as pool:
            futures = {pool.submit(_map_one, text, fields, engine): (sample, expected)
                       for sample, text, expected in jobs}
            for future in as_completed(futures):
                sample, expected = futures[future]
                entry: dict[str, Any] = {"index": sample.get("index"), "filename": sample.get("filename"),
                                         "sample_id": sample.get("sample_id")}
                try:
                    result = future.result()
                    entry["report"] = result["report"]
                    if expected:
                        entry["comparison"] = compare_with_expected(expected, result["values"], field_names)
                except Exception as exc:  # noqa: BLE001 — one sample failing must not hide the others
                    logger.exception("Schema test run failed for sample %s", sample.get("index"))
                    entry["error"] = type(exc).__name__
                state["samples"].append(entry)
                state["done"] += 1
                _write(client, key, state)

        state["samples"].sort(key=lambda item: item.get("index") or 0)
        if schema_id:
            _save_last_runs(schema_id, state["samples"], schema_version)
        state["status"] = "completed"
        _write(client, key, state)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Schema test run %s failed", run_id)
        state["status"] = "failed"
        state["error"] = "The test run stopped unexpectedly. Try again."
        _write(client, key, state)
        raise exc
    finally:
        client.close()


def _save_last_runs(schema_id: str, results: list[dict[str, Any]], version: Optional[int]) -> None:
    """``version`` is the one whose fields were tested, fixed when the run started."""
    from app.models.schema import SchemaSample

    with SessionLocal() as db:
        now = datetime.now(timezone.utc).isoformat()
        for entry in results:
            if not entry.get("sample_id"):
                continue
            row = db.query(SchemaSample).filter(SchemaSample.id == entry["sample_id"]).first()
            if row is None:
                continue
            row.last_run = {
                "run_at": now,
                "schema_version": version,
                "error": entry.get("error"),
                "checked": (entry.get("comparison") or {}).get("checked", 0),
                "matched": (entry.get("comparison") or {}).get("matched", 0),
                "fields": (entry.get("comparison") or {}).get("fields", {}),
            }
        db.commit()


SUGGESTION_FAILED = "Schema suggestion request failed. Check the active AI provider and try again."


@celery_app.task(name="app.tasks.schema_studio_tasks.suggest_schema_task", soft_time_limit=600, time_limit=660)
def suggest_schema_task(user_id: str, run_id: str, session_id: str, document_type: Optional[str] = None,
                        extraction: Optional[list[dict[str, Any]]] = None) -> None:
    """Ask AI for fields and verify them against the cached sample texts."""
    import asyncio
    import redis
    from app.core.config import settings
    from app.services import schema_studio

    client = redis.from_url(settings.REDIS_URL)
    key = run_key(user_id, run_id)
    state: dict[str, Any] = {"status": "running", "kind": "suggestion", "total": 1, "done": 0,
                             "samples": [], "error": None, "result": None}
    try:
        _write(client, key, state)
        samples = schema_studio.load_samples(user_id, session_id)
        if not samples:
            raise ValueError("The uploaded samples have expired. Upload the files again.")
        with SessionLocal() as db:
            result = asyncio.run(schema_studio.suggest_fields(db, samples, document_type))
        result["raw_result"]["extraction"] = extraction or []
        state.update(status="completed", done=1, result=result)
    except ValueError as exc:
        state.update(status="failed", error=str(exc))
    except Exception:  # noqa: BLE001 — the user sees a short message; details go to the log
        logger.exception("Schema suggestion %s failed", run_id)
        state.update(status="failed", error=SUGGESTION_FAILED)
    finally:
        _write(client, key, state)
        client.close()
