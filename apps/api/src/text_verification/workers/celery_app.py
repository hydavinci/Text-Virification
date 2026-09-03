import os
from urllib.parse import urlparse

from celery import Celery  # type: ignore[import-untyped]
from celery.signals import celeryd_init  # type: ignore[import-untyped]
from kombu import Queue  # type: ignore[import-untyped]

from text_verification.config import get_settings, validate_runtime_settings

LEGACY_PROCESSING_QUEUE = "celery"
ADVANCED_PROCESSING_QUEUE = "verification-v2"
MAINTENANCE_QUEUE = "maintenance-v2"
PROCESS_JOB_PUBLISH_RETRY_POLICY = {
    "max_retries": 3,
    "interval_start": 0,
    "interval_step": 0.2,
    "interval_max": 0.2,
}


def broker_transport_options_for(broker_url: str) -> dict[str, bool]:
    if urlparse(broker_url).scheme.lower() in {"amqp", "amqps", "pyamqp"}:
        return {"confirm_publish": True}
    return {}


settings = get_settings()
validate_runtime_settings(settings)
broker_url = settings.celery_broker_url or settings.redis_url

celery_app = Celery(
    "text_verification",
    broker=broker_url,
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
    broker_transport_options=broker_transport_options_for(broker_url),
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


def validate_celeryd_startup(
    sender: object,
    instance: object,
    conf: object,
    options: dict[str, object],
    **kwargs: object,
) -> None:
    del sender, instance, conf, kwargs
    from text_verification.workers.worker_cli import (
        WorkerStartupError,
        guard_celery_worker_startup,
    )

    try:
        guard_celery_worker_startup(os.environ, options)
    except WorkerStartupError as error:
        raise SystemExit(f"Unsafe Celery worker configuration: {error}") from error


celeryd_init.connect(validate_celeryd_startup)
