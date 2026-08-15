from celery import Celery  # type: ignore[import-untyped]

from text_verification.config import get_settings

settings = get_settings()

celery_app = Celery(
    "text_verification",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["text_verification.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=900,
    task_soft_time_limit=840,
    timezone="UTC",
    beat_schedule={
        "cleanup-expired-jobs-hourly": {
            "task": "text_verification.cleanup_expired_jobs",
            "schedule": 3600.0,
        }
    },
)
