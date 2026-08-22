from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from text_verification.api.dependencies import get_db_session
from text_verification.checkers.models import CheckCategory
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobStatus
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.orm import (
    IssueDecisionRow,
    IssueRow,
    IssueSuggestionRow,
    ReviewOperationBatchRow,
    ReviewOperationItemRow,
)
from text_verification.infrastructure.repositories import JobRepository


@dataclass(frozen=True)
class SeededIssue:
    issue_id: UUID
    document_version: int
    accepted_replacement: str | None


def test_one_stale_item_rolls_back_complete_batch(
    client,
    db_session: Session,
) -> None:
    job_id, current_issue, stale_issue = _seed_two_versioned_issues(db_session)

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(current_issue.issue_id),
                    "issue_version": current_issue.document_version,
                    "expected_revision": 0,
                    "action": "accepted",
                    "replacement": current_issue.accepted_replacement,
                    "suggestion_id": None,
                },
                {
                    "issue_id": str(stale_issue.issue_id),
                    "issue_version": stale_issue.document_version,
                    "expected_revision": 0,
                    "action": "ignored",
                    "replacement": None,
                    "suggestion_id": None,
                },
            ]
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "decision_batch_conflict",
        "message": "问题决策已过期或无效，请刷新后重试。",
        "issue_ids": [str(stale_issue.issue_id)],
    }
    assert _count_decisions(db_session, current_issue.issue_id) == 0
    assert _count_decisions(db_session, stale_issue.issue_id) == 0
    assert _count_operation_batches(db_session) == 0


def test_batch_decisions_reject_duplicate_issue_ids_with_structured_error(
    client,
    db_session: Session,
) -> None:
    job_id, current_issue, _stale_issue = _seed_two_versioned_issues(db_session)

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(current_issue.issue_id),
                    "issue_version": current_issue.document_version,
                    "expected_revision": 0,
                    "action": "accepted",
                    "replacement": current_issue.accepted_replacement,
                    "suggestion_id": None,
                },
                {
                    "issue_id": str(current_issue.issue_id),
                    "issue_version": current_issue.document_version,
                    "expected_revision": 0,
                    "action": "ignored",
                    "replacement": None,
                    "suggestion_id": None,
                },
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "duplicate_issue_decision",
        "message": "同一请求中不能重复提交同一问题的决策。",
    }
    assert _count_decisions(db_session, current_issue.issue_id) == 0


def test_batch_decisions_require_known_job_with_analysis(client, db_session: Session) -> None:
    ready_without_analysis = _seed_job(db_session, status=JobStatus.COMPLETED)
    payload = {
        "decisions": [
            {
                "issue_id": str(uuid4()),
                "issue_version": 1,
                "expected_revision": 0,
                "action": "accepted",
                "replacement": "替换",
                "suggestion_id": None,
            }
        ]
    }

    missing_response = client.put(
        "/api/v1/jobs/00000000-0000-0000-0000-000000000000/decisions",
        json=payload,
    )
    not_ready_response = client.put(
        f"/api/v1/jobs/{ready_without_analysis}/decisions",
        json=payload,
    )

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == {
        "code": "job_not_found",
        "message": "作业不存在。",
    }
    assert not_ready_response.status_code == 409
    assert not_ready_response.json()["detail"] == {
        "code": "analysis_not_ready",
        "message": "分析结果尚未就绪，请稍后重试。",
    }


def test_batch_decisions_reject_more_than_500_items(client) -> None:
    response = client.put(
        "/api/v1/jobs/00000000-0000-0000-0000-000000000000/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(uuid4()),
                    "issue_version": 1,
                    "expected_revision": 0,
                    "action": "accepted",
                    "replacement": "替换",
                    "suggestion_id": None,
                }
                for _ in range(501)
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "invalid_decision_request",
        "message": "问题决策请求无效，请检查后重试。",
    }


@pytest.mark.parametrize(
    "replacement",
    ["before\0after", "🙂" * 10_001],
    ids=["nul", "over-limit"],
)
def test_batch_decisions_reject_invalid_accepted_replacement_with_structured_error(
    client,
    db_session: Session,
    replacement: str,
) -> None:
    job_id, current_issue, _stale_issue = _seed_two_versioned_issues(db_session)

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(current_issue.issue_id),
                    "issue_version": current_issue.document_version,
                    "expected_revision": 0,
                    "action": "accepted",
                    "replacement": replacement,
                    "suggestion_id": None,
                }
            ]
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "invalid_decision_request",
        "message": "问题决策请求无效，请检查后重试。",
    }
    assert _count_decisions(db_session, current_issue.issue_id) == 0


def test_batch_decisions_accept_accepted_replacement_at_10_000_code_point_boundary(
    client,
    db_session: Session,
) -> None:
    job_id, current_issue, _stale_issue = _seed_two_versioned_issues(db_session)
    replacement = "🙂" * 10_000

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(current_issue.issue_id),
                    "issue_version": current_issue.document_version,
                    "expected_revision": 0,
                    "action": "accepted",
                    "replacement": replacement,
                    "suggestion_id": None,
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["outcomes"][0]["decision"]["replacement"] == replacement
    assert db_session.scalar(
        select(IssueDecisionRow.replacement).where(
            IssueDecisionRow.issue_id == current_issue.issue_id
        )
    ) == replacement


def test_one_missing_item_rolls_back_complete_batch(
    client,
    db_session: Session,
) -> None:
    job_id, current_issue, _stale_issue = _seed_two_versioned_issues(db_session)
    missing_issue_id = uuid4()

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(current_issue.issue_id),
                    "issue_version": current_issue.document_version,
                    "expected_revision": 0,
                    "action": "accepted",
                    "replacement": current_issue.accepted_replacement,
                    "suggestion_id": None,
                },
                {
                    "issue_id": str(missing_issue_id),
                    "issue_version": current_issue.document_version,
                    "expected_revision": 0,
                    "action": "ignored",
                    "replacement": None,
                    "suggestion_id": None,
                },
            ]
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "decision_batch_conflict",
        "message": "问题决策已过期或无效，请刷新后重试。",
        "issue_ids": [str(missing_issue_id)],
    }
    assert _count_decisions(db_session, current_issue.issue_id) == 0
    assert _count_operation_batches(db_session) == 0


def test_successful_batch_returns_batch_id_and_records_snapshots(
    client,
    db_session: Session,
) -> None:
    job_id, first_issue, second_issue = _seed_two_current_issues(db_session)

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json=_decision_payload(
            [
                (first_issue, "accepted"),
                (second_issue, "ignored"),
            ]
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    batch_id = UUID(payload["batch_id"])
    assert [outcome["issue_id"] for outcome in payload["outcomes"]] == [
        str(first_issue.issue_id),
        str(second_issue.issue_id),
    ]
    assert [outcome["status"] for outcome in payload["outcomes"]] == [
        "applied",
        "applied",
    ]
    batch = db_session.get(ReviewOperationBatchRow, batch_id)
    assert batch is not None
    assert batch.affected_count == 2
    items = db_session.scalars(
        select(ReviewOperationItemRow)
        .where(ReviewOperationItemRow.operation_batch_id == batch_id)
        .order_by(ReviewOperationItemRow.sequence)
    ).all()
    assert [item.issue_id for item in items] == [
        first_issue.issue_id,
        second_issue.issue_id,
    ]
    assert all(item.before_json is None for item in items)
    assert all(item.after_json is not None for item in items)
    assert [item.after_json["issue_id"] for item in items if item.after_json] == [
        str(first_issue.issue_id),
        str(second_issue.issue_id),
    ]
    assert all(
        item.after_json["operation_batch_id"] == str(batch_id)
        for item in items
        if item.after_json
    )
    assert all("updated_at" in item.after_json for item in items if item.after_json)


def test_issue_response_exposes_ordered_unique_suggestions_and_accepts_edited_candidate(
    client,
    db_session: Session,
) -> None:
    job_id, issue = _seed_issue_with_suggestions(db_session)

    issue_response = client.get(f"/api/v1/jobs/{job_id}/issues")

    assert issue_response.status_code == 200
    suggestions = issue_response.json()["items"][0]["suggestions"]
    assert [
        {
            "text": item["text"],
            "source": item["source"],
            "explanation": item["explanation"],
            "rank": item["rank"],
            "preferred": item["preferred"],
        }
        for item in suggestions
    ] == [
        {
            "text": "首选",
            "source": "rule",
            "explanation": None,
            "rank": 0,
            "preferred": True,
        },
        {
            "text": "备选",
            "source": "rule",
            "explanation": None,
            "rank": 1,
            "preferred": False,
        },
        {
            "text": "另一个",
            "source": "rule",
            "explanation": None,
            "rank": 2,
            "preferred": False,
        },
    ]

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(issue.issue_id),
                    "issue_version": issue.document_version,
                    "expected_revision": 0,
                    "action": "accepted",
                    "replacement": "编辑后的候选",
                    "suggestion_id": suggestions[1]["suggestion_id"],
                }
            ]
        },
    )

    assert response.status_code == 200
    decision = response.json()["outcomes"][0]["decision"]
    assert decision["replacement"] == "编辑后的候选"
    assert decision["suggestion_id"] == suggestions[1]["suggestion_id"]
    stored = db_session.get(IssueDecisionRow, issue.issue_id)
    assert stored is not None
    assert stored.final_replacement == "编辑后的候选"


def test_batch_rejects_suggestion_from_another_issue(
    client,
    db_session: Session,
) -> None:
    job_id, first_issue, second_issue = _seed_two_current_issues(db_session)
    foreign_suggestion_id = db_session.scalar(
        select(IssueSuggestionRow.suggestion_id).where(
            IssueSuggestionRow.issue_id == second_issue.issue_id
        )
    )
    assert foreign_suggestion_id is not None

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json={
            "decisions": [
                {
                    "issue_id": str(first_issue.issue_id),
                    "issue_version": first_issue.document_version,
                    "expected_revision": 0,
                    "action": "accepted",
                    "replacement": "编辑后的候选",
                    "suggestion_id": str(foreign_suggestion_id),
                }
            ]
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "decision_batch_conflict"
    assert response.json()["detail"]["issue_ids"] == [str(first_issue.issue_id)]
    assert _count_decisions(db_session, first_issue.issue_id) == 0
    assert _count_operation_batches(db_session) == 0


def test_overlapping_accepted_decisions_roll_back_complete_batch(
    client,
    db_session: Session,
) -> None:
    job_id, first_issue, second_issue = _seed_two_current_issues(db_session)

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json=_decision_payload(
            [
                (first_issue, "accepted"),
                (second_issue, "accepted"),
            ]
        ),
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "overlapping_decisions",
        "message": "接受的修改范围相互重叠，请仅保留其中一个。",
        "issue_ids": [
            str(first_issue.issue_id),
            str(second_issue.issue_id),
        ],
    }
    assert _count_decisions(db_session, first_issue.issue_id) == 0
    assert _count_decisions(db_session, second_issue.issue_id) == 0
    assert _count_operation_batches(db_session) == 0


def test_new_accepted_decision_cannot_overlap_existing_accepted_decision(
    client,
    db_session: Session,
) -> None:
    job_id, first_issue, second_issue = _seed_two_current_issues(db_session)
    first = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json=_decision_payload([(first_issue, "accepted")]),
    )
    assert first.status_code == 200

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json=_decision_payload([(second_issue, "accepted")]),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "overlapping_decisions"
    assert set(response.json()["detail"]["issue_ids"]) == {
        str(first_issue.issue_id),
        str(second_issue.issue_id),
    }
    assert _count_decisions(db_session, first_issue.issue_id) == 1
    assert _count_decisions(db_session, second_issue.issue_id) == 0
    assert _count_operation_batches(db_session) == 1


def test_overlap_conflict_reports_every_nested_issue(
    client,
    db_session: Session,
) -> None:
    job_id, issues = _seed_nested_current_issues(db_session)

    response = client.put(
        f"/api/v1/jobs/{job_id}/decisions",
        json=_decision_payload([(issue, "accepted") for issue in issues]),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "overlapping_decisions"
    assert set(response.json()["detail"]["issue_ids"]) == {
        str(issue.issue_id) for issue in issues
    }
    assert _count_operation_batches(db_session) == 0


def test_reversed_concurrent_batches_serialize_without_deadlock(
    app: FastAPI,
    db_session: Session,
    db_session_factory: sessionmaker[Session],
) -> None:
    job_id, first_issue, second_issue = _seed_two_current_issues(db_session)
    first_flushes = [Event(), Event()]
    assignment_lock = Lock()
    assigned_sessions = 0

    def _fresh_session():
        nonlocal assigned_sessions
        session = db_session_factory()
        session.execute(text("SET lock_timeout = '5s'"))
        with assignment_lock:
            session_index = assigned_sessions
            assigned_sessions += 1
        flush_count = 0

        def _rendezvous_after_first_flush(
            _session: Session,
            _flush_context: object,
        ) -> None:
            nonlocal flush_count
            flush_count += 1
            if flush_count != 1:
                return
            first_flushes[session_index].set()
            first_flushes[1 - session_index].wait(timeout=0.75)

        event.listen(session, "after_flush", _rendezvous_after_first_flush)
        try:
            yield session
        finally:
            event.remove(session, "after_flush", _rendezvous_after_first_flush)
            session.close()

    app.dependency_overrides[get_db_session] = _fresh_session
    first_payload = _decision_payload(
        [
            (first_issue, "accepted"),
            (second_issue, "ignored"),
        ]
    )
    second_payload = _decision_payload(
        [
            (second_issue, "ignored"),
            (first_issue, "accepted"),
        ]
    )

    with TestClient(app, raise_server_exceptions=False) as concurrent_client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    concurrent_client.put,
                    f"/api/v1/jobs/{job_id}/decisions",
                    json=payload,
                )
                for payload in (first_payload, second_payload)
            ]
            responses = [future.result(timeout=10) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 409]
    successful = next(response for response in responses if response.status_code == 200)
    conflict = next(response for response in responses if response.status_code == 409)
    assert [outcome["status"] for outcome in successful.json()["outcomes"]] == [
        "applied",
        "applied",
    ]
    assert conflict.json()["detail"]["code"] == "decision_batch_conflict"
    assert set(conflict.json()["detail"]["issue_ids"]) == {
        str(first_issue.issue_id),
        str(second_issue.issue_id),
    }


def test_batch_and_reanalysis_serialize_without_deadlock(
    app: FastAPI,
    db_session: Session,
    db_session_factory: sessionmaker[Session],
) -> None:
    job_id, current_issue, _other_issue = _seed_two_current_issues(db_session)
    batch_flush_reached = Event()
    reanalysis_job_locked = Event()

    def _fresh_session():
        session = db_session_factory()
        session.execute(text("SET lock_timeout = '5s'"))
        flush_count = 0

        def _wait_after_issue_lock_before_first_flush(
            _session: Session,
            _flush_context: object,
            _instances: object,
        ) -> None:
            nonlocal flush_count
            flush_count += 1
            if flush_count != 1:
                return
            batch_flush_reached.set()
            reanalysis_job_locked.wait(timeout=0.75)

        event.listen(session, "before_flush", _wait_after_issue_lock_before_first_flush)
        try:
            yield session
        finally:
            event.remove(session, "before_flush", _wait_after_issue_lock_before_first_flush)
            session.close()

    def _replace_analysis() -> None:
        session = db_session_factory()
        bind = session.get_bind()

        def _signal_job_lock(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            normalized = " ".join(statement.lower().split())
            if "from jobs" in normalized and "for update" in normalized:
                reanalysis_job_locked.set()

        event.listen(bind, "after_cursor_execute", _signal_job_lock)
        try:
            session.execute(text("SET lock_timeout = '5s'"))
            AnalysisRepository(session).replace_analysis(
                job_id,
                _build_document(version=2, text="重新分析"),
                [],
                {},
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            event.remove(bind, "after_cursor_execute", _signal_job_lock)
            session.close()

    app.dependency_overrides[get_db_session] = _fresh_session
    payload = _decision_payload([(current_issue, "accepted")])

    with TestClient(app, raise_server_exceptions=False) as concurrent_client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            batch_future = executor.submit(
                concurrent_client.put,
                f"/api/v1/jobs/{job_id}/decisions",
                json=payload,
            )
            assert batch_flush_reached.wait(timeout=3)
            reanalysis_future = executor.submit(_replace_analysis)

            batch_response = batch_future.result(timeout=10)
            reanalysis_future.result(timeout=10)

    assert batch_response.status_code == 200
    verification_session = db_session_factory()
    try:
        assert AnalysisRepository(verification_session).get_document(job_id) == _build_document(
            version=2,
            text="重新分析",
        )
        assert _count_decisions(verification_session, current_issue.issue_id) == 1
    finally:
        verification_session.close()


def _seed_two_versioned_issues(db_session: Session) -> tuple[UUID, SeededIssue, SeededIssue]:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    repository = AnalysisRepository(db_session)
    stale_document = _build_document(version=1, text="旧问题")
    stale_issue = _build_issue(
        document=stale_document,
        issue_id=UUID("00000000-0000-0000-0000-000000000021"),
        original="旧",
        suggestion="新",
    )
    repository.replace_analysis(job_id, stale_document, [stale_issue], {})
    db_session.commit()

    current_document = _build_document(version=2, text="当前问题")
    current_issue = _build_issue(
        document=current_document,
        issue_id=UUID("00000000-0000-0000-0000-000000000022"),
        original="当前",
        suggestion="最新",
    )
    repository.replace_analysis(job_id, current_document, [current_issue], {})
    db_session.commit()

    current_issue_row = db_session.get(IssueRow, current_issue.issue_id)
    assert current_issue_row is not None
    return (
        job_id,
        SeededIssue(
            issue_id=current_issue_row.issue_id,
            document_version=current_issue_row.document_version,
            accepted_replacement=current_issue.suggestion,
        ),
        SeededIssue(
            issue_id=stale_issue.issue_id,
            document_version=stale_document.version,
            accepted_replacement=stale_issue.suggestion,
        ),
    )


def _seed_two_current_issues(
    db_session: Session,
) -> tuple[UUID, SeededIssue, SeededIssue]:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    repository = AnalysisRepository(db_session)
    document = _build_document(version=1, text="两个问题")
    first_issue = _build_issue(
        document=document,
        issue_id=UUID("00000000-0000-0000-0000-000000000031"),
        original="两个",
        suggestion="双",
    )
    second_issue = _build_issue(
        document=document,
        issue_id=UUID("00000000-0000-0000-0000-000000000032"),
        original="问题",
        suggestion="事项",
    )
    repository.replace_analysis(job_id, document, [first_issue, second_issue], {})
    db_session.commit()

    return (
        job_id,
        SeededIssue(first_issue.issue_id, document.version, first_issue.suggestion),
        SeededIssue(second_issue.issue_id, document.version, second_issue.suggestion),
    )


def _seed_issue_with_suggestions(
    db_session: Session,
) -> tuple[UUID, SeededIssue]:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    repository = AnalysisRepository(db_session)
    document = _build_document(version=1, text="候选建议")
    issue = _build_issue(
        document=document,
        issue_id=UUID("00000000-0000-0000-0000-000000000041"),
        original="候选",
        suggestion="首选",
        alternatives=["备选", "首选", "另一个", "备选"],
    )
    repository.replace_analysis(job_id, document, [issue], {})
    db_session.commit()

    return (
        job_id,
        SeededIssue(issue.issue_id, document.version, issue.suggestion),
    )


def _seed_nested_current_issues(
    db_session: Session,
) -> tuple[UUID, list[SeededIssue]]:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    repository = AnalysisRepository(db_session)
    document = _build_document(version=1, text="四字文本")
    issue_specs = [
        (
            UUID("00000000-0000-0000-0000-000000000061"),
            0,
            4,
            "四字文本",
        ),
        (
            UUID("00000000-0000-0000-0000-000000000062"),
            1,
            2,
            "字",
        ),
        (
            UUID("00000000-0000-0000-0000-000000000063"),
            2,
            3,
            "文",
        ),
    ]
    issues = [
        Issue(
            issue_id=issue_id,
            document_id=document.document_id,
            block_id="p-000001",
            page=1,
            start=start,
            end=end,
            original=original,
            suggestion="替换",
            alternatives=["替换"],
            type="literal",
            severity=IssueSeverity.WARNING,
            layer=CheckCategory.SECURITY.value,
            message="命中规则。",
            rule_id=f"security-{index}",
            source="test",
            source_version="1",
            confidence=1.0,
            auto_fixable=True,
            context=original,
        )
        for index, (issue_id, start, end, original) in enumerate(issue_specs)
    ]
    repository.replace_analysis(job_id, document, issues, {})
    db_session.commit()
    return (
        job_id,
        [
            SeededIssue(issue.issue_id, document.version, issue.suggestion)
            for issue in issues
        ],
    )


def _decision_payload(
    decisions: list[tuple[SeededIssue, str]],
) -> dict[str, list[dict[str, object]]]:
    return {
        "decisions": [
            {
                "issue_id": str(issue.issue_id),
                "issue_version": issue.document_version,
                "expected_revision": 0,
                "action": action,
                "replacement": issue.accepted_replacement if action == "accepted" else None,
                "suggestion_id": None,
            }
            for issue, action in decisions
        ]
    }


def _count_decisions(db_session: Session, issue_id: UUID) -> int:
    return int(
        db_session.scalar(
            select(func.count())
            .select_from(IssueDecisionRow)
            .where(IssueDecisionRow.issue_id == issue_id)
        )
        or 0
    )


def _count_operation_batches(db_session: Session) -> int:
    return int(
        db_session.scalar(select(func.count()).select_from(ReviewOperationBatchRow))
        or 0
    )


def _seed_job(
    db_session: Session,
    *,
    status: JobStatus,
) -> UUID:
    now = datetime.now(UTC)
    job_id = uuid4()
    repository = JobRepository(db_session)
    repository.create_job(
        job_id=job_id,
        source_name="analysis.txt",
        file_type=FileType.TXT.value,
        size_bytes=16,
        storage_key=str(job_id),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    if status != JobStatus.QUEUED:
        repository.transition(
            job_id,
            status,
            100 if status in {JobStatus.COMPLETED, JobStatus.PARTIAL} else 0,
            "处理完成" if status in {JobStatus.COMPLETED, JobStatus.PARTIAL} else "处理中",
        )
    repository.commit()
    return job_id


def _build_document(*, version: int, text: str) -> DocumentModel:
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="analysis.txt",
        version=version,
        blocks=[
            TextBlock(
                block_id="p-000001",
                kind="paragraph",
                text=text,
                page=1,
                paragraph_index=0,
                parent_id=None,
                style={"style_name": "Normal"},
                source_locator={"paragraph_index": 0},
            )
        ],
        metadata={"language": "zh-CN"},
    )


def _build_issue(
    *,
    document: DocumentModel,
    issue_id: UUID,
    original: str,
    suggestion: str | None,
    alternatives: list[str] | None = None,
) -> Issue:
    return Issue(
        issue_id=issue_id,
        document_id=document.document_id,
        block_id="p-000001",
        page=1,
        start=0,
        end=len(original),
        original=original,
        suggestion=suggestion,
        alternatives=(
            [] if suggestion is None else [suggestion]
        )
        if alternatives is None
        else alternatives,
        type="literal",
        severity=IssueSeverity.WARNING,
        layer=CheckCategory.SECURITY.value,
        message="命中规则。",
        rule_id="security-001",
        source="test",
        source_version="1",
        confidence=1.0,
        auto_fixable=suggestion is not None,
        context=original,
    )


@pytest.fixture(autouse=True)
def override_db_session(app: FastAPI, db_session: Session) -> None:
    def _db_session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _db_session_override
