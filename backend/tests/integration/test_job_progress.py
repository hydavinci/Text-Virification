from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI

from text_verification.domain.documents import FileType
from text_verification.domain.jobs import JobEvent, JobRead, JobStatus


class RecordingJobRepository:
    def __init__(self) -> None:
        self._jobs: dict[UUID, JobRead] = {}
        self._events: dict[UUID, list[JobEvent]] = {}

    def create_completed_job(self) -> JobRead:
        job_id = uuid4()
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)
        source_name = f"client-secret-{job_id}.txt"
        job = JobRead(
            job_id=job_id,
            source_name=source_name,
            file_type=FileType.TXT,
            size_bytes=12,
            status=JobStatus.COMPLETED,
            progress=100,
            created_at=created_at,
            expires_at=expires_at,
        )
        self._jobs[job_id] = job
        self._events[job_id] = [
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
                status=JobStatus.COMPLETED,
                progress=100,
                message="处理完成",
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
    return repository.create_completed_job()


@pytest.fixture(autouse=True)
def override_dependencies(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    repository: RecordingJobRepository,
) -> SessionFactorySpy:
    from text_verification.api.dependencies import get_job_repository
    from text_verification.api.routes import jobs as job_routes

    session_factory = SessionFactorySpy([])
    app.dependency_overrides[get_job_repository] = lambda: repository
    monkeypatch.setattr(job_routes, "SESSION_FACTORY_PROVIDER", lambda: session_factory)
    monkeypatch.setattr(job_routes, "REPOSITORY_FACTORY", lambda session: repository)
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
