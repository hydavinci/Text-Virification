from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from text_verification.domain.documents import FileType, TextBlock
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
from text_verification.infrastructure.storage import validate_artifact_storage_key


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
                        text=text,
                        created_at=created_at,
                    )
                )
                self._session.flush()
        except IntegrityError as error:
            raise ValueError(
                f"Review revision {review_revision_id} conflicts with existing data."
            ) from error

    def save_export_artifact(
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
        created_at: datetime,
    ) -> None:
        if size_bytes < 0:
            raise ValueError("size_bytes must be greater than or equal to zero.")
        run = self._lock_run(verification_run_id)
        job = self._lock_job(run.job_id)
        if JobStatus(job.status) is JobStatus.EXPIRED:
            raise ValueError(f"Job {job.job_id} has expired.")
        validate_artifact_storage_key(job.job_id, storage_key)
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

        normalized_file_type = FileType(file_type).value
        values = (
            verification_run_id,
            review_revision_id,
            source_version,
            normalized_file_type,
            file_name,
            media_type,
            storage_key,
            size_bytes,
            created_at,
        )
        existing = self._session.get(ExportArtifactRow, export_artifact_id)
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
                existing.created_at,
            )
            if persisted != values:
                raise ValueError(
                    f"Export artifact {export_artifact_id} is already persisted "
                    "with different data."
                )
            return

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
                        file_type=normalized_file_type,
                        file_name=file_name,
                        media_type=media_type,
                        storage_key=storage_key,
                        size_bytes=size_bytes,
                        created_at=created_at,
                    )
                )
                self._session.flush()
        except IntegrityError as error:
            raise ValueError(
                f"Export artifact {export_artifact_id} conflicts with existing data."
            ) from error

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
        row = self._session.execute(
            select(JobRow)
            .where(JobRow.job_id == job_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if row is None:
            raise LookupError(f"Job {job_id} does not exist.")
        return row

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
