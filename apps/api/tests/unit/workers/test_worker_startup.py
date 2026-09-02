from __future__ import annotations

import os
from collections.abc import Mapping

import pytest
from celery.signals import celeryd_init

from text_verification.workers.celery_app import celery_app
from text_verification.workers.worker_cli import (
    CONCURRENCY_ENV,
    QUEUES_ENV,
    ROLE_ENV,
    WorkerRole,
    WorkerStartupError,
    build_worker_argv,
    guard_celery_worker_startup,
    main,
    resolve_worker_spec,
)


def _environment(
    role: WorkerRole,
    *,
    queues: str,
    concurrency: str,
) -> dict[str, str]:
    return {
        ROLE_ENV: role.value,
        QUEUES_ENV: queues,
        CONCURRENCY_ENV: concurrency,
    }


def test_verification_role_consumes_exactly_legacy_and_v2_queues() -> None:
    environment = _environment(
        WorkerRole.VERIFICATION,
        queues="celery,verification-v2",
        concurrency="2",
    )

    spec = resolve_worker_spec(environment)
    argv = build_worker_argv(environment)

    assert spec.queues == ("celery", "verification-v2")
    assert spec.concurrency == 2
    assert "maintenance-v2" not in spec.queues
    assert "--queues=celery,verification-v2" in argv
    assert "--concurrency=2" in argv
    assert "--prefetch-multiplier=1" in argv
    assert not any(argument.startswith("--autoscale") for argument in argv)


def test_maintenance_role_is_single_concurrency_and_queue_isolated() -> None:
    environment = _environment(
        WorkerRole.MAINTENANCE,
        queues="maintenance-v2",
        concurrency="1",
    )

    spec = resolve_worker_spec(environment)
    argv = build_worker_argv(environment)

    assert spec.queues == ("maintenance-v2",)
    assert spec.concurrency == 1
    assert "--queues=maintenance-v2" in argv
    assert "--concurrency=1" in argv
    assert "--prefetch-multiplier=1" in argv


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {ROLE_ENV: "unknown", QUEUES_ENV: "celery", CONCURRENCY_ENV: "1"},
        {ROLE_ENV: "verification", CONCURRENCY_ENV: "2"},
        {ROLE_ENV: "verification", QUEUES_ENV: "celery,verification-v2"},
    ],
)
def test_missing_or_unknown_worker_configuration_fails_closed(
    environment: Mapping[str, str],
) -> None:
    with pytest.raises(WorkerStartupError):
        resolve_worker_spec(environment)


@pytest.mark.parametrize(
    "environment",
    [
        _environment(
            WorkerRole.VERIFICATION,
            queues="verification-v2",
            concurrency="2",
        ),
        _environment(
            WorkerRole.VERIFICATION,
            queues="celery,verification-v2,maintenance-v2",
            concurrency="2",
        ),
        _environment(
            WorkerRole.MAINTENANCE,
            queues="maintenance-v2",
            concurrency="2",
        ),
        _environment(
            WorkerRole.MAINTENANCE,
            queues="maintenance-v2",
            concurrency="0",
        ),
    ],
)
def test_wrong_queue_or_concurrency_environment_override_fails_closed(
    environment: Mapping[str, str],
) -> None:
    with pytest.raises(WorkerStartupError):
        resolve_worker_spec(environment)


def test_direct_celery_worker_guard_validates_final_options() -> None:
    environment = _environment(
        WorkerRole.VERIFICATION,
        queues="celery,verification-v2",
        concurrency="2",
    )

    guard_celery_worker_startup(
        environment,
        {
            "queues": "celery,verification-v2",
            "concurrency": 2,
            "prefetch_multiplier": 1,
            "autoscale": None,
        },
    )

    with pytest.raises(WorkerStartupError, match="selected queues"):
        guard_celery_worker_startup(
            environment,
            {
                "queues": "celery",
                "concurrency": 2,
                "prefetch_multiplier": 1,
                "autoscale": None,
            },
        )


def test_direct_maintenance_worker_guard_rejects_autoscale_and_prefetch() -> None:
    environment = _environment(
        WorkerRole.MAINTENANCE,
        queues="maintenance-v2",
        concurrency="1",
    )

    with pytest.raises(WorkerStartupError, match="autoscale"):
        guard_celery_worker_startup(
            environment,
            {
                "queues": "maintenance-v2",
                "concurrency": 1,
                "prefetch_multiplier": 1,
                "autoscale": "1,2",
            },
        )
    with pytest.raises(WorkerStartupError, match="prefetch"):
        guard_celery_worker_startup(
            environment,
            {
                "queues": "maintenance-v2",
                "concurrency": 1,
                "prefetch_multiplier": 2,
                "autoscale": None,
            },
        )


def test_console_entrypoint_executes_exact_validated_worker_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment(
        WorkerRole.MAINTENANCE,
        queues="maintenance-v2",
        concurrency="1",
    )
    executed: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(os, "environ", environment)
    monkeypatch.setattr(
        os,
        "execv",
        lambda executable, argv: executed.append((executable, argv)),
    )

    main()

    assert len(executed) == 1
    assert executed[0][1] == build_worker_argv(environment)


def test_direct_celery_invocation_signal_exits_before_unsafe_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os, "environ", {})

    with pytest.raises(SystemExit, match=ROLE_ENV):
        celeryd_init.send(
            sender="worker",
            instance=object(),
            conf=celery_app.conf,
            options={
                "queues": None,
                "concurrency": None,
                "prefetch_multiplier": None,
                "autoscale": None,
            },
        )


def test_beat_configuration_does_not_require_worker_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ROLE_ENV, raising=False)
    monkeypatch.delenv(QUEUES_ENV, raising=False)
    monkeypatch.delenv(CONCURRENCY_ENV, raising=False)

    assert "cleanup-expired-jobs-hourly" in celery_app.conf.beat_schedule
