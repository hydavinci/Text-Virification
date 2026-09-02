from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI

from text_verification.domain.documents import FileType
from text_verification.domain.jobs import JobEvent, JobRead, JobStatus
from text_verification.domain.verification import VerificationOptions
from text_verification.infrastructure.storage import JobStorage


def make_docx_bytes() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return data.getvalue()


class RecordingJobRepository:
    def __init__(self, *, fail_on_commit_calls: set[int] | None = None) -> None:
        self._fail_on_commit_calls = fail_on_commit_calls or set()
        self._commit_count = 0
        self.rollback_calls = 0
        self._jobs: dict[UUID, JobRead] = {}
        self._events: dict[UUID, list[JobEvent]] = {}
        self._reset_working_copy()

    def create_job(
        self,
        *,
        job_id: UUID,
        source_name: str,
        file_type: str,
        size_bytes: int,
        storage_key: str,
        verification_options: VerificationOptions,
        created_at: datetime,
        expires_at: datetime,
    ) -> JobRead:
        del storage_key
        job = JobRead(
            job_id=job_id,
            source_name=source_name,
            file_type=FileType(file_type),
            size_bytes=size_bytes,
            status=JobStatus.QUEUED,
            progress=0,
            verification_options=verification_options,
            created_at=created_at,
            expires_at=expires_at,
        )
        self._working_jobs[job_id] = job
        self._working_events[job_id] = [
            JobEvent(
                sequence=1,
                status=JobStatus.QUEUED,
                progress=0,
                message="作业已创建",
                created_at=created_at,
            )
        ]
        return job

    def get_job(self, job_id: UUID) -> JobRead | None:
        return self._jobs.get(job_id)

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
        current_job = self._working_jobs[job_id]
        changed_at = datetime.now(UTC)
        self._working_jobs[job_id] = current_job.model_copy(
            update={
                "status": status,
                "progress": progress,
                "error_code": error_code,
                "error_message": error_message,
            }
        )
        next_sequence = len(self._working_events[job_id]) + 1
        self._working_events[job_id].append(
            JobEvent(
                sequence=next_sequence,
                status=status,
                progress=progress,
                message=message,
                created_at=changed_at,
            )
        )

    def list_events_after(self, job_id: UUID, after_sequence: int) -> list[JobEvent]:
        return [
            event for event in self._events.get(job_id, []) if event.sequence > after_sequence
        ]

    def expire_jobs_before(self, cutoff: datetime) -> list[UUID]:
        del cutoff
        return []

    def commit(self) -> None:
        self._commit_count += 1
        if self._commit_count in self._fail_on_commit_calls:
            raise RuntimeError("database unavailable")
        self._jobs = {
            job_id: job.model_copy(deep=True) for job_id, job in self._working_jobs.items()
        }
        self._events = {
            job_id: [event for event in events] for job_id, events in self._working_events.items()
        }
        self._reset_working_copy()

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._reset_working_copy()

    def _reset_working_copy(self) -> None:
        self._working_jobs = {
            job_id: job.model_copy(deep=True) for job_id, job in self._jobs.items()
        }
        self._working_events = {
            job_id: [event for event in events] for job_id, events in self._events.items()
        }


@dataclass
class TaskSpy:
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def __call__(self, job_id: str) -> None:
        self.calls.append(job_id)
        if self.error is not None:
            raise self.error


def _override_dependency_if_present(
    app: FastAPI,
    module_name: str,
    attribute_name: str,
    replacement: object,
) -> None:
    try:
        module = __import__(module_name, fromlist=[attribute_name])
    except ImportError:
        return

    original = getattr(module, attribute_name, None)
    if original is None:
        return

    app.dependency_overrides[original] = replacement  # type: ignore[index]


def _patch_dispatcher_if_present(monkeypatch, spy: TaskSpy) -> None:
    try:
        jobs_routes = __import__(
            "text_verification.api.routes.jobs",
            fromlist=["dispatch_process_job"],
        )
    except ImportError:
        return

    if not hasattr(jobs_routes, "dispatch_process_job"):
        return

    monkeypatch.setattr(jobs_routes, "dispatch_process_job", spy)


@pytest.fixture
def repository(request) -> RecordingJobRepository:
    if "failing_repository" in request.fixturenames:
        return request.getfixturevalue("failing_repository")
    if "recovery_failing_repository" in request.fixturenames:
        return request.getfixturevalue("recovery_failing_repository")
    return RecordingJobRepository()


@pytest.fixture
def failing_repository() -> RecordingJobRepository:
    return RecordingJobRepository(fail_on_commit_calls={1})


@pytest.fixture
def recovery_failing_repository() -> RecordingJobRepository:
    return RecordingJobRepository(fail_on_commit_calls={2})


@pytest.fixture
def storage(tmp_path) -> JobStorage:
    root = tmp_path / "jobs"
    root.mkdir()
    return JobStorage(root, max_upload_bytes=25 * 1024 * 1024)


@pytest.fixture
def dispatch_error() -> RuntimeError:
    return RuntimeError("dispatcher offline")


@pytest.fixture
def task_spy(request, monkeypatch) -> TaskSpy:
    error: Exception | None = None
    if "dispatch_error" in request.fixturenames:
        error = request.getfixturevalue("dispatch_error")
    spy = TaskSpy(error=error)
    if "client" in request.fixturenames:
        _patch_dispatcher_if_present(monkeypatch, spy)
    return spy


@pytest.fixture(autouse=True)
def override_dependencies(
    request,
    app: FastAPI,
    repository: RecordingJobRepository,
    storage: JobStorage,
    task_spy: TaskSpy,
) -> None:
    if "client" not in request.fixturenames:
        return
    del task_spy
    _override_dependency_if_present(
        app,
        "text_verification.api.dependencies",
        "get_job_repository",
        lambda: repository,
    )
    _override_dependency_if_present(
        app,
        "text_verification.api.dependencies",
        "get_job_storage",
        lambda: storage,
    )


def test_create_txt_job_persists_and_enqueues(client, repository, task_spy) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", "需要检查".encode(), "text/plain")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["source_name"] == "sample.txt"
    assert payload["file_type"] == "txt"
    assert payload["status"] == "queued"
    assert payload["progress"] == 0
    assert "storage_key" not in payload
    assert task_spy.calls == [payload["job_id"]]
    assert repository.get_job(UUID(payload["job_id"])) is not None


def test_create_job_persists_nondefault_verification_options_without_exposing_lists(
    client,
    repository,
    task_spy,
) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"colour forbidden", "text/plain")},
        data={
            "scenario": "legal",
            "enable_security": "false",
            "enable_sensitive": "false",
            "enable_ad_extreme": "true",
            "custom_glossary": (
                '[{"original":"colour","standard":"color"}]'
            ),
            "banned_words": '["forbidden"]',
        },
    )

    assert response.status_code == 202
    body = response.json()
    job = repository.get_job(UUID(body["job_id"]))
    assert job is not None
    assert job.verification_options == VerificationOptions(
        scenario="legal",
        enable_security=False,
        enable_sensitive=False,
        enable_ad_extreme=True,
        custom_glossary=({"original": "colour", "standard": "color"},),
        banned_words=("forbidden",),
    )
    assert "verification_options" not in body
    assert "custom_glossary" not in response.text
    assert task_spy.calls == [body["job_id"]]


def test_create_job_rejects_oversized_options_before_upload_side_effects(
    client,
    repository,
    storage,
    task_spy,
    caplog: pytest.LogCaptureFixture,
) -> None:
    banned_words = [f"private-term-{index}" for index in range(501)]

    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", "text/plain")},
        data={"banned_words": __import__("json").dumps(banned_words)},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_verification_options"
    assert repository._jobs == {}
    assert list(storage._root.iterdir()) == []
    assert task_spy.calls == []
    assert "private-term" not in caplog.text


def test_same_source_with_different_options_creates_distinct_job_snapshots(
    client,
    repository,
    task_spy,
) -> None:
    first = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"same source", "text/plain")},
    )
    second = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"same source", "text/plain")},
        data={"scenario": "legal", "enable_security": "false"},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job_id"] != second.json()["job_id"]
    first_job = repository.get_job(UUID(first.json()["job_id"]))
    second_job = repository.get_job(UUID(second.json()["job_id"]))
    assert first_job is not None
    assert second_job is not None
    assert first_job.verification_options != second_job.verification_options
    assert task_spy.calls == [first.json()["job_id"], second.json()["job_id"]]


@pytest.mark.parametrize(
    ("name", "payload", "declared_mime", "expected_type"),
    [
        ("sample.txt", b"text", "text/plain", "txt"),
        ("sample.docx", make_docx_bytes(), (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ), "docx"),
        (
            "sample.doc",
            bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 16,
            "application/msword",
            "doc",
        ),
        ("sample.pdf", b"%PDF-1.7\n%%EOF", "application/pdf", "pdf"),
        ("sample.rtf", br"{\rtf1 sample}", "application/rtf", "rtf"),
        ("sample.md", b"# sample", "text/markdown", "md"),
        ("sample.csv", b"name,value\nsample,1\n", "text/csv", "csv"),
    ],
)
def test_create_job_accepts_all_seven_strictly_validated_formats(
    client,
    repository,
    task_spy,
    name: str,
    payload: bytes,
    declared_mime: str,
    expected_type: str,
) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": (name, payload, declared_mime)},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["file_type"] == expected_type
    assert task_spy.calls == [body["job_id"]]
    assert repository.get_job(UUID(body["job_id"])) is not None


@pytest.mark.parametrize(
    ("name", "payload", "declared_mime"),
    [
        ("sample.txt", b"text", "application/pdf"),
        ("sample.pdf", b"%PDF-1.7\n%%EOF", "text/plain"),
        (
            "sample.docx",
            make_docx_bytes(),
            "application/pdf",
        ),
    ],
)
def test_create_job_rejects_explicit_mime_mismatch_without_side_effects(
    client,
    repository,
    storage,
    task_spy,
    name: str,
    payload: bytes,
    declared_mime: str,
) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": (name, payload, declared_mime)},
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_file_type"
    assert repository._jobs == {}
    assert task_spy.calls == []
    assert list(storage._root.iterdir()) == []


@pytest.mark.parametrize("declared_mime", [None, "", "application/octet-stream"])
def test_create_job_accepts_missing_blank_or_generic_mime(
    client,
    repository,
    task_spy,
    declared_mime: str | None,
) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", declared_mime)},
    )

    assert response.status_code == 202
    payload = response.json()
    assert repository.get_job(UUID(payload["job_id"])) is not None
    assert task_spy.calls == [payload["job_id"]]


def test_create_job_normalizes_explicit_mime_case_and_parameters(
    client,
    repository,
    task_spy,
) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", " Text/Plain ; charset=utf-8 ")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert repository.get_job(UUID(payload["job_id"])) is not None
    assert task_spy.calls == [payload["job_id"]]


@pytest.mark.parametrize(
    "client_name",
    [
        "../../secret.txt",
        r"C:\Users\Alice\secret.txt",
    ],
)
def test_create_job_normalizes_source_name_to_basename(
    client,
    repository,
    task_spy,
    client_name: str,
) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": (client_name, b"text", "text/plain")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["source_name"] == "secret.txt"
    assert "/" not in payload["source_name"]
    assert "\\" not in payload["source_name"]
    assert task_spy.calls == [payload["job_id"]]
    assert repository.get_job(UUID(payload["job_id"])).source_name == "secret.txt"


def test_create_job_requires_file(client) -> None:
    assert client.post("/api/v1/jobs").status_code == 422


def test_create_job_rejects_unsupported_extension(client) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.exe", b"MZ", "application/octet-stream")},
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_file_type"


def test_create_job_rejects_extension_content_mismatch(client) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.pdf", b"plain text", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_upload"


def test_create_job_rejects_oversized_upload(client, storage) -> None:
    storage._max_upload_bytes = 8

    response = client.post(
        "/api/v1/jobs",
        files={"file": ("large.txt", b"x" * 9, "text/plain")},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "upload_too_large"


def test_database_failure_removes_written_job_directory(
    client,
    failing_repository,
    storage,
) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", "text/plain")},
    )

    assert response.status_code == 500
    assert failing_repository.rollback_calls == 1
    assert list(storage._root.iterdir()) == []


def test_database_failure_cleanup_failure_returns_shaped_error(
    client,
    failing_repository,
    storage,
    monkeypatch,
) -> None:
    def failing_delete_job(job_id: UUID) -> None:
        del job_id
        raise PermissionError(r"locked C:\jobs\secret.txt")

    monkeypatch.setattr(storage, "delete_job", failing_delete_job)

    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", "text/plain")},
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "job_cleanup_failed"
    assert failing_repository.rollback_calls == 1
    assert len(list(storage._root.iterdir())) == 1
    assert "locked" not in response.text.lower()
    assert str(storage._root).lower() not in response.text.lower()


def test_dispatch_failure_marks_job_failed_and_removes_upload(
    client,
    repository,
    storage,
    dispatch_error,
) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", "text/plain")},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "job_dispatch_failed"
    assert len(repository._jobs) == 1
    [job] = repository._jobs.values()
    assert job.status == JobStatus.FAILED
    assert job.error_code == "job_dispatch_failed"
    assert list(storage._root.iterdir()) == []
    assert str(dispatch_error) not in response.text


def test_dispatch_failure_cleanup_failure_returns_shaped_error(
    client,
    repository,
    storage,
    dispatch_error,
    monkeypatch,
) -> None:
    def failing_delete_job(job_id: UUID) -> None:
        del job_id
        raise PermissionError(r"locked C:\jobs\secret.txt")

    monkeypatch.setattr(storage, "delete_job", failing_delete_job)

    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", "text/plain")},
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "job_dispatch_cleanup_failed"
    [job] = repository._jobs.values()
    assert job.status == JobStatus.FAILED
    assert job.error_code == "job_dispatch_failed"
    assert repository.rollback_calls == 0
    assert len(list(storage._root.iterdir())) == 1
    assert "locked" not in response.text.lower()
    assert str(storage._root).lower() not in response.text.lower()


def test_dispatch_recovery_commit_failure_returns_shaped_error(
    client,
    recovery_failing_repository,
    storage,
    dispatch_error,
) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", "text/plain")},
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "job_dispatch_recovery_failed"
    assert recovery_failing_repository.rollback_calls == 1
    [job] = recovery_failing_repository._jobs.values()
    assert job.status == JobStatus.QUEUED
    assert job.error_code is None
    assert len(list(storage._root.iterdir())) == 1
    assert "database unavailable" not in response.text.lower()


def test_dispatch_process_job_imports_planned_worker_task(monkeypatch) -> None:
    dispatch_calls: list[str] = []

    def fake_import_module(module_name: str) -> object:
        assert module_name == "text_verification.workers.tasks"

        return SimpleNamespace(
            dispatch_process_job=lambda job_id: dispatch_calls.append(job_id)
        )

    monkeypatch.setattr(
        "text_verification.api.routes.jobs.import_module",
        fake_import_module,
    )

    from text_verification.api.routes.jobs import dispatch_process_job

    dispatch_process_job("job-123")

    assert dispatch_calls == ["job-123"]


def test_create_job_response_never_exposes_storage_path(client) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", "text/plain")},
    )

    serialized = response.text.lower()
    assert "storage_key" not in serialized
    assert "source.txt" not in serialized
    assert "\\\\" not in serialized
    assert "text" not in serialized
