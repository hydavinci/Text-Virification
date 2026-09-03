from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from text_verification.domain.artifacts import (
    ArtifactLifecycleStatus,
    ArtifactReservation,
    ArtifactSnapshot,
)
from text_verification.domain.documents import DocumentMetadata, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import (
    RESULT_READY_STATUSES,
    TERMINAL_STATUSES,
    JobLeaseLostError,
    JobStateConflictError,
    JobStatus,
    JobUnleasedError,
    TerminalJobStateError,
)
from text_verification.domain.verification import (
    DocumentRevisionKind,
    PersistedDocumentRevision,
    ReviewRevisionDraft,
    Scenario,
    VerificationAnalysisMode,
    VerificationDegradation,
    VerificationExecutionMode,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)
from text_verification.infrastructure.orm import (
    DocumentBlockRow,
    DocumentRow,
    ExportArtifactRow,
    JobRow,
    ReviewRevisionRow,
    VerificationIssueRow,
    VerificationRunRow,
)
from text_verification.infrastructure.storage import (
    validate_artifact_identity,
    validate_artifact_storage_key,
)


class JobResultState(StrEnum):
    MISSING = "missing"
    PENDING = "pending"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    EXPIRED = "expired"


@dataclass(frozen=True)
class JobResultSnapshot:
    state: JobResultState
    result: VerificationResult | None


class VerificationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_result(self, job_id: UUID, result: VerificationResult) -> None:
        job = self._lock_job(job_id)
        self._save_result_for_job(job, result)

    def save_claimed_result(
        self,
        job_id: UUID,
        result: VerificationResult,
        *,
        owner_token: UUID,
        expected_status: JobStatus,
        now: datetime,
    ) -> None:
        if expected_status is not JobStatus.CHECKING_ENGLISH:
            raise ValueError(
                "Claimed results may only persist from checking_english."
            )
        job = self._lock_job(job_id)
        self._assert_active_lease(job, owner_token, now)
        self._assert_expected_status(job, expected_status)
        self._save_result_for_job(job, result)

    def _save_result_for_job(
        self,
        job: JobRow,
        result: VerificationResult,
    ) -> None:
        job_id = job.job_id
        self._validate_job_source(job, result)

        existing = self._get_run_row_for_job(job_id)
        if existing is not None:
            if (
                existing.verification_run_id != result.verification_run_id
                or existing.document_id != result.document_id
            ):
                raise ValueError(f"Job {job_id} already has a different verification result.")
            if _map_rows_to_result(existing.document, existing) != result:
                raise ValueError(
                    f"Verification run {result.verification_run_id} is already persisted "
                    "with different canonical data."
                )
            return

        document_row, run_row = _map_result_to_rows(job_id, result)
        try:
            with self._session.begin_nested():
                self._session.add_all([document_row, run_row])
                self._session.flush()
        except IntegrityError as error:
            raise ValueError(
                f"Verification result for job {job_id} conflicts with existing data."
            ) from error

    def get_result_for_job(self, job_id: UUID) -> VerificationResult | None:
        row = self._get_run_row_for_job(job_id)
        if row is None:
            return None
        return _map_rows_to_result(row.document, row)

    def get_result_for_claimed_job(
        self,
        job_id: UUID,
        *,
        owner_token: UUID,
        now: datetime,
    ) -> VerificationResult | None:
        job = self._lock_job(job_id)
        self._assert_active_lease(job, owner_token, now)
        return self.get_result_for_job(job_id)

    def read_result_snapshot(self, job_id: UUID) -> JobResultSnapshot:
        job = self._session.execute(
            select(JobRow)
            .where(JobRow.job_id == job_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if job is None:
            return JobResultSnapshot(JobResultState.MISSING, None)

        job_status = JobStatus(job.status)
        if job_status is JobStatus.EXPIRED:
            return JobResultSnapshot(JobResultState.EXPIRED, None)
        if job_status not in RESULT_READY_STATUSES:
            state = (
                JobResultState.UNAVAILABLE
                if job_status in TERMINAL_STATUSES
                else JobResultState.PENDING
            )
            return JobResultSnapshot(state, None)

        result = self.get_result_for_job(job_id)
        if result is None:
            return JobResultSnapshot(JobResultState.UNAVAILABLE, None)
        return JobResultSnapshot(JobResultState.READY, result)

    def delete_results_for_jobs(self, job_ids: list[UUID]) -> None:
        if not job_ids:
            return
        self._session.execute(
            delete(DocumentRow)
            .where(DocumentRow.job_id.in_(job_ids))
            .execution_options(synchronize_session=False)
        )

    def list_artifact_storage_keys(self, job_id: UUID) -> tuple[str, ...]:
        return tuple(
            self._session.scalars(
                select(ExportArtifactRow.storage_key)
                .join(
                    VerificationRunRow,
                    ExportArtifactRow.verification_run_id
                    == VerificationRunRow.verification_run_id,
                )
                .where(VerificationRunRow.job_id == job_id)
                .order_by(ExportArtifactRow.storage_key)
            ).all()
        )

    def list_all_artifact_storage_keys(self) -> tuple[str, ...]:
        return tuple(
            self._session.scalars(
                select(ExportArtifactRow.storage_key).order_by(
                    ExportArtifactRow.storage_key
                )
            ).all()
        )

    def save_review_revision(
        self,
        *,
        review_revision_id: UUID,
        verification_run_id: UUID,
        source_version: str,
        revision_number: int,
        text: str,
        created_at: datetime,
    ) -> None:
        if revision_number < 1:
            raise ValueError("revision_number must be greater than zero.")
        run = self._lock_run(verification_run_id)
        if source_version != run.document.source_version:
            raise ValueError(
                f"Review source version {source_version!r} does not match "
                f"{run.document.source_version!r}."
            )
        existing = self._session.get(ReviewRevisionRow, review_revision_id)
        values = (
            verification_run_id,
            run.document_id,
            source_version,
            revision_number,
            text,
            created_at,
        )
        if existing is not None:
            persisted = (
                existing.verification_run_id,
                existing.document_id,
                existing.source_version,
                existing.revision_number,
                existing.text,
                existing.created_at,
            )
            if persisted != values:
                raise ValueError(
                    f"Review revision {review_revision_id} is already persisted "
                    "with different data."
                )
            return

        conflicting_revision = self._session.scalar(
            select(ReviewRevisionRow.review_revision_id).where(
                ReviewRevisionRow.verification_run_id == verification_run_id,
                ReviewRevisionRow.revision_number == revision_number,
            )
        )
        if conflicting_revision is not None:
            raise ValueError(
                f"Verification run {verification_run_id} already has review revision "
                f"number {revision_number}."
            )

        try:
            with self._session.begin_nested():
                self._session.add(
                    ReviewRevisionRow(
                        review_revision_id=review_revision_id,
                        verification_run_id=verification_run_id,
                        document_id=run.document_id,
                        source_version=source_version,
                        revision_number=revision_number,
                        parent_revision_id=None,
                        kind=DocumentRevisionKind.REVIEW.value,
                        text=text,
                        created_at=created_at,
                    )
                )
                self._session.flush()
        except IntegrityError as error:
            raise ValueError(
                f"Review revision {review_revision_id} conflicts with existing data."
            ) from error

    def persist_review_revision(
        self,
        job_id: UUID,
        draft: ReviewRevisionDraft,
        *,
        created_at: datetime,
    ) -> PersistedDocumentRevision:
        run = self._lock_run(draft.verification_run_id)
        if run.job_id != job_id:
            raise ValueError(
                f"Verification run {draft.verification_run_id} does not belong "
                f"to requested job {job_id}."
            )
        if run.document_id != draft.document_id:
            raise ValueError(
                f"Review document {draft.document_id} does not match "
                f"{run.document_id}."
            )
        if run.document.source_version != draft.source_version:
            raise ValueError(
                f"Review source version {draft.source_version!r} does not match "
                f"{run.document.source_version!r}."
            )

        existing = self._session.scalar(
            select(ReviewRevisionRow)
            .where(ReviewRevisionRow.review_revision_id == draft.revision_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if existing is not None:
            persisted = _persisted_revision_from_row(existing)
            if _revision_draft_identity(persisted) != draft:
                raise ValueError(
                    f"Review revision {draft.revision_id} is already persisted "
                    "with different data."
                )
            return persisted

        latest = self._session.scalar(
            select(ReviewRevisionRow)
            .where(
                ReviewRevisionRow.verification_run_id
                == draft.verification_run_id
            )
            .order_by(ReviewRevisionRow.revision_number.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        if latest is None:
            if draft.parent_revision_id is not None:
                parent = self._session.get(
                    ReviewRevisionRow,
                    draft.parent_revision_id,
                )
                if parent is None:
                    raise LookupError(
                        f"Parent revision {draft.parent_revision_id} does not exist."
                    )
                raise ValueError(
                    f"Parent revision {draft.parent_revision_id} does not belong "
                    f"to verification run {draft.verification_run_id}."
                )
            revision_number = 1
        else:
            if draft.parent_revision_id != latest.review_revision_id:
                raise ValueError(
                    "Revision parent must be the latest persisted revision "
                    f"{latest.review_revision_id}."
                )
            if (
                latest.document_id != draft.document_id
                or latest.source_version != draft.source_version
            ):
                raise ValueError("Parent revision identity is not canonical.")
            revision_number = latest.revision_number + 1

        row = ReviewRevisionRow(
            review_revision_id=draft.revision_id,
            verification_run_id=draft.verification_run_id,
            document_id=draft.document_id,
            source_version=draft.source_version,
            revision_number=revision_number,
            parent_revision_id=draft.parent_revision_id,
            kind=draft.kind.value,
            text=draft.text,
            created_at=created_at,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as error:
            raise ValueError(
                f"Review revision {draft.revision_id} conflicts with existing data."
            ) from error
        return _persisted_revision_from_row(row)

    def read_review_revision(
        self,
        review_revision_id: UUID,
    ) -> PersistedDocumentRevision | None:
        row = self._session.get(ReviewRevisionRow, review_revision_id)
        return None if row is None else _persisted_revision_from_row(row)

    def reserve_export_artifact(
        self,
        *,
        export_artifact_id: UUID,
        verification_run_id: UUID,
        review_revision_id: UUID | None,
        source_version: str,
        file_type: FileType | str,
        file_name: str,
        media_type: str,
        storage_key: str,
        size_bytes: int,
        content_sha256: str,
        reserved_at: datetime,
        created_at: datetime,
    ) -> ArtifactReservation:
        if size_bytes < 0:
            raise ValueError("Artifact size must be greater than or equal to zero.")
        _validate_sha256(content_sha256)
        normalized_file_type = FileType(file_type)
        run = self._lock_run(verification_run_id)
        job = self._lock_job(run.job_id)
        if JobStatus(job.status) is JobStatus.EXPIRED:
            raise ValueError(f"Job {job.job_id} has expired.")
        validate_artifact_identity(
            job.job_id,
            export_artifact_id,
            normalized_file_type,
            storage_key,
        )
        review_revision = self._review_revision_for_run(
            verification_run_id,
            review_revision_id,
        )
        expected_source_version = (
            review_revision.source_version
            if review_revision is not None
            else run.document.source_version
        )
        if source_version != expected_source_version:
            raise ValueError(
                f"Export source version {source_version!r} does not match "
                f"{expected_source_version!r}."
            )

        values = (
            verification_run_id,
            review_revision_id,
            source_version,
            normalized_file_type.value,
            file_name,
            media_type,
            storage_key,
            size_bytes,
            content_sha256,
            created_at,
        )
        existing = self._lock_artifact_or_none(export_artifact_id)
        if existing is not None:
            persisted = (
                existing.verification_run_id,
                existing.review_revision_id,
                existing.source_version,
                existing.file_type,
                existing.file_name,
                existing.media_type,
                existing.storage_key,
                existing.size_bytes,
                existing.content_sha256,
                existing.created_at,
            )
            persisted_without_digest = persisted[:8] + persisted[9:]
            values_without_digest = values[:8] + values[9:]
            if persisted_without_digest != values_without_digest:
                raise ValueError(
                    f"Export artifact {export_artifact_id} is already persisted "
                    "with different data."
                )
            if (
                existing.content_sha256 is not None
                and existing.content_sha256 != content_sha256
            ):
                raise ValueError(
                    f"Export artifact {export_artifact_id} is already reserved "
                    "with different content."
                )
            if (
                ArtifactLifecycleStatus(existing.status)
                is ArtifactLifecycleStatus.PENDING
            ):
                existing.reserved_at = reserved_at
                self._session.flush()
            return _artifact_reservation_from_row(
                existing,
                expected_content_sha256=content_sha256,
            )

        conflicting_storage_key = self._session.scalar(
            select(ExportArtifactRow.export_artifact_id).where(
                ExportArtifactRow.storage_key == storage_key
            )
        )
        if conflicting_storage_key is not None:
            raise ValueError(f"Export storage key {storage_key!r} is already persisted.")

        try:
            with self._session.begin_nested():
                self._session.add(
                    ExportArtifactRow(
                        export_artifact_id=export_artifact_id,
                        verification_run_id=verification_run_id,
                        review_revision_id=review_revision_id,
                        source_version=source_version,
                        file_type=normalized_file_type.value,
                        file_name=file_name,
                        media_type=media_type,
                        storage_key=storage_key,
                        size_bytes=size_bytes,
                        content_sha256=content_sha256,
                        status=ArtifactLifecycleStatus.PENDING.value,
                        reserved_at=reserved_at,
                        ready_at=None,
                        created_at=created_at,
                    )
                )
                self._session.flush()
        except IntegrityError as error:
            raise ValueError(
                f"Export artifact {export_artifact_id} conflicts with existing data."
            ) from error
        row = self._session.get(ExportArtifactRow, export_artifact_id)
        if row is None:
            raise AssertionError("reserved artifact row was not persisted")
        return _artifact_reservation_from_row(
            row,
            expected_content_sha256=content_sha256,
        )

    def finalize_export_artifact(
        self,
        reservation: ArtifactReservation,
        *,
        ready_at: datetime,
        consistency_check: Callable[[], None],
        require_current_result: bool = False,
    ) -> ArtifactSnapshot | None:
        run = self._lock_run(reservation.verification_run_id)
        if run.job_id != reservation.job_id:
            raise ValueError("Artifact reservation does not belong to the requested job.")
        job = self._lock_job(run.job_id)
        row = self._lock_artifact_or_none(reservation.export_artifact_id)
        if row is None:
            return None
        if require_current_result and not _artifact_finalization_is_authorized(
            job,
            run,
            row,
            reservation,
            ready_at,
        ):
            if (
                ArtifactLifecycleStatus(row.status)
                is ArtifactLifecycleStatus.PENDING
                and _artifact_row_matches_reservation(row, reservation)
            ):
                self._session.delete(row)
                self._session.flush()
            return None
        _assert_artifact_row_matches_reservation(row, reservation)
        consistency_check()
        snapshot = _finalize_artifact_row(row, reservation, ready_at)
        self._session.flush()
        return snapshot

    def begin_export_artifact_repair(
        self,
        expected: ArtifactReservation,
        *,
        consistency_check: Callable[[], bool | None],
    ) -> ArtifactReservation | None:
        run = self._lock_run(expected.verification_run_id)
        job = self._lock_job(run.job_id)
        if job.job_id != expected.job_id:
            raise ValueError("Artifact repair does not belong to the requested job.")
        if JobStatus(job.status) not in RESULT_READY_STATUSES:
            raise ValueError("Artifact repair requires a result-ready job.")
        row = self._lock_artifact_or_none(expected.export_artifact_id)
        if row is None:
            return None
        if not _artifact_row_matches_repair(row, expected):
            raise ValueError(
                f"Export artifact {expected.export_artifact_id} cannot be repaired "
                "with different canonical metadata."
            )
        repair_state = consistency_check()
        if (
            repair_state is not False
            or ArtifactLifecycleStatus(row.status) is ArtifactLifecycleStatus.PENDING
        ):
            row.status = ArtifactLifecycleStatus.PENDING.value
            row.reserved_at = expected.reserved_at
            row.ready_at = None
            self._session.flush()
        return _artifact_reservation_from_row(
            row,
            expected_content_sha256=expected.content_sha256,
        )

    def finalize_stale_pending_export_artifact(
        self,
        reservation: ArtifactReservation,
        *,
        ready_at: datetime,
        consistency_check: Callable[[], None],
    ) -> ArtifactSnapshot | None:
        run = self._lock_run(reservation.verification_run_id)
        if run.job_id != reservation.job_id:
            raise ValueError("Artifact reservation does not belong to the requested job.")
        self._lock_job(run.job_id)
        row = self._lock_artifact_or_none(reservation.export_artifact_id)
        if row is None or not _pending_artifact_row_matches_reservation(
            row,
            reservation,
        ):
            return None
        consistency_check()
        snapshot = _finalize_artifact_row(row, reservation, ready_at)
        self._session.flush()
        return snapshot

    def read_export_artifact(
        self,
        export_artifact_id: UUID,
    ) -> ArtifactSnapshot | None:
        row = self._session.get(ExportArtifactRow, export_artifact_id)
        return None if row is None else _artifact_snapshot_from_row(row)

    def delete_stale_pending_export_artifact(
        self,
        reservation: ArtifactReservation,
        *,
        missing_check: Callable[[], bool],
    ) -> bool:
        run = self._lock_run(reservation.verification_run_id)
        if run.job_id != reservation.job_id:
            raise ValueError("Artifact reservation does not belong to the requested job.")
        self._lock_job(run.job_id)
        row = self._lock_artifact_or_none(reservation.export_artifact_id)
        if row is None or not _pending_artifact_row_matches_reservation(
            row,
            reservation,
        ):
            return False
        if not missing_check():
            return False
        self._session.delete(row)
        self._session.flush()
        return True

    def delete_unreferenced_artifact(
        self,
        *,
        job_id: UUID,
        artifact_id: UUID,
        file_type: FileType | str,
        storage_key: str,
        candidate_storage_key: str,
        delete_path: Callable[[bool], bool],
    ) -> bool:
        validate_artifact_identity(
            job_id,
            artifact_id,
            file_type,
            storage_key,
        )
        validate_artifact_storage_key(job_id, candidate_storage_key)
        job = self._lock_job_or_none(job_id)
        if job is None:
            return delete_path(True)
        if candidate_storage_key != storage_key:
            canonical = self._session.scalar(
                select(ExportArtifactRow)
                .where(ExportArtifactRow.storage_key == storage_key)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if canonical is not None:
                if (
                    ArtifactLifecycleStatus(canonical.status)
                    is ArtifactLifecycleStatus.PENDING
                ):
                    return False
                return delete_path(False)
        referenced = self._session.scalar(
            select(ExportArtifactRow.export_artifact_id)
            .where(
                ExportArtifactRow.storage_key == candidate_storage_key,
                ExportArtifactRow.status.in_(
                    (
                        ArtifactLifecycleStatus.PENDING.value,
                        ArtifactLifecycleStatus.READY.value,
                    )
                ),
            )
            .limit(1)
        )
        if referenced is not None:
            return False
        any_job_artifact = self._session.scalar(
            select(ExportArtifactRow.export_artifact_id)
            .join(
                VerificationRunRow,
                ExportArtifactRow.verification_run_id
                == VerificationRunRow.verification_run_id,
            )
            .where(VerificationRunRow.job_id == job.job_id)
            .limit(1)
        )
        return delete_path(any_job_artifact is None)

    def list_stale_pending_artifacts(
        self,
        older_than: datetime,
    ) -> tuple[ArtifactSnapshot, ...]:
        rows = self._session.scalars(
            select(ExportArtifactRow)
            .where(
                ExportArtifactRow.status == ArtifactLifecycleStatus.PENDING.value,
                ExportArtifactRow.reserved_at < older_than,
            )
            .order_by(
                ExportArtifactRow.reserved_at,
                ExportArtifactRow.export_artifact_id,
            )
        ).all()
        return tuple(_artifact_snapshot_from_row(row) for row in rows)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def _get_run_row_for_job(self, job_id: UUID) -> VerificationRunRow | None:
        return self._session.scalar(
            select(VerificationRunRow)
            .options(
                selectinload(VerificationRunRow.document),
                selectinload(VerificationRunRow.document).selectinload(
                    DocumentRow.blocks
                ),
                selectinload(VerificationRunRow.issues),
            )
            .where(VerificationRunRow.job_id == job_id)
            .execution_options(populate_existing=True)
        )

    def _lock_job(self, job_id: UUID) -> JobRow:
        row = self._lock_job_or_none(job_id)
        if row is None:
            raise LookupError(f"Job {job_id} does not exist.")
        return row

    def _lock_job_or_none(self, job_id: UUID) -> JobRow | None:
        return self._session.execute(
            select(JobRow)
            .where(JobRow.job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

    def _lock_run(self, verification_run_id: UUID) -> VerificationRunRow:
        row = self._session.scalar(
            select(VerificationRunRow)
            .options(selectinload(VerificationRunRow.document))
            .where(VerificationRunRow.verification_run_id == verification_run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise LookupError(f"Verification run {verification_run_id} does not exist.")
        return row

    def _lock_artifact(self, export_artifact_id: UUID) -> ExportArtifactRow:
        row = self._lock_artifact_or_none(export_artifact_id)
        if row is None:
            raise LookupError(f"Export artifact {export_artifact_id} does not exist.")
        return row

    def _lock_artifact_or_none(
        self,
        export_artifact_id: UUID,
    ) -> ExportArtifactRow | None:
        return self._session.scalar(
            select(ExportArtifactRow)
            .where(ExportArtifactRow.export_artifact_id == export_artifact_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _assert_active_lease(
        self,
        job: JobRow,
        owner_token: UUID,
        now: datetime,
    ) -> None:
        current_status = JobStatus(job.status)
        if current_status in TERMINAL_STATUSES:
            raise TerminalJobStateError(
                job_id=job.job_id,
                current_status=current_status,
                target_status=current_status,
            )
        if job.lease_owner_token is None or job.lease_expires_at is None:
            raise JobUnleasedError(job.job_id)
        if job.lease_owner_token != owner_token or job.lease_expires_at <= now:
            raise JobLeaseLostError(job.job_id, job.lease_expires_at)

    def _assert_expected_status(
        self,
        job: JobRow,
        expected_status: JobStatus,
    ) -> None:
        current_status = JobStatus(job.status)
        if current_status in TERMINAL_STATUSES:
            raise TerminalJobStateError(
                job_id=job.job_id,
                current_status=current_status,
                target_status=expected_status,
            )
        if current_status is not expected_status:
            raise JobStateConflictError(
                job_id=job.job_id,
                expected_status=expected_status,
                current_status=current_status,
            )

    def _validate_job_source(
        self,
        job: JobRow,
        result: VerificationResult,
    ) -> None:
        if job.source_name != result.source_name:
            raise ValueError(
                f"Job {job.job_id} source name {job.source_name!r} does not match "
                f"{result.source_name!r}."
            )
        try:
            job_file_type = FileType(job.file_type)
        except ValueError as error:
            raise ValueError(
                f"Job {job.job_id} file type {job.file_type!r} is not canonical."
            ) from error
        if job_file_type is not result.file_type:
            raise ValueError(
                f"Job {job.job_id} file type {job_file_type.value!r} does not match "
                f"{result.file_type.value!r}."
            )

    def _review_revision_for_run(
        self,
        verification_run_id: UUID,
        review_revision_id: UUID | None,
    ) -> ReviewRevisionRow | None:
        if review_revision_id is None:
            return None
        revision = self._session.scalar(
            select(ReviewRevisionRow)
            .where(ReviewRevisionRow.review_revision_id == review_revision_id)
            .execution_options(populate_existing=True)
        )
        if revision is None:
            raise LookupError(f"Review revision {review_revision_id} does not exist.")
        if revision.verification_run_id != verification_run_id:
            raise ValueError(
                f"Review revision {review_revision_id} does not belong to "
                f"verification run {verification_run_id}."
            )
        return revision


def _map_result_to_rows(
    job_id: UUID,
    result: VerificationResult,
    *,
    created_at: datetime | None = None,
) -> tuple[DocumentRow, VerificationRunRow]:
    persisted_at = created_at if created_at is not None else datetime.now(UTC)
    document_row = DocumentRow(
        document_id=result.document_id,
        job_id=job_id,
        source_version=result.source_version,
        source_name=result.source_name,
        file_type=result.file_type.value,
        text=result.text,
        parser_name=result.parser_name,
        parser_version=result.parser_version,
        document_metadata=result.metadata.model_dump(mode="json"),
        created_at=persisted_at,
    )
    document_row.blocks = [
        _map_block_to_row(block, block_index=index)
        for index, block in enumerate(result.blocks)
    ]
    run_row = VerificationRunRow(
        verification_run_id=result.verification_run_id,
        job_id=job_id,
        document_id=result.document_id,
        scenario=result.scenario.value,
        execution_mode=result.execution_mode.value,
        analysis_mode=result.analysis_mode.value,
        stats_char_count=result.stats.char_count,
        stats_char_count_no_space=result.stats.char_count_no_space,
        stats_line_count=result.stats.line_count,
        stats_paragraph_count=result.stats.paragraph_count,
        stats_language=result.stats.language,
        stats_primary_count=result.stats.primary_count,
        stats_primary_label=result.stats.primary_label,
        summary_total=result.summary.total,
        summary_by_type=dict(result.summary.by_type),
        summary_by_severity=dict(result.summary.by_severity),
        summary_by_rule=dict(result.summary.by_rule),
        summary_by_layer=dict(result.summary.by_layer),
        summary_llm_review=deepcopy(result.summary.llm_review),
        dictionary_versions=dict(result.dictionary_versions),
        degradation_is_degraded=result.degradation.is_degraded,
        degradation_reasons=list(result.degradation.reasons),
        created_at=persisted_at,
        document=document_row,
    )
    run_row.issues = [
        _map_issue_to_row(issue, issue_index=index)
        for index, issue in enumerate(result.issues)
    ]
    return document_row, run_row


def _persisted_revision_from_row(
    row: ReviewRevisionRow,
) -> PersistedDocumentRevision:
    return PersistedDocumentRevision(
        revision_id=row.review_revision_id,
        document_id=row.document_id,
        verification_run_id=row.verification_run_id,
        source_version=row.source_version,
        revision_number=row.revision_number,
        created_at=row.created_at,
        parent_revision_id=row.parent_revision_id,
        persistence_state="persisted",
        kind=DocumentRevisionKind(row.kind),
        text=row.text,
    )


def _revision_draft_identity(
    revision: PersistedDocumentRevision,
) -> ReviewRevisionDraft:
    return ReviewRevisionDraft(
        revision_id=revision.revision_id,
        document_id=revision.document_id,
        verification_run_id=revision.verification_run_id,
        source_version=revision.source_version,
        parent_revision_id=revision.parent_revision_id,
        kind=revision.kind,
        text=revision.text,
    )


def _map_rows_to_result(
    document_row: DocumentRow,
    run_row: VerificationRunRow,
) -> VerificationResult:
    issues = tuple(_map_issue_to_domain(issue_row) for issue_row in run_row.issues)
    return VerificationResult(
        verification_run_id=run_row.verification_run_id,
        document_id=document_row.document_id,
        source_version=document_row.source_version,
        source_name=document_row.source_name,
        file_type=FileType(document_row.file_type),
        scenario=Scenario(run_row.scenario),
        text=document_row.text,
        blocks=tuple(_map_block_to_domain(row) for row in document_row.blocks),
        parser_name=document_row.parser_name,
        parser_version=document_row.parser_version,
        metadata=DocumentMetadata.model_validate(document_row.document_metadata),
        ocr_requirement=DocumentMetadata.model_validate(
            document_row.document_metadata
        ).pdf_ocr_requirement,
        stats=VerificationStatistics(
            char_count=run_row.stats_char_count,
            char_count_no_space=run_row.stats_char_count_no_space,
            line_count=run_row.stats_line_count,
            paragraph_count=run_row.stats_paragraph_count,
            language=run_row.stats_language,
            primary_count=run_row.stats_primary_count,
            primary_label=run_row.stats_primary_label,
        ),
        issues=issues,
        summary=VerificationSummary(
            total=run_row.summary_total,
            by_type=dict(run_row.summary_by_type),
            by_severity=dict(run_row.summary_by_severity),
            by_rule=dict(run_row.summary_by_rule),
            by_layer=dict(run_row.summary_by_layer),
            llm_review=deepcopy(run_row.summary_llm_review),
        ),
        execution_mode=VerificationExecutionMode(run_row.execution_mode),
        analysis_mode=VerificationAnalysisMode(run_row.analysis_mode),
        dictionary_versions=dict(run_row.dictionary_versions),
        degradation=VerificationDegradation(
            is_degraded=run_row.degradation_is_degraded,
            reasons=tuple(run_row.degradation_reasons),
        ),
    )


def _map_block_to_row(
    block: TextBlock,
    *,
    block_index: int,
) -> DocumentBlockRow:
    return DocumentBlockRow(
        block_index=block_index,
        block_id=block.block_id,
        kind=block.kind,
        text=block.text,
        global_start=block.global_start,
        global_end=block.global_end,
        block_start=block.block_start,
        block_end=block.block_end,
        page=block.page,
        paragraph_index=block.paragraph_index,
        table_index=block.table_index,
        row_index=block.row_index,
        cell_index=block.cell_index,
        bbox=list(block.bbox) if block.bbox is not None else None,
        parent_id=block.parent_id,
        style=deepcopy(block.style),
        source_locator=deepcopy(block.source_locator),
    )


def _map_block_to_domain(row: DocumentBlockRow) -> TextBlock:
    return TextBlock(
        block_id=row.block_id,
        kind=row.kind,
        text=row.text,
        global_start=row.global_start,
        global_end=row.global_end,
        block_start=row.block_start,
        block_end=row.block_end,
        page=row.page,
        paragraph_index=row.paragraph_index,
        table_index=row.table_index,
        row_index=row.row_index,
        cell_index=row.cell_index,
        bbox=tuple(row.bbox) if row.bbox is not None else None,
        parent_id=row.parent_id,
        style=deepcopy(row.style),
        source_locator=deepcopy(row.source_locator),
    )


def _map_issue_to_row(issue: Issue, *, issue_index: int) -> VerificationIssueRow:
    return VerificationIssueRow(
        verification_run_id=issue.verification_run_id,
        document_id=issue.document_id,
        issue_id=issue.issue_id,
        issue_index=issue_index,
        block_id=issue.block_id,
        page=issue.page,
        start=issue.start,
        end=issue.end,
        block_start=issue.block_start,
        block_end=issue.block_end,
        original=issue.original,
        suggestion=issue.suggestion,
        alternatives=list(issue.alternatives),
        type=issue.type,
        severity=issue.severity.value,
        layer=issue.layer,
        message=issue.message,
        description=issue.description,
        rule_id=issue.rule_id,
        rule_version=issue.rule_version,
        source=issue.source,
        source_version=issue.source_version,
        confidence=issue.confidence,
        auto_fixable=issue.auto_fixable,
        context=issue.context,
        review=issue.review,
        review_reason=issue.review_reason,
    )


def _map_issue_to_domain(row: VerificationIssueRow) -> Issue:
    return Issue(
        issue_id=row.issue_id,
        document_id=row.document_id,
        verification_run_id=row.verification_run_id,
        block_id=row.block_id,
        page=row.page,
        start=row.start,
        end=row.end,
        block_start=row.block_start,
        block_end=row.block_end,
        original=row.original,
        suggestion=row.suggestion,
        alternatives=list(row.alternatives),
        type=row.type,
        severity=IssueSeverity(row.severity),
        layer=row.layer,
        message=row.message,
        description=row.description,
        rule_id=row.rule_id,
        rule_version=row.rule_version,
        source=row.source,
        source_version=row.source_version,
        confidence=row.confidence,
        auto_fixable=row.auto_fixable,
        context=row.context,
        review=row.review,
        review_reason=row.review_reason,
    )


def _validate_sha256(value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("Artifact content SHA-256 must be 64 lowercase hexadecimal characters.")


def _artifact_reservation_from_row(
    row: ExportArtifactRow,
    *,
    expected_content_sha256: str,
) -> ArtifactReservation:
    return ArtifactReservation(
        export_artifact_id=row.export_artifact_id,
        job_id=row.run.job_id,
        verification_run_id=row.verification_run_id,
        review_revision_id=row.review_revision_id,
        source_version=row.source_version,
        file_type=FileType(row.file_type),
        file_name=row.file_name,
        media_type=row.media_type,
        storage_key=row.storage_key,
        size_bytes=row.size_bytes,
        content_sha256=row.content_sha256 or expected_content_sha256,
        status=ArtifactLifecycleStatus(row.status),
        reserved_at=row.reserved_at,
        created_at=row.created_at,
    )


def _artifact_snapshot_from_row(row: ExportArtifactRow) -> ArtifactSnapshot:
    return ArtifactSnapshot(
        export_artifact_id=row.export_artifact_id,
        job_id=row.run.job_id,
        verification_run_id=row.verification_run_id,
        review_revision_id=row.review_revision_id,
        source_version=row.source_version,
        file_type=FileType(row.file_type),
        file_name=row.file_name,
        media_type=row.media_type,
        storage_key=row.storage_key,
        size_bytes=row.size_bytes,
        content_sha256=row.content_sha256,
        status=ArtifactLifecycleStatus(row.status),
        reserved_at=row.reserved_at,
        ready_at=row.ready_at,
        created_at=row.created_at,
    )


def _assert_artifact_row_matches_reservation(
    row: ExportArtifactRow,
    reservation: ArtifactReservation,
) -> None:
    if not _artifact_row_matches_reservation(row, reservation):
        raise ValueError(
            f"Export artifact {reservation.export_artifact_id} reservation changed."
        )


def _pending_artifact_row_matches_reservation(
    row: ExportArtifactRow,
    reservation: ArtifactReservation,
) -> bool:
    return (
        reservation.status is ArtifactLifecycleStatus.PENDING
        and _artifact_row_matches_reservation(row, reservation)
        and ArtifactLifecycleStatus(row.status) is ArtifactLifecycleStatus.PENDING
        and row.reserved_at == reservation.reserved_at
    )


def _artifact_row_matches_reservation(
    row: ExportArtifactRow,
    reservation: ArtifactReservation,
) -> bool:
    persisted = (
        row.export_artifact_id,
        row.run.job_id,
        row.verification_run_id,
        row.review_revision_id,
        row.source_version,
        row.file_type,
        row.file_name,
        row.media_type,
        row.storage_key,
        row.size_bytes,
        row.created_at,
    )
    expected = (
        reservation.export_artifact_id,
        reservation.job_id,
        reservation.verification_run_id,
        reservation.review_revision_id,
        reservation.source_version,
        reservation.file_type.value,
        reservation.file_name,
        reservation.media_type,
        reservation.storage_key,
        reservation.size_bytes,
        reservation.created_at,
    )
    return (
        persisted == expected
        and (
            row.content_sha256 is None
            or row.content_sha256 == reservation.content_sha256
        )
        )


def _artifact_row_matches_repair(
        row: ExportArtifactRow,
        expected: ArtifactReservation,
) -> bool:
        return (
            row.run.job_id == expected.job_id
            and row.verification_run_id == expected.verification_run_id
            and row.review_revision_id == expected.review_revision_id
            and row.source_version == expected.source_version
            and row.file_type == expected.file_type.value
            and row.file_name == expected.file_name
            and row.media_type == expected.media_type
            and row.storage_key == expected.storage_key
            and row.size_bytes == expected.size_bytes
            and row.content_sha256 == expected.content_sha256
            and row.created_at == expected.created_at
    )


def _finalize_artifact_row(
    row: ExportArtifactRow,
    reservation: ArtifactReservation,
    ready_at: datetime,
) -> ArtifactSnapshot:
    if row.content_sha256 is None:
        row.content_sha256 = reservation.content_sha256
    if row.content_sha256 != reservation.content_sha256:
        raise ValueError(
            f"Export artifact {reservation.export_artifact_id} has "
            "different persisted content."
        )
    row.size_bytes = reservation.size_bytes
    row.status = ArtifactLifecycleStatus.READY.value
    row.ready_at = row.ready_at or ready_at
    return _artifact_snapshot_from_row(row)


def _artifact_finalization_is_authorized(
    job: JobRow,
    current_run: VerificationRunRow,
    row: ExportArtifactRow,
    reservation: ArtifactReservation,
    now: datetime,
) -> bool:
    if (
        JobStatus(job.status) not in RESULT_READY_STATUSES
        or job.expires_at <= now
        or current_run.job_id != job.job_id
        or row.run.job_id != job.job_id
    ):
        return False
    return (
        current_run.verification_run_id == reservation.verification_run_id
        and current_run.document_id == row.run.document_id
        and current_run.document.source_version == reservation.source_version
        and row.verification_run_id == current_run.verification_run_id
    )
