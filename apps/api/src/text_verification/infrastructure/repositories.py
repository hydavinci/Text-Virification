from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from text_verification.checkers.models import CHECK_CATEGORY_ORDER, CheckCategory, CheckScenario
from text_verification.domain.documents import FileType
from text_verification.domain.jobs import (
    TERMINAL_STATUSES,
    JobEvent,
    JobEventMetadata,
    JobRead,
    JobStatus,
    TerminalJobStateError,
)
from text_verification.infrastructure.orm import JobEventRow, JobRow

INITIAL_EVENT_MESSAGE = "作业已创建"
EXPIRED_EVENT_MESSAGE = "作业已过期"


class JobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_job(
        self,
        *,
        job_id: UUID,
        source_name: str,
        file_type: str,
        size_bytes: int,
        storage_key: str,
        created_at: datetime,
        expires_at: datetime,
        scenario: CheckScenario | str = CheckScenario.GENERAL,
        enabled_categories: Iterable[CheckCategory | str] = CHECK_CATEGORY_ORDER,
    ) -> JobRead:
        normalized_scenario = _normalize_scenario(scenario)
        normalized_categories = _normalize_enabled_categories(enabled_categories)
        row = JobRow(
            job_id=job_id,
            source_name=source_name,
            file_type=file_type,
            size_bytes=size_bytes,
            storage_key=storage_key,
            status=JobStatus.QUEUED.value,
            progress=0,
            error_code=None,
            error_message=None,
            scenario=normalized_scenario.value,
            enabled_categories_json=[category.value for category in normalized_categories],
            created_at=created_at,
            updated_at=created_at,
            expires_at=expires_at,
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
        job = self._lock_job(job_id)
        current_status = JobStatus(job.status)
        if current_status in TERMINAL_STATUSES:
            raise TerminalJobStateError(
                job_id=job_id,
                current_status=current_status,
                target_status=status,
            )
        changed_at = datetime.now(UTC)
        job.status = status.value
        job.progress = progress
        job.error_code = error_code
        job.error_message = error_message
        job.updated_at = changed_at
        self._session.add(
            JobEventRow(
                job_id=job_id,
                sequence=self._next_sequence(job_id),
                status=status.value,
                progress=progress,
                message=message,
                created_at=changed_at,
            )
        )
        self._session.flush()

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

    def record_progress(
        self,
        job_id: UUID,
        *,
        progress: int,
        message: str,
        metadata: JobEventMetadata,
    ) -> None:
        job = self._lock_job(job_id)
        current_status = JobStatus(job.status)
        if current_status in TERMINAL_STATUSES:
            raise TerminalJobStateError(
                job_id=job_id,
                current_status=current_status,
                target_status=current_status,
            )
        changed_at = datetime.now(UTC)
        job.progress = progress
        job.updated_at = changed_at
        self._session.add(
            JobEventRow(
                job_id=job_id,
                sequence=self._next_sequence(job_id),
                status=current_status.value,
                progress=progress,
                message=message,
                metadata_json=metadata.model_dump(mode="json"),
                created_at=changed_at,
            )
        )
        self._session.flush()

    def expire_jobs_before(self, cutoff: datetime) -> list[UUID]:
        rows = self._session.scalars(
            select(JobRow)
            .where(
                JobRow.expires_at <= cutoff,
            )
            .order_by(JobRow.expires_at, JobRow.job_id)
            .with_for_update()
        ).all()

        expired_job_ids: list[UUID] = []
        for row in rows:
            if row.status != JobStatus.EXPIRED.value:
                row.status = JobStatus.EXPIRED.value
                row.updated_at = cutoff
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
            scenario=CheckScenario(row.scenario),
            enabled_categories=[
                CheckCategory(category) for category in row.enabled_categories_json
            ],
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
            metadata=(
                JobEventMetadata.model_validate(row.metadata_json)
                if row.metadata_json is not None
                else None
            ),
        )


def _normalize_scenario(value: CheckScenario | str) -> CheckScenario:
    if isinstance(value, CheckScenario):
        return value
    return CheckScenario(value)


def _normalize_enabled_categories(
    values: Iterable[CheckCategory | str],
) -> list[CheckCategory]:
    normalized: list[CheckCategory] = []
    seen: set[CheckCategory] = set()
    for value in values:
        category = value if isinstance(value, CheckCategory) else CheckCategory(value)
        if category in seen:
            continue
        seen.add(category)
        normalized.append(category)
    if not normalized:
        raise ValueError("enabled_categories must not be empty")
    return normalized
