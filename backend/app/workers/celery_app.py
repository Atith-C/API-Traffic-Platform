"""Celery application.

Redis is used as both broker and result backend for simplicity in this stage. Tasks (usage
aggregation, telemetry outbox drain, notifications) are registered in sibling modules as milestones
land. Beat schedules the periodic rollups / outbox publisher.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "api_traffic",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],  # ensure tasks are registered in worker AND beat processes
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    # Periodic schedule (defined in config so beat picks it up deterministically).
    beat_schedule={
        "publish-telemetry": {"task": "telemetry.publish", "schedule": 10.0},
        "rollup-daily-usage": {"task": "analytics.rollup_daily", "schedule": 900.0},
    },
)
