from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from text_verification import application
from text_verification.domain.documents import FileType
from text_verification.infrastructure.storage import (
    JobStorage,
    PublishedArtifact,
    VerifiedArtifact,
    build_artifact_storage_key,
)


@dataclass
class FakeArtifactRepository:
    verifier: Callable[[PublishedArtifact], VerifiedArtifact]
    save_error: Exception | None = None
    commit_error: Exception | None = None
    mutate_before_error: bytes | None = None
    saved: list[VerifiedArtifact] = field(default_factory=list)
    commits: int = 0
    rollbacks: int = 0

    def save_export_artifact(self, **values: object) -> VerifiedArtifact:
        artifact = values["artifact"]
        assert isinstance(artifact, PublishedArtifact)
        verified = self.verifier(artifact)
        self.saved.append(verified)
        if self.mutate_before_error is not None:
            verified.path.write_bytes(self.mutate_before_error)
        if self.save_error is not None:
            raise self.save_error
        return verified

    def commit(self) -> None:
        self.commits += 1
        if self.commit_error is not None:
            raise self.commit_error

    def rollback(self) -> None:
        self.rollbacks += 1


def _request(
    *,
    job_id=None,
    artifact_id=None,
    data: bytes = b"artifact",
):
    resolved_job_id = job_id or uuid4()
    resolved_artifact_id = artifact_id or uuid4()
    return application.ArtifactPersistenceRequest(
        job_id=resolved_job_id,
        export_artifact_id=resolved_artifact_id,
        verification_run_id=uuid4(),
        review_revision_id=None,
        source_version="sha256:source",
        file_type=FileType.TXT,
        file_name="reviewed.txt",
        media_type="text/plain",
        storage_key=build_artifact_storage_key(
            resolved_job_id,
            resolved_artifact_id,
            FileType.TXT,
        ),
        data=data,
        created_at=datetime(2026, 9, 1, 4, 0, tzinfo=UTC),
    )


def test_artifact_service_publishes_verifies_and_commits(tmp_path: Path) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    repository = FakeArtifactRepository(storage.verify_artifact)
    request = _request()
    service = application.ArtifactPersistenceService(storage, repository)

    result = service.persist(request)

    assert result.export_artifact_id == request.export_artifact_id
    assert result.storage_key == request.storage_key
    assert result.path.read_bytes() == request.data
    assert result.size_bytes == len(request.data)
    assert len(result.content_sha256) == 64
    assert result.created is True
    assert repository.commits == 1
    assert repository.rollbacks == 0
    assert repository.saved[0].content_sha256 == result.content_sha256


@pytest.mark.parametrize(
    "error",
    [
        ValueError("artifact does not belong to job"),
        ValueError("source version does not match"),
    ],
)
def test_artifact_service_compensates_new_file_after_repository_rejection(
    tmp_path: Path,
    error: Exception,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    repository = FakeArtifactRepository(storage.verify_artifact, save_error=error)
    request = _request()
    service = application.ArtifactPersistenceService(storage, repository)

    with pytest.raises(ValueError, match=str(error)):
        service.persist(request)

    assert not (tmp_path / request.storage_key).exists()
    assert repository.commits == 0
    assert repository.rollbacks == 1


def test_artifact_service_keeps_preexisting_idempotent_file_on_unique_conflict(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    existing = storage.publish_artifact(
        request.job_id,
        request.export_artifact_id,
        request.storage_key,
        request.file_type,
        request.data,
    )
    repository = FakeArtifactRepository(
        storage.verify_artifact,
        save_error=ValueError("storage key is already persisted")
    )
    service = application.ArtifactPersistenceService(storage, repository)

    with pytest.raises(ValueError, match="already persisted"):
        service.persist(request)

    assert existing.path.read_bytes() == request.data
    assert repository.rollbacks == 1


def test_artifact_service_compensates_new_file_after_commit_exception(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    repository = FakeArtifactRepository(
        storage.verify_artifact,
        commit_error=RuntimeError("commit failed"),
    )
    request = _request()
    service = application.ArtifactPersistenceService(storage, repository)

    with pytest.raises(RuntimeError, match="commit failed"):
        service.persist(request)

    assert not (tmp_path / request.storage_key).exists()
    assert repository.commits == 1
    assert repository.rollbacks == 1


def test_artifact_service_does_not_delete_file_changed_after_verification(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    repository = FakeArtifactRepository(
        storage.verify_artifact,
        save_error=ValueError("flush failed"),
        mutate_before_error=b"changed",
    )
    request = _request()
    service = application.ArtifactPersistenceService(storage, repository)

    with pytest.raises(ValueError, match="flush failed"):
        service.persist(request)

    assert (tmp_path / request.storage_key).read_bytes() == b"changed"
    assert repository.rollbacks == 1
