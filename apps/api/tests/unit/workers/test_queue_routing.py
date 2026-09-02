import tomllib
from pathlib import Path

from text_verification.workers.celery_app import (
    ADVANCED_PROCESSING_QUEUE,
    LEGACY_PROCESSING_QUEUE,
    MAINTENANCE_QUEUE,
    PROCESS_JOB_PUBLISH_RETRY_POLICY,
    broker_transport_options_for,
    celery_app,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[5]


def test_celery_routes_new_jobs_and_maintenance_to_versioned_queues() -> None:
    assert LEGACY_PROCESSING_QUEUE == "celery"
    assert ADVANCED_PROCESSING_QUEUE == "verification-v2"
    assert MAINTENANCE_QUEUE == "maintenance-v2"
    assert {queue.name for queue in celery_app.conf.task_queues} == {
        LEGACY_PROCESSING_QUEUE,
        ADVANCED_PROCESSING_QUEUE,
        MAINTENANCE_QUEUE,
    }
    assert celery_app.conf.task_default_queue == LEGACY_PROCESSING_QUEUE
    assert celery_app.conf.task_create_missing_queues is False
    assert celery_app.conf.task_routes == {
        "text_verification.process_job": {"queue": ADVANCED_PROCESSING_QUEUE},
        "text_verification.cleanup_expired_jobs": {"queue": MAINTENANCE_QUEUE},
        "text_verification.rescue_expired_job_leases": {
            "queue": MAINTENANCE_QUEUE
        },
    }
    assert celery_app.conf.task_publish_retry is True
    assert celery_app.conf.task_publish_retry_policy == PROCESS_JOB_PUBLISH_RETRY_POLICY
    assert "confirm_publish" not in celery_app.conf.broker_transport_options


def test_publisher_confirm_option_is_transport_aware() -> None:
    assert broker_transport_options_for("redis://redis:6379/0") == {}
    assert broker_transport_options_for("rediss://redis:6379/0") == {}
    assert broker_transport_options_for("amqp://guest:guest@rabbitmq//") == {
        "confirm_publish": True
    }
    assert broker_transport_options_for("amqps://guest:guest@rabbitmq//") == {
        "confirm_publish": True
    }
    assert broker_transport_options_for("pyamqp://guest:guest@rabbitmq//") == {
        "confirm_publish": True
    }
    assert broker_transport_options_for("pyamqps://guest:guest@rabbitmq//") == {}


def test_periodic_tasks_have_one_non_processing_queue_owner() -> None:
    schedule = celery_app.conf.beat_schedule

    assert schedule["cleanup-expired-jobs-hourly"]["options"] == {
        "queue": MAINTENANCE_QUEUE
    }
    assert schedule["rescue-expired-job-leases"]["options"] == {
        "queue": MAINTENANCE_QUEUE
    }


def test_compose_new_worker_drains_legacy_and_v2_with_separate_maintenance() -> None:
    compose = (REPOSITORY_ROOT / "infra" / "compose.yaml").read_text(encoding="utf-8")

    assert compose.count('"text-verification-worker"') == 2
    assert "TEXT_VERIFICATION_WORKER_ROLE: verification" in compose
    assert "TEXT_VERIFICATION_WORKER_QUEUES: celery,verification-v2" in compose
    assert 'TEXT_VERIFICATION_WORKER_CONCURRENCY: "2"' in compose
    assert compose.count("maintenance-worker:") == 1
    assert "TEXT_VERIFICATION_WORKER_ROLE: maintenance" in compose
    assert "TEXT_VERIFICATION_WORKER_QUEUES: maintenance-v2" in compose
    assert 'TEXT_VERIFICATION_WORKER_CONCURRENCY: "1"' in compose


def test_rollout_documentation_keeps_pre_fix_worker_off_v2_queue() -> None:
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")
    legacy_command = next(
        line for line in readme.splitlines() if "旧版 Worker 命令" in line
    )

    assert "--queues=celery" in legacy_command
    assert ADVANCED_PROCESSING_QUEUE not in legacy_command
    assert "text-verification-worker" in readme
    assert "TEXT_VERIFICATION_WORKER_ROLE=verification" in readme
    assert "TEXT_VERIFICATION_WORKER_ROLE=maintenance" in readme


def test_worker_console_entrypoint_is_packaged() -> None:
    config = tomllib.loads(
        (REPOSITORY_ROOT / "apps" / "api" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert config["project"]["scripts"]["text-verification-worker"] == (
        "text_verification.workers.worker_cli:main"
    )
