from celery import Celery  # type: ignore[import-untyped]

from text_verification.config import get_settings

TASK_HARD_TIME_LIMIT_SECONDS = 900
TASK_SOFT_TIME_LIMIT_SECONDS = 840

settings = get_settings()

celery_app = Celery(
    "text_verification",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "text_verification.workers.tasks",
        "text_verification.workers.export_tasks",
        "text_verification.workers.reanalysis_tasks",
    ],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=TASK_HARD_TIME_LIMIT_SECONDS,
    task_soft_time_limit=TASK_SOFT_TIME_LIMIT_SECONDS,
    timezone="UTC",
    beat_schedule={
        "cleanup-expired-jobs-hourly": {
            "task": "text_verification.cleanup_expired_jobs",
            "schedule": 3600.0,
        },
        "recover-stale-queued-exports-every-minute": {
            "task": "text_verification.recover_stale_queued_exports",
            "schedule": 60.0,
        },
    },
)
