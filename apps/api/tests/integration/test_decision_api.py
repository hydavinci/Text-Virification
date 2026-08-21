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
from text_verification.infrastructure.orm import IssueDecisionRow, IssueRow
from text_verification.infrastructure.repositories import JobRepository


@dataclass(frozen=True)
class SeededIssue:
    issue_id: UUID
    document_version: int
    accepted_replacement: str | None


def test_batch_decisions_return_per_item_outcomes_in_request_order(
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

    assert response.status_code == 200
    payload = response.json()
    assert [item["status"] for item in payload["outcomes"]] == ["applied", "conflict"]
    assert payload["outcomes"][0]["issue_id"] == str(current_issue.issue_id)
    assert payload["outcomes"][0]["decision"]["issue_id"] == str(current_issue.issue_id)
    assert payload["outcomes"][0]["decision"]["issue_version"] == current_issue.document_version
    assert payload["outcomes"][0]["decision"]["action"] == "accepted"
    assert payload["outcomes"][0]["decision"]["replacement"] == current_issue.accepted_replacement
    assert payload["outcomes"][1] == {
        "issue_id": str(stale_issue.issue_id),
        "status": "conflict",
        "code": "stale_issue_version",
        "decision": None,
    }
    assert _count_decisions(db_session, current_issue.issue_id) == 1


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


def test_batch_decisions_return_ordered_applied_and_invalid_outcomes_and_persist_sibling(
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

    assert response.status_code == 200
    assert [outcome["status"] for outcome in response.json()["outcomes"]] == [
        "applied",
        "invalid",
    ]
    assert response.json()["outcomes"][1] == {
        "issue_id": str(missing_issue_id),
        "status": "invalid",
        "code": "issue_not_found",
        "decision": None,
    }
    assert _count_decisions(db_session, current_issue.issue_id) == 1


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
            (second_issue, "accepted"),
            (first_issue, "ignored"),
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

    assert [response.status_code for response in responses] == [200, 200]
    assert all(
        [outcome["status"] for outcome in response.json()["outcomes"]]
        == ["applied", "applied"]
        for response in responses
    )


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
        alternatives=[] if suggestion is None else [suggestion],
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
