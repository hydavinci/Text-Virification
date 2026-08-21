from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from text_verification.checkers.models import CheckCategory, CheckerFailure
from text_verification.domain.documents import DocumentModel
from text_verification.domain.issues import Issue
from text_verification.domain.revisions import DocumentVersionRead, DocumentVersionStatus
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.orm import DocumentRow, DocumentVersionRow, JobRow
from text_verification.infrastructure.repositories import JobRepository


class ImmutableDocumentVersionError(ValueError):
    def __init__(self, version_id: UUID, status: DocumentVersionStatus) -> None:
        self.version_id = version_id
        self.status = status
        super().__init__(
            f"Document version {version_id} is immutable after reaching {status.value}."
        )


class RevisionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._analysis = AnalysisRepository(session)

    def create_queued_version(
        self,
        job_id: UUID,
        parent_version_id: UUID | None,
        reason: str,
        idempotency_key: str | None,
    ) -> DocumentVersionRead:
        job = JobRepository(self._session).lock_job(job_id)
        del job

        if idempotency_key is not None:
            existing = self._session.execute(
                select(DocumentVersionRow)
                .where(
                    DocumentVersionRow.job_id == job_id,
                    DocumentVersionRow.idempotency_key == idempotency_key,
                )
                .execution_options(populate_existing=True)
            ).scalar_one_or_none()
            if existing is not None:
                return _to_version_read(existing)

        if parent_version_id is not None:
            parent = self._session.get(DocumentVersionRow, parent_version_id)
            if parent is None or parent.job_id != job_id:
                raise LookupError(f"Parent document version {parent_version_id} does not exist.")

        created_at = datetime.now(UTC)
        version = DocumentVersionRow(
            job_id=job_id,
            parent_version_id=parent_version_id,
            revision_number=self._next_revision_number(job_id),
            status=DocumentVersionStatus.QUEUED.value,
            source_kind="upload" if parent_version_id is None else "edit",
            created_reason=reason,
            content_sha256=None,
            idempotency_key=idempotency_key,
            created_at=created_at,
            started_at=None,
            completed_at=None,
            failure_code=None,
            failure_message=None,
        )
        self._session.add(version)
        self._session.flush()
        return _to_version_read(version)

    def mark_analyzing(self, version_id: UUID) -> DocumentVersionRead:
        version = self._lock_version(version_id)
        status = DocumentVersionStatus(version.status)
        if status in {DocumentVersionStatus.SUCCEEDED, DocumentVersionStatus.FAILED}:
            raise ImmutableDocumentVersionError(version_id, status)
        if status == DocumentVersionStatus.ANALYZING:
            return _to_version_read(version)

        JobRepository(self._session).lock_job(version.job_id)
        version.status = DocumentVersionStatus.ANALYZING.value
        version.started_at = version.started_at or datetime.now(UTC)
        self._session.flush()
        return _to_version_read(version)

    def complete_analysis(
        self,
        version_id: UUID,
        document: DocumentModel,
        issues: list[Issue],
        failures: dict[CheckCategory, CheckerFailure],
    ) -> DocumentVersionRead:
        version = self._lock_version(version_id)
        status = DocumentVersionStatus(version.status)
        if status in {DocumentVersionStatus.SUCCEEDED, DocumentVersionStatus.FAILED}:
            raise ImmutableDocumentVersionError(version_id, status)

        job = JobRepository(self._session).lock_job(version.job_id)
        self._require_strictly_newer_document_version(
            version.job_id,
            version.version_id,
            document.version,
        )
        self._analysis.persist_version_analysis(version.version_id, document, issues, failures)

        changed_at = datetime.now(UTC)
        version.status = DocumentVersionStatus.SUCCEEDED.value
        version.content_sha256 = normalized_document_sha256(document)
        version.started_at = version.started_at or changed_at
        version.completed_at = changed_at
        version.failure_code = None
        version.failure_message = None
        job.active_version_id = version.version_id
        self._session.flush()
        return _to_version_read(version)

    def fail_version(self, version_id: UUID, code: str, message: str) -> DocumentVersionRead:
        version = self._lock_version(version_id)
        status = DocumentVersionStatus(version.status)
        if status in {DocumentVersionStatus.SUCCEEDED, DocumentVersionStatus.FAILED}:
            raise ImmutableDocumentVersionError(version_id, status)

        JobRepository(self._session).lock_job(version.job_id)
        changed_at = datetime.now(UTC)
        version.status = DocumentVersionStatus.FAILED.value
        version.started_at = version.started_at or changed_at
        version.completed_at = changed_at
        version.failure_code = code
        version.failure_message = message
        version.content_sha256 = None
        self._session.flush()
        return _to_version_read(version)

    def get_active_version(self, job_id: UUID) -> DocumentVersionRead | None:
        version_id = self._current_version_id(job_id)
        if version_id is None:
            return None
        version = self._session.get(DocumentVersionRow, version_id)
        if version is None:
            return None
        return _to_version_read(version)

    def list_versions(self, job_id: UUID) -> list[DocumentVersionRead]:
        rows = self._session.scalars(
            select(DocumentVersionRow)
            .where(DocumentVersionRow.job_id == job_id)
            .order_by(DocumentVersionRow.revision_number, DocumentVersionRow.created_at)
        ).all()
        return [_to_version_read(row) for row in rows]

    def _lock_version(self, version_id: UUID) -> DocumentVersionRow:
        version = self._session.execute(
            select(DocumentVersionRow)
            .where(DocumentVersionRow.version_id == version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if version is None:
            raise LookupError(f"Document version {version_id} does not exist.")
        return version

    def _next_revision_number(self, job_id: UUID) -> int:
        current_max = self._session.scalar(
            select(func.max(DocumentVersionRow.revision_number)).where(
                DocumentVersionRow.job_id == job_id
            )
        )
        return int(current_max or 0) + 1

    def _current_version_id(self, job_id: UUID) -> UUID | None:
        version_id = self._session.scalar(
            select(JobRow.active_version_id).where(JobRow.job_id == job_id)
        )
        if version_id is not None:
            return version_id
        return self._session.scalar(
            select(DocumentRow.version_id)
            .where(DocumentRow.job_id == job_id)
            .order_by(DocumentRow.version.desc())
            .limit(1)
        )

    def _require_strictly_newer_document_version(
        self,
        job_id: UUID,
        version_id: UUID,
        document_version: int,
    ) -> None:
        current_version_id = self._current_version_id(job_id)
        if current_version_id is None or current_version_id == version_id:
            return
        current_document_version = self._session.scalar(
            select(DocumentRow.version).where(DocumentRow.version_id == current_version_id)
        )
        if current_document_version is not None and document_version <= current_document_version:
            raise ValueError(
                "replacement document version must be strictly greater than "
                "current persisted version"
            )


def normalized_document_sha256(document: DocumentModel) -> str:
    payload = json.dumps(
        document.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _to_version_read(row: DocumentVersionRow) -> DocumentVersionRead:
    return DocumentVersionRead.model_validate(row)
