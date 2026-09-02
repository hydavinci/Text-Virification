from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.orm import Session

from text_verification.domain.artifacts import (
    ArtifactLifecycleStatus,
    ArtifactReservation,
)
from text_verification.domain.documents import FileType
from text_verification.domain.jobs import JobStatus
from text_verification.infrastructure.verification_repository import (
    VerificationRepository,
)


def test_finalize_export_artifact_locks_run_job_artifact_in_canonical_order() -> None:
    repository, reservation, order = _repository()

    snapshot = repository.finalize_export_artifact(
        reservation,
        ready_at=reservation.created_at + timedelta(minutes=1),
        consistency_check=lambda: None,
        require_current_result=True,
    )

    assert snapshot is not None
    assert order == ["run", "job", "artifact"]


def test_finalize_stale_artifact_locks_run_job_artifact_in_canonical_order() -> None:
    repository, reservation, order = _repository()

    snapshot = repository.finalize_stale_pending_export_artifact(
        reservation,
        ready_at=reservation.created_at + timedelta(minutes=1),
        consistency_check=lambda: None,
    )

    assert snapshot is not None
    assert order == ["run", "job", "artifact"]


def test_delete_stale_artifact_locks_run_job_artifact_in_canonical_order() -> None:
    repository, reservation, order = _repository()

    deleted = repository.delete_stale_pending_export_artifact(
        reservation,
        missing_check=lambda: True,
    )

    assert deleted is True
    assert order == ["run", "job", "artifact"]


class _RecordingSession:
    def __init__(self, run: SimpleNamespace, order: list[str]) -> None:
        self._run = run
        self._order = order

    def scalar(self, statement: object) -> SimpleNamespace:
        del statement
        self._order.append("run-query")
        return self._run

    def flush(self) -> None:
        return None

    def delete(self, value: object) -> None:
        del value


class _RecordingVerificationRepository(VerificationRepository):
    def __init__(
        self,
        session: Session,
        run: SimpleNamespace,
        job: SimpleNamespace,
        artifact: SimpleNamespace,
        order: list[str],
    ) -> None:
        super().__init__(session)
        self._run_row = run
        self._job_row = job
        self._artifact_row = artifact
        self._order = order

    def _lock_run(self, verification_run_id):  # type: ignore[no-untyped-def]
        assert verification_run_id == self._run_row.verification_run_id
        self._order.append("run")
        return cast(Any, self._run_row)

    def _lock_job(self, job_id):  # type: ignore[no-untyped-def]
        assert job_id == self._job_row.job_id
        self._order.append("job")
        return cast(Any, self._job_row)

    def _lock_artifact_or_none(self, export_artifact_id):  # type: ignore[no-untyped-def]
        assert export_artifact_id == self._artifact_row.export_artifact_id
        self._order.append("artifact")
        return cast(Any, self._artifact_row)


def _repository() -> tuple[
    VerificationRepository,
    ArtifactReservation,
    list[str],
]:
    created_at = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)
    job_id = uuid4()
    run_id = uuid4()
    document_id = uuid4()
    artifact_id = uuid4()
    storage_key = f"{job_id}/exports/{artifact_id}.docx"
    run = SimpleNamespace(
        verification_run_id=run_id,
        job_id=job_id,
        document_id=document_id,
        document=SimpleNamespace(source_version="sha256:source"),
    )
    job = SimpleNamespace(
        job_id=job_id,
        status=JobStatus.COMPLETED.value,
        expires_at=created_at + timedelta(days=1),
    )
    artifact = SimpleNamespace(
        export_artifact_id=artifact_id,
        run=run,
        verification_run_id=run_id,
        review_revision_id=None,
        source_version="sha256:source",
        file_type=FileType.DOCX.value,
        file_name="reconstructed.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        storage_key=storage_key,
        size_bytes=12,
        content_sha256="a" * 64,
        status=ArtifactLifecycleStatus.PENDING.value,
        reserved_at=created_at,
        ready_at=None,
        created_at=created_at,
    )
    reservation = ArtifactReservation(
        export_artifact_id=artifact_id,
        job_id=job_id,
        verification_run_id=run_id,
        review_revision_id=None,
        source_version="sha256:source",
        file_type=FileType.DOCX,
        file_name=artifact.file_name,
        media_type=artifact.media_type,
        storage_key=storage_key,
        size_bytes=12,
        content_sha256="a" * 64,
        status=ArtifactLifecycleStatus.PENDING,
        reserved_at=created_at,
        created_at=created_at,
    )
    order: list[str] = []
    session = cast(Session, _RecordingSession(run, order))
    repository = _RecordingVerificationRepository(
        session,
        run,
        job,
        artifact,
        order,
    )
    return repository, reservation, order
