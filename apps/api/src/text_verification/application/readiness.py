from __future__ import annotations

import json
import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from functools import lru_cache
from threading import Lock
from time import monotonic
from typing import Any
from urllib.request import urlopen

from kombu import Connection as BrokerConnection  # type: ignore[import-untyped]
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

PROBE_TIMEOUT_SECONDS = 2
READINESS_TIMEOUT_SECONDS = 3.0
READINESS_CACHE_SECONDS = 5.0
logger = logging.getLogger(__name__)


class ReadinessChecker:
    def __init__(
        self,
        probes: dict[str, Callable[[], bool]],
        *,
        timeout: float = READINESS_TIMEOUT_SECONDS,
        cache_seconds: float = READINESS_CACHE_SECONDS,
    ) -> None:
        self._probes = probes
        self._timeout = timeout
        self._cache_seconds = cache_seconds
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, len(probes)), thread_name_prefix="readiness",
        )
        self._lock = Lock()
        self._pending: dict[str, Future[bool]] = {}
        self._cached: dict[str, bool] = {}
        self._expires_at = 0.0

    def check(self) -> dict[str, bool]:
        # Single-flight also bounds queued probes when a dependency ignores its
        # socket timeout. An unfinished probe is never submitted a second time.
        with self._lock:
            if monotonic() < self._expires_at:
                return dict(self._cached)
            for name, probe in self._probes.items():
                if name not in self._pending:
                    self._pending[name] = self._executor.submit(probe)
            wait(self._pending.values(), timeout=self._timeout)
            results: dict[str, bool] = {}
            for name, future in list(self._pending.items()):
                results[name] = False
                if future.done():
                    del self._pending[name]
                    try:
                        results[name] = bool(future.result())
                    except Exception as error:
                        logger.warning(
                            "readiness_probe_failed",
                            extra={"probe": name, "error_type": type(error).__name__},
                        )
            self._cached = results
            self._expires_at = monotonic() + self._cache_seconds
            return dict(results)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def compatible_worker_available(
    registered: dict[str, Any] | None,
    queues: dict[str, Any] | None,
) -> bool:
    if not registered or not queues:
        return False
    return any(
        "text_verification.process_job" in tasks
        and any(queue.get("name") == "verification-v2" for queue in queues.get(worker, []))
        for worker, tasks in registered.items()
    )


def _database_ready(database_url: str) -> bool:
    engine = create_engine(
        database_url,
        poolclass=NullPool,
        connect_args={
            "connect_timeout": PROBE_TIMEOUT_SECONDS,
            "options": f"-c statement_timeout={PROBE_TIMEOUT_SECONDS * 1000}",
        },
    )
    try:
        with engine.connect() as connection:
            return bool(connection.execute(text("SELECT 1")).scalar_one() == 1)
    finally:
        engine.dispose()


def _redis_ready(redis_url: str) -> bool:
    with Redis.from_url(
        redis_url,
        socket_connect_timeout=PROBE_TIMEOUT_SECONDS,
        socket_timeout=PROBE_TIMEOUT_SECONDS,
        retry=Retry(NoBackoff(), 0),
    ) as client:
        return bool(client.ping())


def _broker_connection(broker_url: str) -> BrokerConnection:
    return BrokerConnection(
        broker_url,
        connect_timeout=PROBE_TIMEOUT_SECONDS,
        transport_options={
            "socket_connect_timeout": PROBE_TIMEOUT_SECONDS,
            "socket_timeout": PROBE_TIMEOUT_SECONDS,
            "max_retries": 0,
        },
    )


def _broker_ready(broker_url: str) -> bool:
    with _broker_connection(broker_url) as connection:
        connection.ensure_connection(max_retries=0)
        return bool(connection.connected)


def _worker_ready(broker_url: str) -> bool:
    from text_verification.workers.celery_app import celery_app

    with _broker_connection(broker_url) as connection:
        connection.ensure_connection(max_retries=0)
        inspector = celery_app.control.inspect(timeout=0.75, connection=connection)
        return compatible_worker_available(inspector.registered(), inspector.active_queues())


def _renderer_ready(renderer_url: str) -> bool:
    if not renderer_url:
        return False
    with urlopen(
        f"{renderer_url.rstrip('/')}/health", timeout=PROBE_TIMEOUT_SECONDS,
    ) as response:
        return bool(
            response.status == 200
            and json.loads(response.read(1024)).get("status") == "ok"
        )


@lru_cache(maxsize=1)
def get_readiness_checker(
    database_url: str,
    redis_url: str,
    broker_url: str,
    renderer_url: str,
) -> ReadinessChecker:
    return ReadinessChecker({
        "database": lambda: _database_ready(database_url),
        "redis": lambda: _redis_ready(redis_url),
        "broker": lambda: _broker_ready(broker_url or redis_url),
        "worker": lambda: _worker_ready(broker_url or redis_url),
        "renderer": lambda: _renderer_ready(renderer_url),
    })
