from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from text_verification.application import (
    VerificationCommand,
    build_default_verification_pipeline,
)
from text_verification.config import Settings
from text_verification.domain.jobs import (
    TERMINAL_STATUSES,
    JobRead,
    JobStatus,
    TerminalJobStateError,
)
from text_verification.domain.verification import (
    VerificationExecutionMode,
    VerificationOptions,
    VerificationResult,
)
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.storage import JobStorage
from text_verification.infrastructure.verification_repository import (
    JobResultSnapshot,
    JobResultState,
)
from text_verification.workers.pipeline import PipelineRunner

SAMPLE = "帐号包含 test@example.com。"


class EquivalenceJobRepository:
    def __init__(self, job: JobRead) -> None:
        self._job = job

    def get_job(self, job_id: UUID) -> JobRead | None:
        return self._job if self._job.job_id == job_id else None

    def transition(
        self,
        job_id: UUID,
        status: JobStatus,
        progress: int,
        message: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        del message
        if self._job.job_id != job_id:
            raise LookupError(job_id)
        if self._job.status in TERMINAL_STATUSES:
            raise TerminalJobStateError(
                job_id=job_id,
                current_status=self._job.status,
                target_status=status,
            )
        self._job = self._job.model_copy(
            update={
                "status": status,
                "progress": progress,
                "error_code": error_code,
                "error_message": error_message,
            }
        )

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


class EquivalenceVerificationRepository:
    def __init__(self, jobs: EquivalenceJobRepository) -> None:
        self._jobs = jobs
        self._results: dict[UUID, VerificationResult] = {}

    def save_result(self, job_id: UUID, result: VerificationResult) -> None:
        self._results[job_id] = result

    def get_result_for_job(self, job_id: UUID) -> VerificationResult | None:
        return self._results.get(job_id)

    def read_result_snapshot(self, job_id: UUID) -> JobResultSnapshot:
        job = self._jobs.get_job(job_id)
        if job is None:
            return JobResultSnapshot(JobResultState.MISSING, None)
        result = self._results.get(job_id)
        if job.status is JobStatus.COMPLETED and result is not None:
            return JobResultSnapshot(JobResultState.READY, result)
        return JobResultSnapshot(JobResultState.PENDING, None)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def test_sync_and_async_results_have_equivalent_canonical_semantics(
    tmp_path,
) -> None:
    settings = Settings(storage_root=tmp_path / "jobs", llm_api_key="")
    storage = JobStorage(settings.storage_root, settings.max_upload_bytes)
    job_id = uuid4()
    stored = storage.save_bytes(job_id, "sample.txt", SAMPLE.encode("utf-8"))
    created_at = datetime.now(UTC)
    job_repository = EquivalenceJobRepository(
        JobRead(
            job_id=job_id,
            source_name=stored.original_name,
            file_type=stored.file_type,
            size_bytes=stored.size_bytes,
            status=JobStatus.QUEUED,
            progress=0,
            created_at=created_at,
            expires_at=created_at + timedelta(hours=24),
        )
    )
    pipeline = build_default_verification_pipeline(settings)
    runner = PipelineRunner(storage, pipeline)

    async_result = runner.run(
        job_repository.get_job(job_id),
        lambda stage: None,
    )
    sync_result = pipeline.run(
        VerificationCommand(
            document_id=uuid4(),
            source_path=stored.path,
            direct_text=None,
            source_name=stored.original_name,
            file_type=stored.file_type,
            options=VerificationOptions(),
            execution_mode=VerificationExecutionMode.SYNCHRONOUS,
        )
    )

    assert _normalize_result(sync_result) == _normalize_result(async_result)


def test_postgresql_worker_entry_matches_synchronous_canonical_result(
    db_session_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from text_verification.workers import tasks as worker_tasks

    settings = Settings(storage_root=tmp_path / "jobs", llm_api_key="")
    storage = JobStorage(settings.storage_root, settings.max_upload_bytes)
    job_id = uuid4()
    stored = storage.save_bytes(job_id, "sample.txt", SAMPLE.encode("utf-8"))
    now = datetime.now(UTC)
    seed_session = db_session_factory()
    try:
        repository = JobRepository(seed_session)
        repository.create_job(
            job_id=job_id,
            source_name=stored.original_name,
            file_type=stored.file_type,
            size_bytes=stored.size_bytes,
            storage_key=str(job_id),
            created_at=now,
            expires_at=now + timedelta(hours=24),
        )
        repository.commit()
    finally:
        seed_session.close()

    pipeline = build_default_verification_pipeline(settings)
    synchronous = pipeline.run(
        VerificationCommand(
            document_id=uuid4(),
            source_path=stored.path,
            direct_text=None,
            source_name=stored.original_name,
            file_type=stored.file_type,
            options=VerificationOptions(),
            execution_mode=VerificationExecutionMode.SYNCHRONOUS,
        )
    )
    monkeypatch.setattr(worker_tasks, "SESSION_FACTORY_PROVIDER", lambda: db_session_factory)
    monkeypatch.setattr(worker_tasks, "STORAGE_FACTORY", lambda: storage)
    monkeypatch.setattr(worker_tasks, "PIPELINE_FACTORY", lambda: pipeline)
    monkeypatch.setattr(worker_tasks, "get_settings", lambda: settings)

    worker_tasks._process_job(_BoundTask(), str(job_id))

    result_session = db_session_factory()
    try:
        asynchronous = worker_tasks.VerificationRepository(
            result_session
        ).get_result_for_job(job_id)
    finally:
        result_session.close()

    assert asynchronous is not None
    assert _normalize_result(synchronous) == _normalize_result(asynchronous)


class _BoundRequest:
    retries = 0


class _BoundTask:
    request = _BoundRequest()

    def retry(self, **kwargs: object) -> None:
        raise AssertionError(f"unexpected worker retry: {kwargs}")


def _normalize_result(result: VerificationResult) -> dict[str, Any]:
    payload = result.model_dump(mode="json")
    payload.pop("document_id")
    payload.pop("verification_run_id")
    payload.pop("execution_mode")
    for issue in payload["issues"]:
        issue.pop("document_id")
        issue.pop("verification_run_id")
    return payload
