from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from text_verification.domain.issues import DecisionAction, DecisionCommand
from text_verification.domain.review_operations import (
    ReviewOperationBatchRead,
    ReviewOperationType,
)
from text_verification.infrastructure.orm import (
    DocumentRow,
    DocumentVersionRow,
    IssueDecisionRow,
    IssueRow,
    IssueSuggestionRow,
    JobRow,
    ReviewOperationBatchRow,
    ReviewOperationItemRow,
)

ISSUE_NOT_FOUND_CODE = "issue_not_found"
DECISION_NOT_FOUND_CODE = "decision_not_found"
STALE_DECISION_REVISION_CODE = "stale_decision_revision"
STALE_ISSUE_VERSION_CODE = "stale_issue_version"
SUGGESTION_NOT_FOUND_CODE = "suggestion_not_found"

DecisionSnapshot = dict[str, object]


@dataclass(frozen=True)
class PreparedDecision:
    command: DecisionCommand
    issue_row: IssueRow
    decision_row: IssueDecisionRow | None
    before: DecisionSnapshot | None
    after: DecisionSnapshot | None
    updated_at: datetime


@dataclass(frozen=True)
class DecisionOperationResult:
    batch: ReviewOperationBatchRead
    items: list[PreparedDecision]


@dataclass(frozen=True)
class ReviewOperationPage:
    job_id: UUID
    version_id: UUID
    total: int
    items: list[ReviewOperationBatchRead]
    next_cursor: None = None


class DecisionBatchConflict(RuntimeError):
    def __init__(self, conflicts: dict[UUID, str]) -> None:
        self.conflicts = conflicts
        super().__init__("Decision batch contains stale or invalid items.")


class OverlappingDecisions(RuntimeError):
    def __init__(self, issue_ids: list[UUID]) -> None:
        self.issue_ids = issue_ids
        super().__init__("Accepted decision ranges overlap.")


class OperationBatchNotFound(LookupError):
    pass


class OperationUndoConflict(RuntimeError):
    def __init__(self, issue_ids: list[UUID]) -> None:
        self.issue_ids = issue_ids
        super().__init__("Current decisions no longer match the original operation.")


class ReviewOperationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def apply_decisions(
        self,
        job_id: UUID,
        commands: list[DecisionCommand],
    ) -> DecisionOperationResult:
        job = self._lock_job(job_id)
        version_id = self._active_version_id(job)
        issue_rows = self._lock_issues(job_id, version_id, commands)
        issue_rows_by_id = {row.issue_id: row for row in issue_rows}
        decision_rows = self._lock_decisions([command.issue_id for command in commands])
        decision_rows_by_id = {row.issue_id: row for row in decision_rows}
        suggestion_owners = self._suggestion_owners(commands)
        document_version = self._document_version(version_id)

        conflicts: dict[UUID, str] = {}
        prepared: list[PreparedDecision] = []
        for command in commands:
            issue_row = issue_rows_by_id.get(command.issue_id)
            decision_row = decision_rows_by_id.get(command.issue_id)
            conflict_code = self._validate_command(
                command,
                issue_row=issue_row,
                decision_row=decision_row,
                suggestion_owners=suggestion_owners,
                document_version=document_version,
            )
            if conflict_code is not None:
                conflicts[command.issue_id] = conflict_code
                continue
            assert issue_row is not None
            before = _decision_snapshot(decision_row)
            prepared.append(
                PreparedDecision(
                    command=command,
                    issue_row=issue_row,
                    decision_row=decision_row,
                    before=before,
                    after=_command_snapshot(command, issue_row),
                    updated_at=datetime.now(UTC),
                )
            )

        if conflicts:
            raise DecisionBatchConflict(conflicts)

        overlap_ids = self._overlapping_issue_ids(
            version_id,
            prepared,
            issue_rows_by_id,
        )
        if overlap_ids:
            raise OverlappingDecisions(overlap_ids)

        changed_at = datetime.now(UTC)
        batch = ReviewOperationBatchRow(
            job_id=job_id,
            version_id=version_id,
            operation_type=ReviewOperationType.DECISION.value,
            affected_count=len(prepared),
            undoes_batch_id=None,
            created_at=changed_at,
        )
        self._session.add(batch)
        self._session.flush()
        prepared = [
            PreparedDecision(
                command=item.command,
                issue_row=item.issue_row,
                decision_row=item.decision_row,
                before=item.before,
                after=_command_snapshot(
                    item.command,
                    item.issue_row,
                    batch_id=batch.operation_batch_id,
                    updated_at=changed_at,
                ),
                updated_at=changed_at,
            )
            for item in prepared
        ]

        for sequence, item in enumerate(prepared):
            self._session.add(
                ReviewOperationItemRow(
                    operation_batch_id=batch.operation_batch_id,
                    sequence=sequence,
                    issue_id=item.command.issue_id,
                    before_json=item.before,
                    after_json=item.after,
                )
            )
            self._apply_snapshot(
                item.issue_row,
                item.decision_row,
                item.after,
            )

        self._session.flush()
        return DecisionOperationResult(
            batch=ReviewOperationBatchRead.model_validate(batch),
            items=prepared,
        )

    def list_batches(
        self,
        job_id: UUID,
        *,
        version_id: UUID | None = None,
    ) -> ReviewOperationPage:
        resolved_version_id = version_id or self._active_version_id_for_job(job_id)
        total = int(
            self._session.scalar(
                select(func.count())
                .select_from(ReviewOperationBatchRow)
                .where(
                    ReviewOperationBatchRow.job_id == job_id,
                    ReviewOperationBatchRow.version_id == resolved_version_id,
                )
            )
            or 0
        )
        rows = self._session.scalars(
            select(ReviewOperationBatchRow)
            .where(
                ReviewOperationBatchRow.job_id == job_id,
                ReviewOperationBatchRow.version_id == resolved_version_id,
            )
            .order_by(
                ReviewOperationBatchRow.created_at.desc(),
                ReviewOperationBatchRow.operation_batch_id.desc(),
            )
        ).all()
        return ReviewOperationPage(
            job_id=job_id,
            version_id=resolved_version_id,
            total=total,
            items=[ReviewOperationBatchRead.model_validate(row) for row in rows],
        )

    def undo(
        self,
        job_id: UUID,
        batch_id: UUID,
    ) -> ReviewOperationBatchRead:
        self._lock_job(job_id)
        original = self._session.execute(
            select(ReviewOperationBatchRow)
            .where(
                ReviewOperationBatchRow.operation_batch_id == batch_id,
                ReviewOperationBatchRow.job_id == job_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if original is None:
            raise OperationBatchNotFound(batch_id)
        version_owned_by_job = self._session.scalar(
            select(DocumentVersionRow.version_id).where(
                DocumentVersionRow.version_id == original.version_id,
                DocumentVersionRow.job_id == job_id,
            )
        )
        if version_owned_by_job is None:
            raise OperationBatchNotFound(batch_id)

        item_ids = list(
            self._session.scalars(
                select(ReviewOperationItemRow.issue_id)
                .where(ReviewOperationItemRow.operation_batch_id == batch_id)
                .order_by(ReviewOperationItemRow.issue_id)
            ).all()
        )
        issue_rows = self._session.scalars(
            select(IssueRow)
            .where(
                IssueRow.version_id == original.version_id,
                IssueRow.issue_id.in_(item_ids),
            )
            .order_by(IssueRow.issue_id)
            .with_for_update()
        ).all()
        items = self._session.scalars(
            select(ReviewOperationItemRow)
            .where(ReviewOperationItemRow.operation_batch_id == batch_id)
            .order_by(ReviewOperationItemRow.issue_id)
            .with_for_update()
        ).all()
        issue_rows_by_id = {row.issue_id: row for row in issue_rows}
        decision_rows = self._lock_decisions(item_ids)
        decision_rows_by_id = {row.issue_id: row for row in decision_rows}

        conflict_ids = [
            item.issue_id
            for item in items
            if _decision_snapshot(decision_rows_by_id.get(item.issue_id)) != item.after_json
        ]
        if conflict_ids:
            raise OperationUndoConflict(conflict_ids)

        restore_items = [
            PreparedDecision(
                command=DecisionCommand(
                    issue_id=item.issue_id,
                    issue_version=issue_rows_by_id[item.issue_id].document_version,
                    expected_revision=0,
                    action=(
                        DecisionAction.UNREVIEWED
                        if item.before_json is None
                        else DecisionAction(str(item.before_json["action"]))
                    ),
                    replacement=(
                        None
                        if item.before_json is None
                        else _optional_string(item.before_json["final_replacement"])
                    ),
                    suggestion_id=(
                        None
                        if item.before_json is None
                        else _optional_uuid(item.before_json["suggestion_id"])
                    ),
                ),
                issue_row=issue_rows_by_id[item.issue_id],
                decision_row=decision_rows_by_id.get(item.issue_id),
                before=item.after_json,
                after=item.before_json,
                updated_at=datetime.now(UTC),
            )
            for item in items
        ]
        overlap_ids = self._overlapping_issue_ids(
            original.version_id,
            restore_items,
            issue_rows_by_id,
        )
        if overlap_ids:
            raise OperationUndoConflict(overlap_ids)

        changed_at = datetime.now(UTC)
        undo_batch = ReviewOperationBatchRow(
            job_id=job_id,
            version_id=original.version_id,
            operation_type=ReviewOperationType.UNDO.value,
            affected_count=len(items),
            undoes_batch_id=original.operation_batch_id,
            created_at=changed_at,
        )
        self._session.add(undo_batch)
        self._session.flush()

        for sequence, item in enumerate(items):
            restored_snapshot = _restored_snapshot(
                item.before_json,
                issue_rows_by_id[item.issue_id],
                batch_id=undo_batch.operation_batch_id,
                updated_at=changed_at,
            )
            self._session.add(
                ReviewOperationItemRow(
                    operation_batch_id=undo_batch.operation_batch_id,
                    sequence=sequence,
                    issue_id=item.issue_id,
                    before_json=item.after_json,
                    after_json=restored_snapshot,
                )
            )
            issue_row = issue_rows_by_id[item.issue_id]
            self._apply_snapshot(
                issue_row,
                decision_rows_by_id.get(item.issue_id),
                restored_snapshot,
            )

        self._session.flush()
        return ReviewOperationBatchRead.model_validate(undo_batch)

    def _validate_command(
        self,
        command: DecisionCommand,
        *,
        issue_row: IssueRow | None,
        decision_row: IssueDecisionRow | None,
        suggestion_owners: dict[UUID, UUID],
        document_version: int,
    ) -> str | None:
        if issue_row is None:
            if command.issue_version < document_version:
                return STALE_ISSUE_VERSION_CODE
            return ISSUE_NOT_FOUND_CODE
        if issue_row.document_version != command.issue_version:
            return STALE_ISSUE_VERSION_CODE
        current_revision = 0 if decision_row is None else decision_row.revision
        if current_revision != command.expected_revision:
            return STALE_DECISION_REVISION_CODE
        if command.action == DecisionAction.UNREVIEWED and decision_row is None:
            return DECISION_NOT_FOUND_CODE
        if (
            command.suggestion_id is not None
            and suggestion_owners.get(command.suggestion_id) != command.issue_id
        ):
            return SUGGESTION_NOT_FOUND_CODE
        return None

    def _overlapping_issue_ids(
        self,
        version_id: UUID,
        prepared: list[PreparedDecision],
        issue_rows_by_id: dict[UUID, IssueRow],
    ) -> list[UUID]:
        existing_accepted_ids = list(
            self._session.scalars(
                select(IssueDecisionRow.issue_id).where(
                    IssueDecisionRow.version_id == version_id,
                    IssueDecisionRow.action == DecisionAction.ACCEPTED.value,
                )
            ).all()
        )
        final_actions: dict[UUID, str] = {
            issue_id: DecisionAction.ACCEPTED.value for issue_id in existing_accepted_ids
        }
        for item in prepared:
            if item.after is None:
                final_actions.pop(item.command.issue_id, None)
            else:
                final_actions[item.command.issue_id] = str(item.after["action"])

        accepted_issue_ids = sorted(
            issue_id for issue_id, action in final_actions.items() if action == "accepted"
        )
        missing_issue_ids = [
            issue_id for issue_id in accepted_issue_ids if issue_id not in issue_rows_by_id
        ]
        if missing_issue_ids:
            existing_rows = self._session.scalars(
                select(IssueRow).where(
                    IssueRow.version_id == version_id,
                    IssueRow.issue_id.in_(missing_issue_ids),
                )
            ).all()
            issue_rows_by_id.update({row.issue_id: row for row in existing_rows})

        accepted_rows = sorted(
            (issue_rows_by_id[issue_id] for issue_id in accepted_issue_ids),
            key=lambda row: (row.block_id, row.start_offset, row.end_offset, row.issue_id),
        )
        conflict_ids: set[UUID] = set()
        previous: IssueRow | None = None
        for current in accepted_rows:
            if (
                previous is not None
                and previous.block_id == current.block_id
                and current.start_offset < previous.end_offset
            ):
                conflict_ids.add(previous.issue_id)
                conflict_ids.add(current.issue_id)
            if (
                previous is None
                or previous.block_id != current.block_id
                or current.end_offset > previous.end_offset
            ):
                previous = current
        return sorted(conflict_ids)

    def _apply_snapshot(
        self,
        issue_row: IssueRow,
        decision_row: IssueDecisionRow | None,
        snapshot: DecisionSnapshot | None,
    ) -> None:
        if snapshot is None:
            if decision_row is not None:
                self._session.delete(decision_row)
            return

        if decision_row is None:
            decision_row = IssueDecisionRow(
                issue_id=issue_row.issue_id,
                version_id=_required_uuid(snapshot["version_id"]),
                job_id=_required_uuid(snapshot["job_id"]),
                issue_version=_required_int(snapshot["issue_version"]),
                revision=_required_int(snapshot["revision"]),
                action=str(snapshot["action"]),
                replacement=_optional_string(snapshot["replacement"]),
                final_replacement=_optional_string(snapshot["final_replacement"]),
                suggestion_id=_optional_uuid(snapshot["suggestion_id"]),
                operation_batch_id=_optional_uuid(snapshot["operation_batch_id"]),
                updated_at=_required_datetime(snapshot["updated_at"]),
            )
            self._session.add(decision_row)
            return

        decision_row.version_id = _required_uuid(snapshot["version_id"])
        decision_row.job_id = _required_uuid(snapshot["job_id"])
        decision_row.issue_version = _required_int(snapshot["issue_version"])
        decision_row.revision = _required_int(snapshot["revision"])
        decision_row.action = str(snapshot["action"])
        decision_row.replacement = _optional_string(snapshot["replacement"])
        decision_row.final_replacement = _optional_string(snapshot["final_replacement"])
        decision_row.suggestion_id = _optional_uuid(snapshot["suggestion_id"])
        decision_row.operation_batch_id = _optional_uuid(snapshot["operation_batch_id"])
        decision_row.updated_at = _required_datetime(snapshot["updated_at"])

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

    def _active_version_id(self, job: JobRow) -> UUID:
        if job.active_version_id is not None:
            return job.active_version_id
        version_id = self._session.scalar(
            select(DocumentRow.version_id)
            .where(DocumentRow.job_id == job.job_id)
            .order_by(DocumentRow.version.desc())
            .limit(1)
        )
        if version_id is None:
            raise LookupError(f"Job {job.job_id} does not have an active analysis.")
        return version_id

    def _active_version_id_for_job(self, job_id: UUID) -> UUID:
        active_version_id = self._session.scalar(
            select(JobRow.active_version_id).where(JobRow.job_id == job_id)
        )
        if active_version_id is None:
            raise LookupError(f"Job {job_id} does not have an active analysis.")
        return active_version_id

    def _lock_issues(
        self,
        job_id: UUID,
        version_id: UUID,
        commands: list[DecisionCommand],
    ) -> list[IssueRow]:
        issue_ids = sorted({command.issue_id for command in commands})
        return list(
            self._session.scalars(
                select(IssueRow)
                .where(
                    IssueRow.job_id == job_id,
                    IssueRow.version_id == version_id,
                    IssueRow.issue_id.in_(issue_ids),
                )
                .order_by(IssueRow.issue_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )

    def _lock_decisions(self, issue_ids: list[UUID]) -> list[IssueDecisionRow]:
        if not issue_ids:
            return []
        return list(
            self._session.scalars(
                select(IssueDecisionRow)
                .where(IssueDecisionRow.issue_id.in_(sorted(set(issue_ids))))
                .order_by(IssueDecisionRow.issue_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )

    def _suggestion_owners(
        self,
        commands: list[DecisionCommand],
    ) -> dict[UUID, UUID]:
        suggestion_ids = sorted(
            {
                command.suggestion_id
                for command in commands
                if command.suggestion_id is not None
            }
        )
        if not suggestion_ids:
            return {}
        rows = self._session.execute(
            select(IssueSuggestionRow.suggestion_id, IssueSuggestionRow.issue_id).where(
                IssueSuggestionRow.suggestion_id.in_(suggestion_ids)
            )
        ).all()
        return {suggestion_id: issue_id for suggestion_id, issue_id in rows}

    def _document_version(self, version_id: UUID) -> int:
        document_version = self._session.scalar(
            select(DocumentRow.version).where(DocumentRow.version_id == version_id)
        )
        if document_version is None:
            raise LookupError(f"Document version {version_id} does not exist.")
        return document_version


def _decision_snapshot(row: IssueDecisionRow | None) -> DecisionSnapshot | None:
    if row is None:
        return None
    return {
        "issue_id": str(row.issue_id),
        "version_id": str(row.version_id),
        "job_id": str(row.job_id),
        "issue_version": row.issue_version,
        "revision": row.revision,
        "action": row.action,
        "replacement": row.replacement,
        "final_replacement": row.final_replacement,
        "suggestion_id": None if row.suggestion_id is None else str(row.suggestion_id),
        "operation_batch_id": (
            None if row.operation_batch_id is None else str(row.operation_batch_id)
        ),
        "updated_at": row.updated_at.isoformat(),
    }


def _command_snapshot(
    command: DecisionCommand,
    issue_row: IssueRow,
    *,
    batch_id: UUID | None = None,
    updated_at: datetime | None = None,
) -> DecisionSnapshot | None:
    if command.action == DecisionAction.UNREVIEWED:
        return None
    replacement = command.replacement if command.action == DecisionAction.ACCEPTED else None
    return {
        "issue_id": str(command.issue_id),
        "version_id": str(issue_row.version_id),
        "job_id": str(issue_row.job_id),
        "issue_version": command.issue_version,
        "revision": command.expected_revision + 1,
        "action": command.action.value,
        "replacement": replacement,
        "final_replacement": replacement,
        "suggestion_id": (
            None if command.suggestion_id is None else str(command.suggestion_id)
        ),
        "operation_batch_id": None if batch_id is None else str(batch_id),
        "updated_at": None if updated_at is None else updated_at.isoformat(),
    }


def _restored_snapshot(
    prior_snapshot: DecisionSnapshot | None,
    issue_row: IssueRow,
    *,
    batch_id: UUID,
    updated_at: datetime,
) -> DecisionSnapshot | None:
    if prior_snapshot is None:
        return None
    restored = dict(prior_snapshot)
    restored.update(
        {
            "issue_id": str(issue_row.issue_id),
            "version_id": str(issue_row.version_id),
            "job_id": str(issue_row.job_id),
            "operation_batch_id": str(batch_id),
            "updated_at": updated_at.isoformat(),
        }
    )
    return restored


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(str(value))


def _required_int(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError("decision snapshot integer field is invalid")
    return value


def _required_uuid(value: object) -> UUID:
    if value is None:
        raise TypeError("decision snapshot UUID field is invalid")
    return UUID(str(value))


def _required_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise TypeError("decision snapshot datetime field is invalid")
    return datetime.fromisoformat(value)
