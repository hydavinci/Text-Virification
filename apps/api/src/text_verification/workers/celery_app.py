from celery import Celery  # type: ignore[import-untyped]
from kombu import Queue  # type: ignore[import-untyped]

from text_verification.config import get_settings

LEGACY_PROCESSING_QUEUE = "celery"
ADVANCED_PROCESSING_QUEUE = "verification-v2"
MAINTENANCE_QUEUE = "maintenance-v2"
PROCESS_JOB_PUBLISH_RETRY_POLICY = {
    "max_retries": 3,
    "interval_start": 0,
    "interval_step": 0.2,
    "interval_max": 0.2,
}

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
    task_default_queue=LEGACY_PROCESSING_QUEUE,
    task_create_missing_queues=False,
    task_queues=(
        Queue(LEGACY_PROCESSING_QUEUE),
        Queue(ADVANCED_PROCESSING_QUEUE),
        Queue(MAINTENANCE_QUEUE),
    ),
    task_routes={
        "text_verification.process_job": {"queue": ADVANCED_PROCESSING_QUEUE},
        "text_verification.cleanup_expired_jobs": {"queue": MAINTENANCE_QUEUE},
        "text_verification.rescue_expired_job_leases": {
            "queue": MAINTENANCE_QUEUE,
        },
    },
    task_publish_retry=True,
    task_publish_retry_policy=PROCESS_JOB_PUBLISH_RETRY_POLICY,
    broker_transport_options={"confirm_publish": True},
    worker_prefetch_multiplier=1,
    task_time_limit=900,
    task_soft_time_limit=840,
    timezone="UTC",
    beat_schedule={
        "cleanup-expired-jobs-hourly": {
            "task": "text_verification.cleanup_expired_jobs",
            "schedule": 3600.0,
            "options": {"queue": MAINTENANCE_QUEUE},
        },
        "rescue-expired-job-leases": {
            "task": "text_verification.rescue_expired_job_leases",
            "schedule": 60.0,
            "options": {"queue": MAINTENANCE_QUEUE},
        },
    },
)
