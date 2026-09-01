import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from text_verification import application
from text_verification.domain.documents import FileType
from text_verification.infrastructure.storage import JobStorage, build_artifact_storage_key


@dataclass
class ScriptedReservationRepository:
    reservation: object
    ready_snapshot: object
    reserve_error: Exception | None = None
    finalize_error: Exception | None = None
    after_consistency: Callable[[], None] | None = None
    commit_error_on_call: int | None = None
    read_snapshot: object | None = None
    read_error: Exception | None = None
    commit_calls: int = 0
    rollback_calls: int = 0

    def reserve_export_artifact(self, **values: object):
        del values
        if self.reserve_error is not None:
            raise self.reserve_error
        return self.reservation

    def finalize_export_artifact(self, reservation, **values: object):
        del reservation
        consistency_check = values["consistency_check"]
        assert callable(consistency_check)
        consistency_check()
        if self.after_consistency is not None:
            self.after_consistency()
        if self.finalize_error is not None:
            raise self.finalize_error
        return self.ready_snapshot

    def read_export_artifact(self, export_artifact_id):
        del export_artifact_id
        if self.read_error is not None:
            raise self.read_error
        return self.read_snapshot

    def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_error_on_call == self.commit_calls:
            raise RuntimeError("commit outcome unknown")

    def rollback(self) -> None:
        self.rollback_calls += 1


def _repository_factory(
    *repositories: ScriptedReservationRepository,
):
    remaining = iter(repositories)

    @contextmanager
    def factory() -> Iterator[ScriptedReservationRepository]:
        yield next(remaining)

    return factory


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


def _reservation_and_snapshot(request, *, status, digest: str):
    reservation = application.ArtifactReservation(
        export_artifact_id=request.export_artifact_id,
        job_id=request.job_id,
        verification_run_id=request.verification_run_id,
        review_revision_id=request.review_revision_id,
        source_version=request.source_version,
        file_type=request.file_type,
        file_name=request.file_name,
        media_type=request.media_type,
        storage_key=request.storage_key,
        size_bytes=len(request.data),
        content_sha256=digest,
        status=application.ArtifactLifecycleStatus.PENDING,
        reserved_at=request.created_at,
        created_at=request.created_at,
    )
    snapshot_values = asdict(reservation)
    snapshot_values.update(
        status=status,
        ready_at=(
            request.created_at
            if status is application.ArtifactLifecycleStatus.READY
            else None
        ),
    )
    snapshot = application.ArtifactSnapshot(**snapshot_values)
    return reservation, snapshot


def _scripted_repository(
    request,
    *,
    reserve_error: Exception | None = None,
    finalize_error: Exception | None = None,
    after_consistency: Callable[[], None] | None = None,
    commit_error_on_call: int | None = None,
    read_status=None,
    read_digest: str | None = None,
):
    digest = sha256(request.data).hexdigest()
    reservation, ready = _reservation_and_snapshot(
        request,
        status=application.ArtifactLifecycleStatus.READY,
        digest=digest,
    )
    read_snapshot = None
    if read_status is not None:
        _, read_snapshot = _reservation_and_snapshot(
            request,
            status=read_status,
            digest=read_digest or digest,
        )
    return ScriptedReservationRepository(
        reservation=reservation,
        ready_snapshot=ready,
        reserve_error=reserve_error,
        finalize_error=finalize_error,
        after_consistency=after_consistency,
        commit_error_on_call=commit_error_on_call,
        read_snapshot=read_snapshot,
    )


def test_artifact_service_reserves_publishes_finalizes_and_commits(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    repository = _scripted_repository(request)
    service = application.ArtifactPersistenceService(
        storage,
        _repository_factory(repository, repository),
    )

    result = service.persist(request)

    assert result.export_artifact_id == request.export_artifact_id
    assert result.storage_key == request.storage_key
    assert result.path.read_bytes() == request.data
    assert result.size_bytes == len(request.data)
    assert len(result.content_sha256) == 64
    assert result.created is True
    assert repository.commit_calls == 2
    assert repository.rollback_calls == 0


@pytest.mark.parametrize(
    "error",
    [
        ValueError("artifact does not belong to job"),
        ValueError("source version does not match"),
        ValueError("storage key is already persisted"),
    ],
)
def test_reservation_rejection_occurs_before_filesystem_publication(
    tmp_path: Path,
    error: Exception,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    repository = _scripted_repository(request, reserve_error=error)

    with pytest.raises(ValueError, match=str(error)):
        application.ArtifactPersistenceService(
            storage,
            _repository_factory(repository),
        ).persist(request)

    assert not (tmp_path / request.storage_key).exists()
    assert repository.rollback_calls == 1


def test_finalize_failure_compensates_new_file_but_keeps_pending_reservation(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    repository = _scripted_repository(
        request,
        finalize_error=ValueError("finalize conflict"),
    )

    with pytest.raises(ValueError, match="finalize conflict"):
        application.ArtifactPersistenceService(
            storage,
            _repository_factory(repository, repository),
        ).persist(request)

    assert not (tmp_path / request.storage_key).exists()
    assert repository.commit_calls == 1
    assert repository.rollback_calls == 1


def test_finalize_failure_does_not_delete_preexisting_idempotent_file(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    with storage.publish_verified_artifact(
        request.job_id,
        request.export_artifact_id,
        request.storage_key,
        request.file_type,
        request.data,
    ):
        pass
    repository = _scripted_repository(
        request,
        finalize_error=ValueError("finalize conflict"),
    )

    with pytest.raises(ValueError, match="finalize conflict"):
        application.ArtifactPersistenceService(
            storage,
            _repository_factory(repository, repository),
        ).persist(request)

    assert (tmp_path / request.storage_key).read_bytes() == request.data


def test_finalize_commit_succeeded_then_raised_is_proven_ready(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    primary = _scripted_repository(request, commit_error_on_call=2)
    fresh = _scripted_repository(
        request,
        read_status=application.ArtifactLifecycleStatus.READY,
    )

    result = application.ArtifactPersistenceService(
        storage,
        _repository_factory(primary, primary, fresh),
    ).persist(request)

    assert result.storage_key == request.storage_key
    assert result.path.read_bytes() == request.data
    assert primary.rollback_calls == 1


def test_finalize_commit_failed_before_commit_compensates_pending(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    primary = _scripted_repository(request, commit_error_on_call=2)
    fresh = _scripted_repository(
        request,
        read_status=application.ArtifactLifecycleStatus.PENDING,
    )

    with pytest.raises(RuntimeError, match="commit outcome unknown"):
        application.ArtifactPersistenceService(
            storage,
            _repository_factory(primary, primary, fresh),
        ).persist(request)

    assert not (tmp_path / request.storage_key).exists()
    assert fresh.read_snapshot is not None
    assert (
        fresh.read_snapshot.status
        is application.ArtifactLifecycleStatus.PENDING
    )


def test_unprovable_finalize_commit_retains_file_and_reservation(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    primary = _scripted_repository(request, commit_error_on_call=2)
    fresh = _scripted_repository(
        request,
        read_status=application.ArtifactLifecycleStatus.READY,
        read_digest="0" * 64,
    )

    with pytest.raises(application.ArtifactReconciliationRequiredError):
        application.ArtifactPersistenceService(
            storage,
            _repository_factory(primary, primary, fresh),
        ).persist(request)

    assert (tmp_path / request.storage_key).read_bytes() == request.data
    assert fresh.read_snapshot is not None


def test_failed_outcome_probe_raises_typed_reconciliation_error(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    primary = _scripted_repository(request, commit_error_on_call=2)
    fresh = _scripted_repository(request)
    fresh.read_error = RuntimeError("database unavailable")

    with pytest.raises(application.ArtifactReconciliationRequiredError):
        application.ArtifactPersistenceService(
            storage,
            _repository_factory(primary, primary, fresh),
        ).persist(request)

    assert (tmp_path / request.storage_key).read_bytes() == request.data


def test_entry_changed_after_hash_is_retained_for_reconciliation(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    artifact_path = tmp_path / request.storage_key
    repository = _scripted_repository(
        request,
        finalize_error=ValueError("finalize failed"),
        after_consistency=lambda: artifact_path.write_bytes(b"changed"),
    )

    with pytest.raises(application.ArtifactReconciliationRequiredError):
        application.ArtifactPersistenceService(
            storage,
            _repository_factory(repository, repository),
        ).persist(request)

    assert artifact_path.read_bytes() == b"changed"


@dataclass
class PendingReconciliationRepository:
    pending: application.ArtifactSnapshot
    refresh_before_stale_action: bool = False
    before_missing_check: Callable[[], None] | None = None
    finalized: bool = False
    deleted: bool = False
    commit_calls: int = 0
    rollback_calls: int = 0
    stale_finalize_calls: int = 0
    stale_delete_calls: int = 0
    missing_check_calls: int = 0

    def list_stale_pending_artifacts(self, older_than):
        del older_than
        return () if self.deleted or self.finalized else (self.pending,)

    def finalize_export_artifact(self, reservation, **values):
        del reservation
        self._refresh_if_requested()
        values["consistency_check"]()
        self.finalized = True
        snapshot_values = asdict(self.pending)
        snapshot_values.update(
            status=application.ArtifactLifecycleStatus.READY,
            ready_at=values["ready_at"],
        )
        return application.ArtifactSnapshot(**snapshot_values)

    def delete_pending_export_artifact(self, **values):
        assert values["export_artifact_id"] == self.pending.export_artifact_id
        self.deleted = True
        return True

    def finalize_stale_pending_export_artifact(self, reservation, **values):
        self.stale_finalize_calls += 1
        self._refresh_if_requested()
        if self.pending.reserved_at != reservation.reserved_at:
            return None
        values["consistency_check"]()
        self.finalized = True
        self.pending = replace(
            self.pending,
            status=application.ArtifactLifecycleStatus.READY,
            ready_at=values["ready_at"],
        )
        return self.pending

    def delete_stale_pending_export_artifact(self, reservation, *, missing_check):
        self.stale_delete_calls += 1
        self._refresh_if_requested()
        if self.pending.reserved_at != reservation.reserved_at:
            return False
        if self.before_missing_check is not None:
            self.before_missing_check()
        self.missing_check_calls += 1
        if not missing_check():
            return False
        self.deleted = True
        return True

    def read_export_artifact(self, export_artifact_id):
        del export_artifact_id
        return self.pending

    def commit(self):
        self.commit_calls += 1

    def rollback(self):
        self.rollback_calls += 1

    def _refresh_if_requested(self) -> None:
        if self.refresh_before_stale_action:
            self.pending = replace(
                self.pending,
                reserved_at=self.pending.reserved_at + timedelta(minutes=1),
            )


def test_stale_pending_reconciliation_finalizes_matching_file(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    digest = sha256(request.data).hexdigest()
    _, pending = _reservation_and_snapshot(
        request,
        status=application.ArtifactLifecycleStatus.PENDING,
        digest=digest,
    )
    with storage.publish_verified_artifact(
        request.job_id,
        request.export_artifact_id,
        request.storage_key,
        request.file_type,
        request.data,
    ):
        pass
    repository = PendingReconciliationRepository(pending)

    result = application.ArtifactPendingReconciliationService(
        storage,
        _repository_factory(repository, repository),
    ).reconcile_before(datetime(2026, 9, 1, 4, 30, tzinfo=UTC))

    assert result.ready_artifact_ids == (request.export_artifact_id,)
    assert repository.finalized is True
    assert repository.stale_finalize_calls == 1
    assert repository.deleted is False
    assert (tmp_path / request.storage_key).exists()


def test_stale_pending_reconciliation_deletes_missing_reservation(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    digest = sha256(request.data).hexdigest()
    _, pending = _reservation_and_snapshot(
        request,
        status=application.ArtifactLifecycleStatus.PENDING,
        digest=digest,
    )
    repository = PendingReconciliationRepository(pending)

    result = application.ArtifactPendingReconciliationService(
        storage,
        _repository_factory(repository, repository),
    ).reconcile_before(datetime(2026, 9, 1, 4, 30, tzinfo=UTC))

    assert result.deleted_artifact_ids == (request.export_artifact_id,)
    assert repository.deleted is True
    assert repository.stale_delete_calls == 1
    assert repository.missing_check_calls == 1
    assert repository.finalized is False


def test_stale_pending_reconciliation_skips_refreshed_missing_reservation(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    digest = sha256(request.data).hexdigest()
    _, pending = _reservation_and_snapshot(
        request,
        status=application.ArtifactLifecycleStatus.PENDING,
        digest=digest,
    )
    repository = PendingReconciliationRepository(
        pending,
        refresh_before_stale_action=True,
    )

    result = application.ArtifactPendingReconciliationService(
        storage,
        _repository_factory(repository, repository),
    ).reconcile_before(datetime(2026, 9, 1, 4, 30, tzinfo=UTC))

    assert result.deleted_artifact_ids == ()
    assert repository.deleted is False
    assert repository.stale_delete_calls == 1
    assert repository.missing_check_calls == 0
    assert repository.pending.reserved_at == pending.reserved_at + timedelta(minutes=1)


def test_stale_pending_reconciliation_skips_refreshed_matching_reservation(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    digest = sha256(request.data).hexdigest()
    _, pending = _reservation_and_snapshot(
        request,
        status=application.ArtifactLifecycleStatus.PENDING,
        digest=digest,
    )
    with storage.publish_verified_artifact(
        request.job_id,
        request.export_artifact_id,
        request.storage_key,
        request.file_type,
        request.data,
    ):
        pass
    repository = PendingReconciliationRepository(
        pending,
        refresh_before_stale_action=True,
    )

    result = application.ArtifactPendingReconciliationService(
        storage,
        _repository_factory(repository, repository),
    ).reconcile_before(datetime(2026, 9, 1, 4, 30, tzinfo=UTC))

    assert result.ready_artifact_ids == ()
    assert repository.finalized is False
    assert repository.stale_finalize_calls == 1
    assert repository.pending.reserved_at == pending.reserved_at + timedelta(minutes=1)


def test_stale_pending_reconciliation_rechecks_missing_file_under_row_lock(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    digest = sha256(request.data).hexdigest()
    _, pending = _reservation_and_snapshot(
        request,
        status=application.ArtifactLifecycleStatus.PENDING,
        digest=digest,
    )

    def publish_after_initial_missing_check() -> None:
        with storage.publish_verified_artifact(
            request.job_id,
            request.export_artifact_id,
            request.storage_key,
            request.file_type,
            request.data,
        ):
            pass

    repository = PendingReconciliationRepository(
        pending,
        before_missing_check=publish_after_initial_missing_check,
    )

    result = application.ArtifactPendingReconciliationService(
        storage,
        _repository_factory(repository, repository),
    ).reconcile_before(datetime(2026, 9, 1, 4, 30, tzinfo=UTC))

    assert result.deleted_artifact_ids == ()
    assert repository.deleted is False
    assert repository.stale_delete_calls == 1
    assert repository.missing_check_calls == 1
    assert (tmp_path / request.storage_key).read_bytes() == request.data


@dataclass
class OrphanSweepRepository:
    referenced_storage_keys: set[str] = field(default_factory=set)
    committed: int = 0
    rolled_back: int = 0
    deleted_storage_keys: list[str] = field(default_factory=list)

    def delete_unreferenced_artifact(
        self,
        *,
        job_id,
        artifact_id,
        file_type,
        storage_key,
        candidate_storage_key,
        delete_path,
    ):
        del job_id, artifact_id, file_type, storage_key
        if candidate_storage_key in self.referenced_storage_keys:
            return False
        deleted = delete_path(True)
        if deleted:
            self.deleted_storage_keys.append(candidate_storage_key)
        return deleted

    def commit(self) -> None:
        self.committed += 1

    def rollback(self) -> None:
        self.rolled_back += 1


def _publish_stale_orphan(
    storage: JobStorage,
    request: application.ArtifactPersistenceRequest,
    *,
    older_than: datetime,
) -> Path:
    with storage.publish_verified_artifact(
        request.job_id,
        request.export_artifact_id,
        request.storage_key,
        request.file_type,
        request.data,
    ) as handle:
        path = handle.path
    stale_timestamp = (older_than - timedelta(seconds=1)).timestamp()
    os.utime(path, (stale_timestamp, stale_timestamp))
    return path


def test_orphan_sweep_skips_stale_file_reserved_before_candidate_deletion(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    cutoff = request.created_at + timedelta(hours=1)
    path = _publish_stale_orphan(storage, request, older_than=cutoff)
    repository = OrphanSweepRepository({request.storage_key})

    result = application.ArtifactOrphanCleanupService(
        storage,
        _repository_factory(repository),
    ).sweep_before(cutoff)

    assert result.deleted_storage_keys == ()
    assert result.deferred_storage_keys == ()
    assert path.read_bytes() == request.data
    assert repository.deleted_storage_keys == []


def test_orphan_sweep_deletes_before_reservation_then_later_publication_succeeds(
    tmp_path: Path,
) -> None:
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    request = _request()
    cutoff = request.created_at + timedelta(hours=1)
    path = _publish_stale_orphan(storage, request, older_than=cutoff)
    cleanup_repository = OrphanSweepRepository()

    cleanup = application.ArtifactOrphanCleanupService(
        storage,
        _repository_factory(cleanup_repository),
    ).sweep_before(cutoff)

    assert cleanup.deleted_storage_keys == (request.storage_key,)
    assert not path.exists()

    persistence_repository = _scripted_repository(request)
    persisted = application.ArtifactPersistenceService(
        storage,
        _repository_factory(persistence_repository, persistence_repository),
    ).persist(request)

    assert persisted.created is True
    assert path.read_bytes() == request.data
