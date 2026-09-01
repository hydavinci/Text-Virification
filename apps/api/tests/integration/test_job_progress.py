from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI

from text_verification.domain.documents import FileType, TextBlock
from text_verification.domain.jobs import (
    RESULT_READY_STATUSES,
    TERMINAL_STATUSES,
    JobEvent,
    JobRead,
    JobStatus,
)
from text_verification.domain.verification import (
    Scenario,
    VerificationAnalysisMode,
    VerificationDegradation,
    VerificationExecutionMode,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)
from text_verification.infrastructure.verification_repository import (
    JobResultSnapshot,
    JobResultState,
)


class RecordingJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[UUID, JobRead] = {}
        self._events: dict[UUID, list[JobEvent]] = {}

    def create_job(self, status: JobStatus = JobStatus.COMPLETED) -> JobRead:
        job_id = uuid4()
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)
        source_name = f"client-secret-{job_id}.txt"
        job = JobRead(
            job_id=job_id,
            source_name=source_name,
            file_type=FileType.TXT,
            size_bytes=12,
            status=status,
            progress=100 if status is JobStatus.COMPLETED else 25,
            created_at=created_at,
            expires_at=expires_at,
        )
        self._jobs[job_id] = job
        completed_events = [
            JobEvent(
                sequence=1,
                status=JobStatus.QUEUED,
                progress=0,
                message="作业已创建",
                created_at=created_at,
            ),
            JobEvent(
                sequence=2,
                status=JobStatus.UPLOAD_VALIDATED,
                progress=10,
                message="上传校验完成",
                created_at=created_at,
            ),
            JobEvent(
                sequence=3,
                status=JobStatus.PARSING,
                progress=25,
                message="开始解析",
                created_at=created_at,
            ),
            JobEvent(
                sequence=4,
                status=JobStatus.CHECKING_FORMAT,
                progress=50,
                message="正在检查格式",
                created_at=created_at,
            ),
            JobEvent(
                sequence=5,
                status=JobStatus.CHECKING_SENSITIVE,
                progress=65,
                message="正在检查敏感词",
                created_at=created_at,
            ),
            JobEvent(
                sequence=6,
                status=JobStatus.CHECKING_CHINESE,
                progress=80,
                message="正在检查中文",
                created_at=created_at,
            ),
            JobEvent(
                sequence=7,
                status=JobStatus.CHECKING_ENGLISH,
                progress=90,
                message="正在检查英文",
                created_at=created_at,
            ),
            JobEvent(
                sequence=8,
                status=JobStatus.COMPLETED,
                progress=100,
                message="处理完成",
                created_at=created_at,
            ),
        ]
        if status is JobStatus.COMPLETED:
            self._events[job_id] = completed_events
        else:
            self._events[job_id] = [
                completed_events[0],
                JobEvent(
                    sequence=2,
                    status=status,
                    progress=job.progress,
                    message=f"作业状态：{status.value}",
                    created_at=created_at,
                ),
            ]
        return job

    def get_job(self, job_id: UUID) -> JobRead | None:
        return self._jobs.get(job_id)

    def list_events_after(self, job_id: UUID, after_sequence: int) -> list[JobEvent]:
        return [
            event for event in self._events.get(job_id, []) if event.sequence > after_sequence
        ]


class RecordingVerificationRepository:
    def __init__(self) -> None:
        self._results: dict[UUID, VerificationResult] = {}
        self._jobs: RecordingJobRepository | None = None
        self.snapshot_calls: list[UUID] = []
        self.rollback_calls = 0

    def bind_jobs(self, repository: RecordingJobRepository) -> None:
        self._jobs = repository

    def set_result(self, job_id: UUID, result: VerificationResult) -> None:
        self._results[job_id] = result

    def read_result_snapshot(self, job_id: UUID) -> JobResultSnapshot:
        self.snapshot_calls.append(job_id)
        if self._jobs is None:
            raise AssertionError("job repository is not bound")
        job = self._jobs.get_job(job_id)
        if job is None:
            return JobResultSnapshot(JobResultState.MISSING, None)
        if job.status is JobStatus.EXPIRED:
            return JobResultSnapshot(JobResultState.EXPIRED, None)
        if job.status not in RESULT_READY_STATUSES:
            state = (
                JobResultState.UNAVAILABLE
                if job.status in TERMINAL_STATUSES
                else JobResultState.PENDING
            )
            return JobResultSnapshot(state, None)
        result = self._results.get(job_id)
        if result is None:
            return JobResultSnapshot(JobResultState.UNAVAILABLE, None)
        return JobResultSnapshot(JobResultState.READY, result)

    def rollback(self) -> None:
        self.rollback_calls += 1


@dataclass
class FakeSession:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


@dataclass
class SessionFactorySpy:
    sessions: list[FakeSession]

    def __call__(self) -> FakeSession:
        session = FakeSession()
        self.sessions.append(session)
        return session


@pytest.fixture
def repository() -> RecordingJobRepository:
    return RecordingJobRepository()


@pytest.fixture
def completed_job(repository: RecordingJobRepository) -> JobRead:
    return repository.create_job()


@pytest.fixture
def result_repository() -> RecordingVerificationRepository:
    return RecordingVerificationRepository()


@pytest.fixture(autouse=True)
def override_dependencies(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    repository: RecordingJobRepository,
    result_repository: RecordingVerificationRepository,
) -> SessionFactorySpy:
    from text_verification.api.dependencies import get_db_session, get_job_repository
    from text_verification.api.routes import jobs as job_routes

    session_factory = SessionFactorySpy([])
    result_repository.bind_jobs(repository)
    app.dependency_overrides[get_job_repository] = lambda: repository
    app.dependency_overrides[get_db_session] = lambda: FakeSession()
    monkeypatch.setattr(job_routes, "SESSION_FACTORY_PROVIDER", lambda: session_factory)
    monkeypatch.setattr(job_routes, "REPOSITORY_FACTORY", lambda session: repository)
    monkeypatch.setattr(
        job_routes,
        "VERIFICATION_REPOSITORY_FACTORY",
        lambda session: result_repository,
        raising=False,
    )
    return session_factory


def test_get_job_returns_job_payload(client, completed_job: JobRead) -> None:
    response = client.get(f"/api/v1/jobs/{completed_job.job_id}")

    assert response.status_code == 200
    assert response.json()["job_id"] == str(completed_job.job_id)
    assert response.json()["status"] == "completed"


def test_get_job_returns_404_for_unknown_job(client) -> None:
    response = client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "job_not_found"


def test_get_job_result_returns_canonical_result(
    client,
    completed_job: JobRead,
    result_repository: RecordingVerificationRepository,
) -> None:
    result = _result_for_job(completed_job)
    result_repository.set_result(completed_job.job_id, result)

    response = client.get(f"/api/v1/jobs/{completed_job.job_id}/result")

    assert response.status_code == 200
    assert response.json() == result.model_dump(mode="json")
    assert response.json()["execution_mode"] == "asynchronous"
    assert "success" not in response.json()
    assert "filename" not in response.json()
    assert result_repository.snapshot_calls == [completed_job.job_id]
    assert result_repository.rollback_calls == 1


def test_get_job_result_returns_404_for_unknown_job(client) -> None:
    response = client.get(
        "/api/v1/jobs/00000000-0000-0000-0000-000000000000/result"
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "job_not_found",
        "message": "Job was not found.",
    }


def test_get_job_result_returns_409_while_job_is_non_terminal(
    client,
    repository: RecordingJobRepository,
) -> None:
    job = repository.create_job(JobStatus.PARSING)

    response = client.get(f"/api/v1/jobs/{job.job_id}/result")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "job_result_pending",
        "message": "Job result is not available yet.",
    }


def test_get_job_result_returns_409_when_failed_job_has_no_result(
    client,
    repository: RecordingJobRepository,
) -> None:
    job = repository.create_job(JobStatus.FAILED)

    response = client.get(f"/api/v1/jobs/{job.job_id}/result")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "job_result_unavailable",
        "message": "Job did not produce a result.",
    }


def test_get_job_result_does_not_expose_result_for_failed_job(
    client,
    repository: RecordingJobRepository,
    result_repository: RecordingVerificationRepository,
) -> None:
    job = repository.create_job(JobStatus.FAILED)
    result_repository.set_result(job.job_id, _result_for_job(job))

    response = client.get(f"/api/v1/jobs/{job.job_id}/result")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "job_result_unavailable"


@pytest.mark.parametrize("persist_result", [False, True])
def test_get_job_result_returns_410_when_job_is_expired(
    client,
    repository: RecordingJobRepository,
    result_repository: RecordingVerificationRepository,
    persist_result: bool,
) -> None:
    job = repository.create_job(JobStatus.EXPIRED)
    if persist_result:
        result_repository.set_result(job.job_id, _result_for_job(job))

    response = client.get(f"/api/v1/jobs/{job.job_id}/result")

    assert response.status_code == 410
    assert response.json()["detail"] == {
        "code": "job_result_expired",
        "message": "Job result has expired.",
    }


def test_get_job_result_returns_409_when_completed_job_has_no_result(
    client,
    completed_job: JobRead,
) -> None:
    response = client.get(f"/api/v1/jobs/{completed_job.job_id}/result")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "job_result_unavailable",
        "message": "Job did not produce a result.",
    }


def test_sse_replays_events_after_last_event_id(client, completed_job: JobRead) -> None:
    response = client.get(
        f"/api/v1/jobs/{completed_job.job_id}/events",
        headers={"Last-Event-ID": "1"},
    )
    client_path = rf"C:\Users\Alice\{completed_job.source_name}"

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 2" in response.text
    assert '"status":"upload_validated"' in response.text
    assert '"status":"completed"' in response.text
    assert "event: done" in response.text
    assert completed_job.source_name not in response.text
    assert client_path not in response.text


def test_sse_closes_missing_jobs_as_expired_without_path_leakage(client) -> None:
    response = client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000/events")
    client_path = r"C:\Users\Alice\missing-secret.txt"

    assert response.status_code == 200
    assert "event: expired" in response.text
    assert "var\\jobs" not in response.text.lower()
    assert "missing-secret.txt" not in response.text
    assert client_path not in response.text


def test_sse_rejects_negative_last_event_id(client, completed_job: JobRead) -> None:
    response = client.get(
        f"/api/v1/jobs/{completed_job.job_id}/events",
        headers={"Last-Event-ID": "-1"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_last_event_id"


def _result_for_job(job: JobRead) -> VerificationResult:
    return VerificationResult(
        verification_run_id=uuid4(),
        document_id=job.job_id,
        source_version="sha256:test-source",
        source_name=job.source_name,
        file_type=job.file_type,
        scenario=Scenario.GENERAL,
        text="需要检查",
        blocks=(
            TextBlock(
                block_id="p-0",
                kind="paragraph",
                text="需要检查",
                global_start=0,
                global_end=4,
                block_start=0,
                block_end=4,
                page=None,
                paragraph_index=0,
                table_index=None,
                row_index=None,
                cell_index=None,
                bbox=None,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": 0},
            ),
        ),
        parser_name="test-parser",
        parser_version="1",
        stats=VerificationStatistics(
            char_count=4,
            char_count_no_space=4,
            line_count=1,
            paragraph_count=1,
            language="zh",
            primary_count=4,
            primary_label="中文字符",
        ),
        issues=(),
        summary=VerificationSummary(total=0),
        execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
        analysis_mode=VerificationAnalysisMode.LOCAL_ONLY,
        dictionary_versions={},
        degradation=VerificationDegradation(),
    )
