from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from text_verification.domain.exports import (
    TERMINAL_EXPORT_STATUSES,
    ExportRead,
    ExportStatus,
    ExportType,
    TerminalExportStateError,
    build_export_artifact,
)
from text_verification.infrastructure.orm import ExportRow, JobRow


class ExportRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, job_id: UUID, export_type: ExportType, extension: str) -> ExportRead:
        expires_at = self._session.scalar(
            select(JobRow.expires_at).where(JobRow.job_id == job_id)
        )
        if expires_at is None:
            raise LookupError(f"Job {job_id} does not exist.")

        export_id = uuid4()
        artifact = build_export_artifact(
            job_id=job_id,
            export_id=export_id,
            export_type=export_type,
            extension=extension,
        )
        created_at = datetime.now(UTC)
        row = ExportRow(
            export_id=export_id,
            job_id=job_id,
            export_type=_normalize_export_type(export_type).value,
            status=ExportStatus.QUEUED.value,
            file_name=artifact.file_name,
            storage_key=artifact.storage_key,
            warnings_json=[],
            error_code=None,
            error_message=None,
            created_at=created_at,
            updated_at=created_at,
            expires_at=expires_at,
        )
        self._session.add(row)
        self._session.flush()
        return _to_export_read(row)

    def get(self, export_id: UUID) -> ExportRead | None:
        row = self._session.get(ExportRow, export_id)
        if row is None:
            return None
        return _to_export_read(row)

    def mark_processing(self, export_id: UUID) -> ExportRead:
        row = self._lock_export(export_id)
        self._ensure_not_terminal(row, ExportStatus.PROCESSING)
        row.status = ExportStatus.PROCESSING.value
        row.updated_at = datetime.now(UTC)
        row.error_code = None
        row.error_message = None
        self._session.flush()
        return _to_export_read(row)

    def mark_completed(self, export_id: UUID, *, warnings: Sequence[str]) -> ExportRead:
        row = self._lock_export(export_id)
        self._ensure_not_terminal(row, ExportStatus.COMPLETED)
        row.status = ExportStatus.COMPLETED.value
        row.warnings_json = list(warnings)
        row.error_code = None
        row.error_message = None
        row.updated_at = datetime.now(UTC)
        self._session.flush()
        return _to_export_read(row)

    def mark_failed(
        self,
        export_id: UUID,
        *,
        error_code: str,
        error_message: str,
        warnings: Sequence[str] = (),
    ) -> ExportRead:
        row = self._lock_export(export_id)
        self._ensure_not_terminal(row, ExportStatus.FAILED)
        row.status = ExportStatus.FAILED.value
        row.warnings_json = list(warnings)
        row.error_code = error_code
        row.error_message = error_message
        row.updated_at = datetime.now(UTC)
        self._session.flush()
        return _to_export_read(row)

    def _lock_export(self, export_id: UUID) -> ExportRow:
        row = self._session.execute(
            select(ExportRow)
            .where(ExportRow.export_id == export_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if row is None:
            raise LookupError(f"Export {export_id} does not exist.")
        return row

    def _ensure_not_terminal(self, row: ExportRow, target_status: ExportStatus) -> None:
        current_status = ExportStatus(row.status)
        if current_status in TERMINAL_EXPORT_STATUSES:
            raise TerminalExportStateError(
                export_id=row.export_id,
                current_status=current_status,
                target_status=target_status,
            )


def _normalize_export_type(value: ExportType | str) -> ExportType:
    if isinstance(value, ExportType):
        return value
    return ExportType(value)


def _to_export_read(row: ExportRow) -> ExportRead:
    return ExportRead(
        export_id=row.export_id,
        job_id=row.job_id,
        export_type=ExportType(row.export_type),
        status=ExportStatus(row.status),
        file_name=row.file_name,
        storage_key=row.storage_key,
        warnings=list(row.warnings_json),
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
        expires_at=row.expires_at,
    )
