import logging
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from text_verification.api.routes import health


@pytest.mark.parametrize("available", [False, True])
def test_readiness_reports_dependencies_without_changing_liveness(monkeypatch, available):
    app = FastAPI()
    app.include_router(health.router, prefix="/api/v1")
    monkeypatch.setattr(
        health, "get_readiness_checker",
        lambda *args: type("Checker", (), {"check": lambda self: {"database": available}})(),
        raising=False,
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/ready")
        assert response.status_code == (200 if available else 503)
        assert response.json() == {
            "status": "ready" if available else "not_ready",
            "checks": {"database": "ok" if available else "unavailable"},
        }
        assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/v1/health").status_code == 200


def test_readiness_bounds_slow_probes_and_does_not_enqueue_duplicates():
    from text_verification.application.readiness import ReadinessChecker

    release = Event()
    started = Event()
    calls = []

    def slow():
        calls.append(1)
        started.set()
        release.wait(2)
        return True

    checker = ReadinessChecker({"worker": slow}, timeout=0.03, cache_seconds=0)
    try:
        before = time.monotonic()
        assert checker.check() == {"worker": False}
        assert time.monotonic() - before < 0.5
        assert started.is_set()
        assert checker.check() == {"worker": False}
        assert calls == [1]
    finally:
        release.set()
        checker.close()


def test_readiness_caches_concurrent_requests_and_sanitizes_failures(caplog):
    from text_verification.application.readiness import ReadinessChecker

    calls = []

    def broken():
        calls.append(1)
        raise RuntimeError("postgres://secret:password@internal/stack")

    checker = ReadinessChecker(
        {"database": broken, "redis": lambda: True}, timeout=0.1, cache_seconds=5,
    )
    try:
        with (
            caplog.at_level(logging.WARNING, logger="text_verification.application.readiness"),
            ThreadPoolExecutor(max_workers=4) as executor,
        ):
            results = list(executor.map(lambda _: checker.check(), range(4)))
        assert results == [{"database": False, "redis": True}] * 4
        assert calls == [1]
        [record] = caplog.records
        assert record.getMessage() == "readiness_probe_failed"
        assert record.probe == "database"
        assert record.error_type == "RuntimeError"
        assert record.exc_info is None
        assert "secret" not in caplog.text
        assert "password" not in caplog.text
        assert "internal" not in caplog.text
    finally:
        checker.close()


def test_worker_compatibility_requires_task_and_queue_on_same_worker():
    from text_verification.application.readiness import compatible_worker_available

    tasks = {"old": ["text_verification.process_job"], "new": ["other.task"]}
    queues = {"old": [{"name": "celery"}], "new": [{"name": "verification-v2"}]}
    assert not compatible_worker_available(tasks, queues)
    tasks["new"] = ["text_verification.process_job"]
    assert compatible_worker_available(tasks, queues)
    assert not compatible_worker_available(None, queues)


def test_readiness_rechecks_after_cache_expiry():
    from text_verification.application.readiness import ReadinessChecker

    values = iter([False, True])
    checker = ReadinessChecker(
        {"database": lambda: next(values)}, cache_seconds=0, timeout=0.1,
    )
    try:
        assert checker.check() == {"database": False}
        assert checker.check() == {"database": True}
    finally:
        checker.close()
