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
    include=["app.tasks.document_tasks"]
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Bangkok",
    enable_utc=True,
    task_track_started=True,
    task_soft_time_limit=1800,  # 30 minutes — raises SoftTimeLimitExceeded (catchable)
    task_time_limit=2100,       # 35 minutes hard kill (SIGKILL) — last resort
    worker_prefetch_multiplier=1,  # Process one task at a time per worker
    task_acks_late=True,  # Acknowledge task after completion (more reliable)
)
