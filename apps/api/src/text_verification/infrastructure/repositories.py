from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from text_verification.domain.documents import FileType
from text_verification.domain.jobs import (
    TERMINAL_STATUSES,
    JobClaimDisposition,
    JobClaimResult,
    JobEvent,
    JobLeaseLostError,
    JobRead,
    JobStateConflictError,
    JobStatus,
    TerminalJobStateError,
)
from text_verification.infrastructure.orm import JobEventRow, JobRow, VerificationRunRow

INITIAL_EVENT_MESSAGE = "作业已创建"
EXPIRED_EVENT_MESSAGE = "作业已过期"
MAX_SOURCE_NAME_LENGTH = 255
MAX_ERROR_CODE_LENGTH = 64
MAX_EVENT_MESSAGE_LENGTH = 255
CLAIMED_NEXT_STATUS = {
    JobStatus.QUEUED: JobStatus.UPLOAD_VALIDATED,
    JobStatus.UPLOAD_VALIDATED: JobStatus.PARSING,
    JobStatus.PARSING: JobStatus.CHECKING_FORMAT,
    JobStatus.CHECKING_FORMAT: JobStatus.CHECKING_SENSITIVE,
    JobStatus.CHECKING_SENSITIVE: JobStatus.CHECKING_CHINESE,
    JobStatus.CHECKING_CHINESE: JobStatus.CHECKING_ENGLISH,
}


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_job(
        self,
        *,
        job_id: UUID,
        source_name: str,
        file_type: FileType | str,
        size_bytes: int,
        storage_key: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> JobRead:
        _validate_max_length("source_name", source_name, MAX_SOURCE_NAME_LENGTH)
        normalized_file_type = FileType(file_type).value
        row = JobRow(
            job_id=job_id,
            source_name=source_name,
            file_type=normalized_file_type,
            size_bytes=size_bytes,
            storage_key=storage_key,
            status=JobStatus.QUEUED.value,
            progress=0,
            error_code=None,
            error_message=None,
            created_at=created_at,
            updated_at=created_at,
            expires_at=expires_at,
            lease_owner_token=None,
            lease_expires_at=None,
        )
        row.events.append(
            JobEventRow(
                job_id=job_id,
                sequence=1,
                status=JobStatus.QUEUED.value,
                progress=0,
                message=INITIAL_EVENT_MESSAGE,
                created_at=created_at,
            )
        )
        self._session.add(row)
        self._session.flush()
        return self._to_job_read(row)

    def get_job(self, job_id: UUID) -> JobRead | None:
        row = self._session.get(JobRow, job_id)
        if row is None:
            return None
        return self._to_job_read(row)

    def list_job_ids(self) -> set[UUID]:
        return set(self._session.scalars(select(JobRow.job_id)).all())

    def acquire_lease(
        self,
        job_id: UUID,
        *,
        owner_token: UUID,
        now: datetime,
        lease_expires_at: datetime,
        previous_owner_token: UUID | None = None,
    ) -> JobClaimResult:
        if lease_expires_at <= now:
            raise ValueError("lease_expires_at must be later than now.")

        lease_available = [
            JobRow.lease_owner_token.is_(None),
            JobRow.lease_expires_at <= now,
        ]
        if previous_owner_token is not None:
            lease_available.append(
                and_(
                    JobRow.lease_owner_token == previous_owner_token,
                    JobRow.lease_expires_at > now,
                )
            )

        row = self._session.execute(
            update(JobRow)
            .where(
                JobRow.job_id == job_id,
                JobRow.status.not_in(status.value for status in TERMINAL_STATUSES),
                or_(*lease_available),
            )
            .values(
                lease_owner_token=owner_token,
                lease_expires_at=lease_expires_at,
                updated_at=now,
            )
            .returning(JobRow)
            .execution_options(synchronize_session=False)
        ).scalar_one_or_none()
        if row is not None:
            return JobClaimResult(
                disposition=JobClaimDisposition.ACQUIRED,
                job=self._to_job_read(row),
            )

        existing = self._session.execute(
            select(JobRow)
            .where(JobRow.job_id == job_id)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if existing is None:
            return JobClaimResult(JobClaimDisposition.MISSING, None)
        disposition = (
            JobClaimDisposition.TERMINAL
            if JobStatus(existing.status) in TERMINAL_STATUSES
            else JobClaimDisposition.LEASED
        )
        return JobClaimResult(disposition, self._to_job_read(existing))

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
        _validate_max_length("message", message, MAX_EVENT_MESSAGE_LENGTH)
        _validate_max_length("error_code", error_code, MAX_ERROR_CODE_LENGTH)
        job = self._lock_job(job_id)
        current_status = JobStatus(job.status)
        if current_status in TERMINAL_STATUSES:
            raise TerminalJobStateError(
                job_id=job_id,
                current_status=current_status,
                target_status=status,
            )
        changed_at = datetime.now(UTC)
        if (
            job.lease_owner_token is not None
            and job.lease_expires_at is not None
            and job.lease_expires_at > changed_at
        ):
            raise JobLeaseLostError(job_id)
        self._apply_transition(
            job,
            status,
            progress,
            message,
            changed_at=changed_at,
            error_code=error_code,
            error_message=error_message,
            clear_lease=status in TERMINAL_STATUSES,
        )

    def transition_claimed(
        self,
        job_id: UUID,
        *,
        owner_token: UUID,
        expected_status: JobStatus,
        status: JobStatus,
        progress: int,
        message: str,
        now: datetime,
        lease_expires_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> JobRead:
        _validate_max_length("message", message, MAX_EVENT_MESSAGE_LENGTH)
        _validate_max_length("error_code", error_code, MAX_ERROR_CODE_LENGTH)
        if status in TERMINAL_STATUSES:
            raise ValueError("Use a terminal claimed-job operation for terminal states.")
        if CLAIMED_NEXT_STATUS.get(expected_status) is not status:
            raise ValueError(
                "Invalid claimed job transition "
                f"{expected_status.value} -> {status.value}."
            )
        if lease_expires_at <= now:
            raise ValueError("lease_expires_at must be later than now.")

        job = self._lock_job(job_id)
        self._assert_active_lease(job, owner_token, now)
        self._assert_expected_status(job, expected_status)
        self._apply_transition(
            job,
            status,
            progress,
            message,
            changed_at=now,
            error_code=error_code,
            error_message=error_message,
            lease_expires_at=lease_expires_at,
        )
        return self._to_job_read(job)

    def fail_claimed_job(
        self,
        job_id: UUID,
        *,
        owner_token: UUID,
        expected_status: JobStatus,
        progress: int,
        message: str,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> bool:
        _validate_max_length("message", message, MAX_EVENT_MESSAGE_LENGTH)
        _validate_max_length("error_code", error_code, MAX_ERROR_CODE_LENGTH)
        job = self._lock_job(job_id)
        self._assert_active_lease(job, owner_token, now)
        self._assert_expected_status(job, expected_status)
        if self._has_result(job_id):
            return False
        self._apply_transition(
            job,
            JobStatus.FAILED,
            progress,
            message,
            changed_at=now,
            error_code=error_code,
            error_message=error_message,
            clear_lease=True,
        )
        return True

    def complete_claimed_job(
        self,
        job_id: UUID,
        *,
        owner_token: UUID,
        expected_status: JobStatus,
        progress: int,
        message: str,
        now: datetime,
    ) -> JobRead:
        _validate_max_length("message", message, MAX_EVENT_MESSAGE_LENGTH)
        if expected_status is not JobStatus.CHECKING_ENGLISH:
            raise ValueError("Completed jobs must advance from checking_english.")
        job = self._lock_job(job_id)
        self._assert_active_lease(job, owner_token, now)
        self._assert_expected_status(job, expected_status)
        if not self._has_result(job_id):
            raise ValueError(f"Job {job_id} cannot complete without a persisted result.")
        self._apply_transition(
            job,
            JobStatus.COMPLETED,
            progress,
            message,
            changed_at=now,
            clear_lease=True,
        )
        return self._to_job_read(job)

    def list_events_after(self, job_id: UUID, after_sequence: int) -> list[JobEvent]:
        rows = self._session.scalars(
            select(JobEventRow)
            .where(
                JobEventRow.job_id == job_id,
                JobEventRow.sequence > after_sequence,
            )
            .order_by(JobEventRow.sequence)
        ).all()
        return [self._to_job_event(row) for row in rows]

    def expire_jobs_before(self, cutoff: datetime) -> list[UUID]:
        rows = self._session.scalars(
            select(JobRow)
            .where(
                JobRow.expires_at <= cutoff,
                or_(
                    JobRow.status == JobStatus.EXPIRED.value,
                    JobRow.lease_owner_token.is_(None),
                    JobRow.lease_expires_at <= cutoff,
                ),
            )
            .order_by(JobRow.expires_at, JobRow.job_id)
            .with_for_update()
        ).all()

        expired_job_ids: list[UUID] = []
        for row in rows:
            if row.status != JobStatus.EXPIRED.value:
                row.status = JobStatus.EXPIRED.value
                row.updated_at = cutoff
                row.lease_owner_token = None
                row.lease_expires_at = None
                self._session.add(
                    JobEventRow(
                        job_id=row.job_id,
                        sequence=self._next_sequence(row.job_id),
                        status=JobStatus.EXPIRED.value,
                        progress=row.progress,
                        message=EXPIRED_EVENT_MESSAGE,
                        created_at=cutoff,
                    )
                )
            expired_job_ids.append(row.job_id)

        if rows:
            self._session.flush()
        return expired_job_ids

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def _lock_job(self, job_id: UUID) -> JobRow:
        job = self._session.execute(
            select(JobRow)
            .where(JobRow.job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if job is None:
            raise LookupError(f"Job {job_id} does not exist.")
        return job

    def _next_sequence(self, job_id: UUID) -> int:
        current_max = self._session.scalar(
            select(func.max(JobEventRow.sequence)).where(JobEventRow.job_id == job_id)
        )
        return int(current_max or 0) + 1

    def _assert_active_lease(
        self,
        job: JobRow,
        owner_token: UUID,
        now: datetime,
    ) -> None:
        if (
            job.lease_owner_token != owner_token
            or job.lease_expires_at is None
            or job.lease_expires_at <= now
        ):
            raise JobLeaseLostError(job.job_id)

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

    def _has_result(self, job_id: UUID) -> bool:
        return (
            self._session.scalar(
                select(VerificationRunRow.verification_run_id).where(
                    VerificationRunRow.job_id == job_id
                )
            )
            is not None
        )

    def _apply_transition(
        self,
        job: JobRow,
        status: JobStatus,
        progress: int,
        message: str,
        *,
        changed_at: datetime,
        error_code: str | None = None,
        error_message: str | None = None,
        lease_expires_at: datetime | None = None,
        clear_lease: bool = False,
    ) -> None:
        job.status = status.value
        job.progress = progress
        job.error_code = error_code
        job.error_message = error_message
        job.updated_at = changed_at
        if clear_lease:
            job.lease_owner_token = None
            job.lease_expires_at = None
        elif lease_expires_at is not None:
            job.lease_expires_at = lease_expires_at
        self._session.add(
            JobEventRow(
                job_id=job.job_id,
                sequence=self._next_sequence(job.job_id),
                status=status.value,
                progress=progress,
                message=message,
                created_at=changed_at,
            )
        )
        self._session.flush()

    def _to_job_read(self, row: JobRow) -> JobRead:
        return JobRead(
            job_id=row.job_id,
            source_name=row.source_name,
            file_type=FileType(row.file_type),
            size_bytes=row.size_bytes,
            status=JobStatus(row.status),
            progress=row.progress,
            error_code=row.error_code,
            error_message=row.error_message,
            created_at=row.created_at,
            expires_at=row.expires_at,
        )

    def _to_job_event(self, row: JobEventRow) -> JobEvent:
        return JobEvent(
            sequence=row.sequence,
            status=JobStatus(row.status),
            progress=row.progress,
            message=row.message,
            created_at=row.created_at,
        )


def _validate_max_length(
    field_name: str,
    value: str | None,
    max_length: int,
) -> None:
    if value is not None and len(value) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters.")
