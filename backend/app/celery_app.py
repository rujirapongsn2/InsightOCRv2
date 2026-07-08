"""
Celery application configuration for background task processing.
Uses Redis as message broker and result backend.
"""
from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "softnix_ocr",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.document_tasks",
        "app.tasks.workflow_tasks",
        "app.tasks.maintenance_tasks",
    ]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Bangkok",
    enable_utc=True,
    task_track_started=True,
    # Task return values are never read via AsyncResult.get() — the UI reads
    # progress/status from the `doc_progress:*` Redis keys and the DB, not the
    # result backend. Storing every task's return payload (which includes full
    # extracted_data) just grows Redis until it hits maxmemory and the broker
    # stalls. Drop return values and expire any state Celery still writes.
    task_ignore_result=True,
    result_expires=3600,  # 1 hour — safety net for anything that does persist
    task_soft_time_limit=1800,  # 30 minutes — raises SoftTimeLimitExceeded (catchable)
    task_time_limit=2100,       # 35 minutes hard kill (SIGKILL) — last resort
    worker_prefetch_multiplier=1,  # Process one task at a time per worker
    task_acks_late=True,  # Acknowledge task after completion (more reliable)
    # Must exceed task_time_limit: with acks_late, Redis redelivers any task
    # not acked within this window, which would re-run a task that is still
    # executing. Redelivery after a genuine worker death is then gated by the
    # atomic status claims in the tasks themselves.
    broker_transport_options={"visibility_timeout": 2400},
    # Separate queues so long OCR tasks cannot starve short workflow runs.
    # The default worker consumes both (-Q documents,workflows,celery); extra
    # workers can be scaled per queue.
    task_routes={
        "app.tasks.document_tasks.*": {"queue": "documents"},
        "app.tasks.workflow_tasks.*": {"queue": "workflows"},
        "app.tasks.maintenance_tasks.*": {"queue": "workflows"},
    },
    beat_schedule={
        "dispatch-scheduled-workflows": {
            "task": "app.tasks.workflow_tasks.dispatch_scheduled_workflows",
            "schedule": 30.0,  # seconds — checks cron-due workflows
        },
        "reconcile-stale-states": {
            "task": "app.tasks.maintenance_tasks.reconcile_stale_states",
            "schedule": 300.0,  # every 5 minutes
        },
        "prune-old-data": {
            "task": "app.tasks.maintenance_tasks.prune_old_data",
            "schedule": 24 * 3600.0,  # daily
        },
    },
)
