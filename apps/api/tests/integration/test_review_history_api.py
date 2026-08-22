from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from text_verification.api.dependencies import get_db_session
from text_verification.checkers.models import CheckCategory
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobStatus
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.orm import (
    IssueDecisionRow,
    IssueRow,
    JobRow,
    ReviewOperationBatchRow,
    ReviewOperationItemRow,
)
from text_verification.infrastructure.repositories import JobRepository


@dataclass(frozen=True)
class SeededReview:
    job_id: UUID
    version_id: UUID
    first_issue: IssueRow
    second_issue: IssueRow


@pytest.fixture
def seeded_review(db_session: Session) -> SeededReview:
    job_id = _seed_job(db_session)
    document = _build_document(version=1)
    first = _build_issue(
        document,
        issue_id=UUID("00000000-0000-0000-0000-000000000051"),
        start=0,
        end=2,
        original="甲乙",
        suggestion="甲",
    )
    second = _build_issue(
        document,
        issue_id=UUID("00000000-0000-0000-0000-000000000052"),
        start=1,
        end=5,
        original="乙丙丁戊",
        suggestion="丁",
    )
    AnalysisRepository(db_session).replace_analysis(job_id, document, [first, second], {})
    db_session.commit()

    job = db_session.get(JobRow, job_id)
    first_row = db_session.get(IssueRow, first.issue_id)
    second_row = db_session.get(IssueRow, second.issue_id)
    assert job is not None
    assert job.active_version_id is not None
    assert first_row is not None
    assert second_row is not None
    return SeededReview(
        job_id=job_id,
        version_id=job.active_version_id,
        first_issue=first_row,
        second_issue=second_row,
    )


def test_undo_deletes_decision_when_original_before_snapshot_was_absent(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    applied = _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="accepted",
        replacement="自定义文本",
        expected_revision=0,
    )
    batch_id = applied["batch_id"]

    undo = client.post(
        f"/api/v1/jobs/{seeded_review.job_id}/operation-batches/{batch_id}/undo"
    )

    assert undo.status_code == 200
    undo_payload = undo.json()
    assert undo_payload["operation_type"] == "undo"
    assert undo_payload["undoes_batch_id"] == batch_id
    assert db_session.get(IssueDecisionRow, seeded_review.first_issue.issue_id) is None
    assert _count_batches(db_session) == 2


def test_undo_restores_prior_values_only_when_after_snapshot_still_matches(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    ignored = _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="ignored",
        replacement=None,
        expected_revision=0,
    )
    assert ignored["outcomes"][0]["decision"]["action"] == "ignored"
    accepted = _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="accepted",
        replacement="编辑后的候选",
        expected_revision=1,
    )

    undo = client.post(
        f"/api/v1/jobs/{seeded_review.job_id}/operation-batches/"
        f"{accepted['batch_id']}/undo"
    )

    assert undo.status_code == 200
    restored = db_session.get(IssueDecisionRow, seeded_review.first_issue.issue_id)
    assert restored is not None
    assert restored.action == "ignored"
    assert restored.final_replacement is None
    assert restored.suggestion_id is None
    assert restored.operation_batch_id == UUID(undo.json()["batch_id"])
    undo_item = db_session.scalar(
        select(ReviewOperationItemRow).where(
            ReviewOperationItemRow.operation_batch_id == restored.operation_batch_id
        )
    )
    assert undo_item is not None
    assert undo_item.after_json is not None
    assert undo_item.after_json["operation_batch_id"] == str(
        restored.operation_batch_id
    )


def test_unreviewed_deletes_through_recorded_operation_and_can_be_undone(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="accepted",
        replacement="接受文本",
        expected_revision=0,
    )
    unreviewed = _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="unreviewed",
        replacement=None,
        expected_revision=1,
    )

    assert unreviewed["outcomes"][0]["status"] == "applied"
    assert unreviewed["outcomes"][0]["decision"] is None
    assert db_session.get(IssueDecisionRow, seeded_review.first_issue.issue_id) is None
    deletion_item = db_session.scalar(
        select(ReviewOperationItemRow).where(
            ReviewOperationItemRow.operation_batch_id
            == UUID(unreviewed["batch_id"])
        )
    )
    assert deletion_item is not None
    assert deletion_item.before_json is not None
    assert deletion_item.after_json is None

    undo = client.post(
        f"/api/v1/jobs/{seeded_review.job_id}/operation-batches/"
        f"{unreviewed['batch_id']}/undo"
    )

    assert undo.status_code == 200
    restored = db_session.get(IssueDecisionRow, seeded_review.first_issue.issue_id)
    assert restored is not None
    assert restored.action == "accepted"
    assert restored.final_replacement == "接受文本"


def test_unreviewed_without_existing_decision_is_atomic_conflict(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    response = client.put(
        f"/api/v1/jobs/{seeded_review.job_id}/decisions",
        json={
            "decisions": [
                _command(
                    seeded_review.first_issue,
                    action="unreviewed",
                    replacement=None,
                    expected_revision=0,
                ),
                _command(
                    seeded_review.second_issue,
                    action="ignored",
                    replacement=None,
                    expected_revision=0,
                ),
            ]
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "decision_batch_conflict"
    assert response.json()["detail"]["issue_ids"] == [
        str(seeded_review.first_issue.issue_id)
    ]
    assert db_session.get(IssueDecisionRow, seeded_review.second_issue.issue_id) is None
    assert _count_batches(db_session) == 0


def test_undo_conflict_after_newer_decision_does_not_write_partial_history(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    first = _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="accepted",
        replacement="第一版",
        expected_revision=0,
    )
    _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="ignored",
        replacement=None,
        expected_revision=1,
    )

    undo = client.post(
        f"/api/v1/jobs/{seeded_review.job_id}/operation-batches/"
        f"{first['batch_id']}/undo"
    )

    assert undo.status_code == 409
    assert undo.json()["detail"] == {
        "code": "operation_undo_conflict",
        "message": "问题决策已在该操作后发生变化，无法撤销。",
        "issue_ids": [str(seeded_review.first_issue.issue_id)],
    }
    current = db_session.get(IssueDecisionRow, seeded_review.first_issue.issue_id)
    assert current is not None
    assert current.action == "ignored"
    assert _count_batches(db_session) == 2


def test_undo_rejects_restoring_decision_that_would_overlap_current_state(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    first = _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="accepted",
        replacement="第一项",
        expected_revision=0,
    )
    removed = _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="unreviewed",
        replacement=None,
        expected_revision=1,
    )
    second = _put_decision(
        client,
        seeded_review,
        seeded_review.second_issue,
        action="accepted",
        replacement="第二项",
        expected_revision=0,
    )
    assert first["batch_id"] != removed["batch_id"] != second["batch_id"]

    undo = client.post(
        f"/api/v1/jobs/{seeded_review.job_id}/operation-batches/"
        f"{removed['batch_id']}/undo"
    )

    assert undo.status_code == 409
    assert undo.json()["detail"]["code"] == "operation_undo_conflict"
    assert set(undo.json()["detail"]["issue_ids"]) == {
        str(seeded_review.first_issue.issue_id),
        str(seeded_review.second_issue.issue_id),
    }
    assert db_session.get(IssueDecisionRow, seeded_review.first_issue.issue_id) is None
    current = db_session.get(IssueDecisionRow, seeded_review.second_issue.issue_id)
    assert current is not None
    assert current.action == "accepted"
    assert _count_batches(db_session) == 3


def test_history_returns_batches_newest_first_without_crossing_versions(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    first_batch = _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="ignored",
        replacement=None,
        expected_revision=0,
    )
    second_batch = _put_decision(
        client,
        seeded_review,
        seeded_review.second_issue,
        action="ignored",
        replacement=None,
        expected_revision=0,
    )
    next_document = _build_document(version=2)
    next_issue = _build_issue(
        next_document,
        issue_id=UUID("00000000-0000-0000-0000-000000000053"),
        start=0,
        end=2,
        original="甲乙",
        suggestion="新",
    )
    AnalysisRepository(db_session).replace_analysis(
        seeded_review.job_id,
        next_document,
        [next_issue],
        {},
    )
    db_session.commit()
    next_issue_row = db_session.get(IssueRow, next_issue.issue_id)
    assert next_issue_row is not None
    next_job = db_session.get(JobRow, seeded_review.job_id)
    assert next_job is not None
    assert next_job.active_version_id is not None
    next_review = SeededReview(
        seeded_review.job_id,
        next_job.active_version_id,
        next_issue_row,
        next_issue_row,
    )
    current_batch = _put_decision(
        client,
        next_review,
        next_issue_row,
        action="ignored",
        replacement=None,
        expected_revision=0,
    )

    historical = client.get(
        f"/api/v1/jobs/{seeded_review.job_id}/operation-batches",
        params={"version_id": str(seeded_review.version_id)},
    )
    current = client.get(
        f"/api/v1/jobs/{seeded_review.job_id}/operation-batches"
    )

    assert historical.status_code == 200
    assert [item["batch_id"] for item in historical.json()["items"]] == [
        second_batch["batch_id"],
        first_batch["batch_id"],
    ]
    assert historical.json()["total"] == 2
    assert current.status_code == 200
    assert current.json()["version_id"] == str(next_review.version_id)
    assert [item["batch_id"] for item in current.json()["items"]] == [
        current_batch["batch_id"]
    ]


def test_undo_historical_batch_after_new_version_activation(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    historical_batch = _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="ignored",
        replacement=None,
        expected_revision=0,
    )
    next_document = _build_document(version=2)
    next_issue = _build_issue(
        next_document,
        issue_id=UUID("00000000-0000-0000-0000-000000000054"),
        start=0,
        end=2,
        original="甲乙",
        suggestion="新",
    )
    AnalysisRepository(db_session).replace_analysis(
        seeded_review.job_id,
        next_document,
        [next_issue],
        {},
    )
    db_session.commit()
    next_issue_row = db_session.get(IssueRow, next_issue.issue_id)
    job = db_session.get(JobRow, seeded_review.job_id)
    assert next_issue_row is not None
    assert job is not None
    db_session.refresh(job)
    assert job.active_version_id is not None
    active_version_id = job.active_version_id
    next_review = SeededReview(
        seeded_review.job_id,
        active_version_id,
        next_issue_row,
        next_issue_row,
    )
    _put_decision(
        client,
        next_review,
        next_issue_row,
        action="ignored",
        replacement=None,
        expected_revision=0,
    )
    active_decision = db_session.get(IssueDecisionRow, next_issue.issue_id)
    assert active_decision is not None
    active_batch_id = active_decision.operation_batch_id

    undo = client.post(
        f"/api/v1/jobs/{seeded_review.job_id}/operation-batches/"
        f"{historical_batch['batch_id']}/undo"
    )

    assert undo.status_code == 200
    assert undo.json()["version_id"] == str(seeded_review.version_id)
    assert db_session.get(IssueDecisionRow, seeded_review.first_issue.issue_id) is None
    db_session.refresh(job)
    assert job.active_version_id == active_version_id
    unchanged_active_decision = db_session.get(IssueDecisionRow, next_issue.issue_id)
    assert unchanged_active_decision is not None
    assert unchanged_active_decision.action == "ignored"
    assert unchanged_active_decision.operation_batch_id == active_batch_id


def test_long_term_undo_has_no_deadline(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    applied = _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="accepted",
        replacement="长期撤销",
        expected_revision=0,
    )
    batch = db_session.get(ReviewOperationBatchRow, UUID(applied["batch_id"]))
    assert batch is not None
    batch.created_at = datetime.now(UTC) - timedelta(days=365)
    db_session.commit()

    undo = client.post(
        f"/api/v1/jobs/{seeded_review.job_id}/operation-batches/"
        f"{applied['batch_id']}/undo"
    )

    assert undo.status_code == 200
    assert undo.json()["operation_type"] == "undo"


def test_history_rejects_version_from_another_job(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    other_job_id = _seed_job(db_session)
    other_document = _build_document(version=1)
    AnalysisRepository(db_session).replace_analysis(
        other_job_id,
        other_document,
        [],
        {},
    )
    db_session.commit()
    other_job = db_session.get(JobRow, other_job_id)
    assert other_job is not None
    assert other_job.active_version_id is not None

    response = client.get(
        f"/api/v1/jobs/{seeded_review.job_id}/operation-batches",
        params={"version_id": str(other_job.active_version_id)},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "version_not_found"


def test_undo_rejects_batch_from_another_job_without_mutating_it(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    applied = _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="ignored",
        replacement=None,
        expected_revision=0,
    )
    other_job_id = _seed_job(db_session)
    AnalysisRepository(db_session).replace_analysis(
        other_job_id,
        _build_document(version=1),
        [],
        {},
    )
    db_session.commit()

    response = client.post(
        f"/api/v1/jobs/{other_job_id}/operation-batches/{applied['batch_id']}/undo"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "operation_batch_not_found"
    assert db_session.get(IssueDecisionRow, seeded_review.first_issue.issue_id) is not None
    assert _count_batches(db_session) == 1


def test_stale_revision_rolls_back_valid_sibling(
    client,
    db_session: Session,
    seeded_review: SeededReview,
) -> None:
    _put_decision(
        client,
        seeded_review,
        seeded_review.first_issue,
        action="ignored",
        replacement=None,
        expected_revision=0,
    )

    response = client.put(
        f"/api/v1/jobs/{seeded_review.job_id}/decisions",
        json={
            "decisions": [
                _command(
                    seeded_review.first_issue,
                    action="accepted",
                    replacement="过期修改",
                    expected_revision=0,
                ),
                _command(
                    seeded_review.second_issue,
                    action="ignored",
                    replacement=None,
                    expected_revision=0,
                ),
            ]
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "decision_batch_conflict"
    assert response.json()["detail"]["issue_ids"] == [
        str(seeded_review.first_issue.issue_id)
    ]
    assert db_session.get(IssueDecisionRow, seeded_review.second_issue.issue_id) is None
    assert _count_batches(db_session) == 1


def _put_decision(
    client,
    review: SeededReview,
    issue: IssueRow,
    *,
    action: str,
    replacement: str | None,
    expected_revision: int,
) -> dict[str, object]:
    response = client.put(
        f"/api/v1/jobs/{review.job_id}/decisions",
        json={
            "decisions": [
                _command(
                    issue,
                    action=action,
                    replacement=replacement,
                    expected_revision=expected_revision,
                )
            ]
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _command(
    issue: IssueRow,
    *,
    action: str,
    replacement: str | None,
    expected_revision: int,
) -> dict[str, object]:
    return {
        "issue_id": str(issue.issue_id),
        "issue_version": issue.document_version,
        "expected_revision": expected_revision,
        "action": action,
        "replacement": replacement,
        "suggestion_id": None,
    }


def _count_batches(db_session: Session) -> int:
    return int(
        db_session.scalar(select(func.count()).select_from(ReviewOperationBatchRow))
        or 0
    )


def _seed_job(db_session: Session) -> UUID:
    now = datetime.now(UTC)
    job_id = uuid4()
    repository = JobRepository(db_session)
    repository.create_job(
        job_id=job_id,
        source_name="review.txt",
        file_type=FileType.TXT.value,
        size_bytes=32,
        storage_key=str(job_id),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    repository.transition(job_id, JobStatus.COMPLETED, 100, "处理完成")
    repository.commit()
    return job_id


def _build_document(*, version: int) -> DocumentModel:
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="review.txt",
        version=version,
        blocks=[
            TextBlock(
                block_id="p-000001",
                kind="paragraph",
                text="甲乙丙丁戊",
                page=1,
                paragraph_index=0,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": 0},
            )
        ],
        metadata={"language": "zh-CN"},
    )


def _build_issue(
    document: DocumentModel,
    *,
    issue_id: UUID,
    start: int,
    end: int,
    original: str,
    suggestion: str,
) -> Issue:
    return Issue(
        issue_id=issue_id,
        document_id=document.document_id,
        block_id="p-000001",
        page=1,
        start=start,
        end=end,
        original=original,
        suggestion=suggestion,
        alternatives=[suggestion],
        type="literal",
        severity=IssueSeverity.WARNING,
        layer=CheckCategory.SECURITY.value,
        message="命中规则。",
        rule_id="security-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=True,
        context=original,
    )


@pytest.fixture(autouse=True)
def override_db_session(app: FastAPI, db_session: Session) -> None:
    def _db_session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _db_session_override
