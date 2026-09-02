from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn

from text_verification.workers.celery_app import (
    ADVANCED_PROCESSING_QUEUE,
    LEGACY_PROCESSING_QUEUE,
    MAINTENANCE_QUEUE,
)

ROLE_ENV = "TEXT_VERIFICATION_WORKER_ROLE"
QUEUES_ENV = "TEXT_VERIFICATION_WORKER_QUEUES"
CONCURRENCY_ENV = "TEXT_VERIFICATION_WORKER_CONCURRENCY"
WORKER_PREFETCH_MULTIPLIER = 1


class WorkerRole(StrEnum):
    VERIFICATION = "verification"
    MAINTENANCE = "maintenance"


class WorkerStartupError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkerSpec:
    role: WorkerRole
    queues: tuple[str, ...]
    concurrency: int
    hostname: str


_SPECS = {
    WorkerRole.VERIFICATION: WorkerSpec(
        role=WorkerRole.VERIFICATION,
        queues=(LEGACY_PROCESSING_QUEUE, ADVANCED_PROCESSING_QUEUE),
        concurrency=2,
        hostname="verification@%h",
    ),
    WorkerRole.MAINTENANCE: WorkerSpec(
        role=WorkerRole.MAINTENANCE,
        queues=(MAINTENANCE_QUEUE,),
        concurrency=1,
        hostname="maintenance@%h",
    ),
}


def resolve_worker_spec(environment: Mapping[str, str]) -> WorkerSpec:
    raw_role = environment.get(ROLE_ENV)
    if not raw_role:
        raise WorkerStartupError(f"{ROLE_ENV} is required.")
    try:
        role = WorkerRole(raw_role)
    except ValueError as error:
        raise WorkerStartupError(f"Unknown {ROLE_ENV}: {raw_role!r}.") from error
    spec = _SPECS[role]

    raw_queues = environment.get(QUEUES_ENV)
    if not raw_queues:
        raise WorkerStartupError(f"{QUEUES_ENV} is required for role {role.value}.")
    queues = tuple(part.strip() for part in raw_queues.split(",") if part.strip())
    if queues != spec.queues:
        raise WorkerStartupError(
            f"{QUEUES_ENV} for role {role.value} must be "
            f"{','.join(spec.queues)!r}."
        )

    raw_concurrency = environment.get(CONCURRENCY_ENV)
    if not raw_concurrency:
        raise WorkerStartupError(
            f"{CONCURRENCY_ENV} is required for role {role.value}."
        )
    try:
        concurrency = int(raw_concurrency)
    except ValueError as error:
        raise WorkerStartupError(f"{CONCURRENCY_ENV} must be an integer.") from error
    if concurrency != spec.concurrency:
        raise WorkerStartupError(
            f"{CONCURRENCY_ENV} for role {role.value} must be {spec.concurrency}."
        )
    return spec


def build_worker_argv(environment: Mapping[str, str]) -> list[str]:
    spec = resolve_worker_spec(environment)
    return [
        sys.executable,
        "-m",
        "celery",
        "-A",
        "text_verification.workers.celery_app:celery_app",
        "worker",
        "--loglevel=INFO",
        f"--queues={','.join(spec.queues)}",
        f"--concurrency={spec.concurrency}",
        f"--prefetch-multiplier={WORKER_PREFETCH_MULTIPLIER}",
        f"--hostname={spec.hostname}",
    ]


def guard_celery_worker_startup(
    environment: Mapping[str, str],
    options: Mapping[str, object],
) -> None:
    spec = resolve_worker_spec(environment)
    selected_queues = _selected_queues(options.get("queues"))
    if selected_queues != spec.queues:
        raise WorkerStartupError(
            f"Worker role {spec.role.value} selected queues "
            f"{selected_queues!r}; expected {spec.queues!r}."
        )

    concurrency = _positive_integer(options.get("concurrency"), "concurrency")
    if concurrency != spec.concurrency:
        raise WorkerStartupError(
            f"Worker role {spec.role.value} concurrency must be {spec.concurrency}."
        )
    if options.get("autoscale"):
        raise WorkerStartupError(
            f"Worker role {spec.role.value} must not enable autoscale."
        )
    prefetch = _positive_integer(
        options.get("prefetch_multiplier"),
        "prefetch multiplier",
    )
    if prefetch != WORKER_PREFETCH_MULTIPLIER:
        raise WorkerStartupError(
            f"Worker role {spec.role.value} prefetch multiplier must be "
            f"{WORKER_PREFETCH_MULTIPLIER}."
        )


def main() -> None:
    argv = build_worker_argv(os.environ)
    _exec_worker(argv)


def _exec_worker(argv: list[str]) -> NoReturn:
    os.execv(argv[0], argv)


def _selected_queues(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, Sequence):
        selected: list[str] = []
        for item in value:
            queue_name = getattr(item, "name", item)
            if not isinstance(queue_name, str) or not queue_name:
                raise WorkerStartupError("Worker selected queues are invalid.")
            selected.append(queue_name)
        return tuple(selected)
    raise WorkerStartupError("Worker selected queues are required.")


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise WorkerStartupError(f"Worker {field_name} must be a positive integer.")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError as error:
            raise WorkerStartupError(
                f"Worker {field_name} must be a positive integer."
            ) from error
    else:
        raise WorkerStartupError(
            f"Worker {field_name} must be a positive integer."
        )
    if parsed < 1:
        raise WorkerStartupError(f"Worker {field_name} must be a positive integer.")
    return parsed
