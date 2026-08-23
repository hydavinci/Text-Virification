from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from text_verification.api.dependencies import get_db_session
from text_verification.checkers.models import (
    CheckCategory,
    CheckerProgress,
    CheckOptions,
    CheckRunResult,
    LiteralRule,
)
from text_verification.checkers.rule_checker import RuleChecker
from text_verification.checkers.rule_loader import RuleConfigurationError
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.jobs import JobStatus
from text_verification.domain.ports import CheckContext
from text_verification.domain.revisions import (
    DocumentVersionRead,
    DocumentVersionStatus,
    DraftBlock,
)
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
from text_verification.infrastructure.orm import DocumentVersionRow, IssueRow, JobRow
from text_verification.infrastructure.repositories import JobRepository
from text_verification.infrastructure.revision_repository import RevisionRepository


@dataclass(frozen=True)
class SeededEditDraft:
    job_id: UUID
    parent: DocumentVersionRead
    draft: object
    base_document: DocumentModel


@pytest.fixture(autouse=True)
def override_db_session(app: FastAPI, db_session: Session) -> None:
    def _db_session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _db_session_override


@pytest.fixture
def celery_eager() -> None:
    from text_verification.workers.celery_app import celery_app

    original_values = {
        "task_always_eager": celery_app.conf.task_always_eager,
        "task_store_eager_result": celery_app.conf.task_store_eager_result,
        "task_eager_propagates": celery_app.conf.task_eager_propagates,
    }
    celery_app.conf.update(
        task_always_eager=True,
        task_store_eager_result=False,
        task_eager_propagates=False,
    )
    try:
        yield
    finally:
        celery_app.conf.update(**original_values)


@pytest.fixture
def seeded_edit_draft(db_session: Session) -> SeededEditDraft:
    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    revisions = RevisionRepository(db_session)
    base_document = _build_document(["第一段", "第二段"], version=1)
    parent = revisions.create_queued_version(
        job_id,
        parent_version_id=None,
        reason="upload",
        idempotency_key=None,
    )
    parent = revisions.complete_analysis(parent.version_id, base_document, [], {})
    draft = revisions.create_draft(job_id, parent.version_id)
    draft = revisions.update_draft(
        job_id,
        draft.draft_id,
        expected_revision=draft.revision,
        blocks=[
            DraftBlock(block_id="p-000001", text="第一段-已修改"),
            DraftBlock(block_id="p-000002", text="第二段"),
        ],
    )
    db_session.commit()
    return SeededEditDraft(
        job_id=job_id,
        parent=parent,
        draft=draft,
        base_document=base_document,
    )


def test_reanalysis_success_activates_new_version_and_consumes_draft(
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    from text_verification.workers.reanalysis_tasks import process_document_version

    _configure_reanalysis_worker(monkeypatch, db_session)
    revisions = RevisionRepository(db_session)
    version = revisions.create_reanalysis_version(
        seeded_edit_draft.draft.draft_id,
        expected_draft_revision=seeded_edit_draft.draft.revision,
        idempotency_key="request-1",
    ).version
    db_session.commit()

    result = process_document_version.delay(str(version.version_id))

    assert result.successful()
    db_session.expire_all()
    stored_version = revisions.get_version(version.version_id)
    assert stored_version is not None
    assert stored_version.status == DocumentVersionStatus.SUCCEEDED
    assert stored_version.revision_number == 2
    active_version = revisions.get_active_version(seeded_edit_draft.job_id)
    assert active_version is not None
    assert active_version.version_id == version.version_id
    draft = revisions.get_draft(seeded_edit_draft.job_id, seeded_edit_draft.draft.draft_id)
    assert draft is not None
    assert draft.consumed_at is not None
    document = AnalysisRepository(db_session).get_document(
        seeded_edit_draft.job_id,
        version.version_id,
    )
    assert document is not None
    assert document.version == stored_version.revision_number
    assert [block.text for block in document.blocks] == ["第一段-已修改", "第二段"]
    assert [block.source_locator for block in document.blocks] == [
        block.source_locator for block in seeded_edit_draft.base_document.blocks
    ]


def test_reanalysis_persists_unchanged_rule_finding_with_new_issue_id(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    from text_verification.workers.reanalysis_tasks import process_document_version

    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    checker = RuleChecker(
        LiteralRule(
            id="ad-001",
            category=CheckCategory.SECURITY,
            severity="warning",
            pattern="绝对领先",
            suggestion="领先",
            message="避免使用绝对化表述。",
            scenarios=frozenset(),
            auto_fixable=True,
        )
    )
    revisions = RevisionRepository(db_session)
    base_document = _build_document(["这是绝对领先"], version=1)
    base_issues = checker.check(base_document, CheckContext((), ()))
    parent = revisions.create_queued_version(
        job_id,
        parent_version_id=None,
        reason="upload",
        idempotency_key=None,
    )
    revisions.complete_analysis(parent.version_id, base_document, base_issues, {})
    draft = revisions.create_draft(job_id, parent.version_id)
    version = revisions.create_reanalysis_version(
        draft.draft_id,
        expected_draft_revision=draft.revision,
        idempotency_key="unchanged-finding",
    ).version
    db_session.commit()

    class PersistingRuleRunner:
        def __init__(self, session: Session) -> None:
            self._session = session

        def analyze_document(self, version_id, document, options) -> CheckRunResult:
            del options
            issues = checker.check(document, CheckContext((), ()))
            RevisionRepository(self._session).mark_analyzing(version_id)
            result = CheckRunResult(
                issues=issues,
                completed_categories={CheckCategory.SECURITY},
                failures={},
            )
            RevisionRepository(self._session).complete_analysis(
                version_id,
                document,
                result.issues,
                result.failures,
            )
            return result

    _configure_reanalysis_worker(
        monkeypatch,
        db_session,
        runner_factory=lambda session, repository: PersistingRuleRunner(session),
    )

    result = process_document_version.delay(str(version.version_id))

    assert result.successful()
    db_session.expire_all()
    stored_version = revisions.get_version(version.version_id)
    assert stored_version is not None
    assert stored_version.status == DocumentVersionStatus.SUCCEEDED
    stored_issue_ids = list(
        db_session.scalars(
            select(IssueRow.issue_id).where(IssueRow.job_id == job_id).order_by(IssueRow.issue_id)
        )
    )
    assert len(stored_issue_ids) == 2
    assert stored_issue_ids[0] != stored_issue_ids[1]


def test_reanalysis_failure_keeps_parent_active_and_draft_editable(
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    from text_verification.workers.reanalysis_tasks import process_document_version

    attempts = 0

    class FailingRunner:
        def analyze_document(self, version_id, document, options) -> None:
            del version_id, document, options
            nonlocal attempts
            attempts += 1
            raise RuleConfigurationError(r"C:\secret\rules.json: invalid")

    _configure_reanalysis_worker(
        monkeypatch,
        db_session,
        runner_factory=lambda session, repository: FailingRunner(),
    )
    revisions = RevisionRepository(db_session)
    version = revisions.create_reanalysis_version(
        seeded_edit_draft.draft.draft_id,
        expected_draft_revision=seeded_edit_draft.draft.revision,
        idempotency_key="request-failure",
    ).version
    db_session.commit()

    result = process_document_version.delay(str(version.version_id))

    assert result.successful()
    assert attempts == 1
    db_session.expire_all()
    stored_version = revisions.get_version(version.version_id)
    assert stored_version is not None
    assert stored_version.status == DocumentVersionStatus.FAILED
    assert stored_version.failure_code == "invalid_rule_configuration"
    active_version = revisions.get_active_version(seeded_edit_draft.job_id)
    assert active_version is not None
    assert active_version.version_id == seeded_edit_draft.parent.version_id
    draft = revisions.get_draft(seeded_edit_draft.job_id, seeded_edit_draft.draft.draft_id)
    assert draft is not None
    assert draft.consumed_at is None

    updated = revisions.update_draft(
        seeded_edit_draft.job_id,
        seeded_edit_draft.draft.draft_id,
        expected_revision=draft.revision,
        blocks=[
            DraftBlock(block_id="p-000001", text="第一段-再次修改"),
            DraftBlock(block_id="p-000002", text="第二段"),
        ],
    )
    db_session.commit()

    assert updated.revision == draft.revision + 1


def test_reanalysis_route_is_idempotent_and_replays_version_events(
    client,
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    _configure_reanalysis_worker(monkeypatch, db_session)
    url = (
        f"/api/v1/jobs/{seeded_edit_draft.job_id}/drafts/"
        f"{seeded_edit_draft.draft.draft_id}/reanalyze"
    )
    payload = {
        "expected_draft_revision": seeded_edit_draft.draft.revision,
        "idempotency_key": "018f6e36-7f5d-7d7a-a7b5-5f05db25af68",
    }

    first = client.post(url, json=payload)
    second = client.post(url, json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["version"]["version_id"] == second.json()["version"]["version_id"]
    assert first.json()["events_url"] == second.json()["events_url"]

    stream = client.get(
        first.json()["events_url"],
        headers={"Last-Event-ID": "1"},
    )

    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "id: 2" in stream.text
    assert '"status":"analyzing"' in stream.text
    assert '"status":"succeeded"' in stream.text
    assert "event: done" in stream.text
    assert str(seeded_edit_draft.draft.draft_id) not in stream.text
    assert payload["idempotency_key"] not in stream.text


def test_exact_duplicate_reanalysis_returns_existing_version_during_broker_outage(
    client,
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.api.routes import versions as version_routes

    idempotency_key = "duplicate-during-broker-outage"
    existing = RevisionRepository(db_session).create_reanalysis_version(
        seeded_edit_draft.draft.draft_id,
        expected_draft_revision=seeded_edit_draft.draft.revision,
        idempotency_key=idempotency_key,
    ).version
    db_session.commit()
    dispatch_calls = 0

    def unavailable_broker(version_id: str) -> None:
        del version_id
        nonlocal dispatch_calls
        dispatch_calls += 1
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        version_routes,
        "dispatch_process_document_version",
        unavailable_broker,
    )

    response = client.post(
        f"/api/v1/jobs/{seeded_edit_draft.job_id}/drafts/"
        f"{seeded_edit_draft.draft.draft_id}/reanalyze",
        json={
            "expected_draft_revision": seeded_edit_draft.draft.revision,
            "idempotency_key": idempotency_key,
        },
    )

    assert response.status_code == 202
    assert response.json()["version"]["version_id"] == str(existing.version_id)
    assert dispatch_calls == 0


def test_dispatch_failure_retries_terminalization_and_persists_one_failed_event(
    client,
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.api.routes import versions as version_routes

    monkeypatch.setattr(
        version_routes,
        "dispatch_process_document_version",
        lambda version_id: (_ for _ in ()).throw(RuntimeError(f"broker failed: {version_id}")),
    )
    original_fail_version = RevisionRepository.fail_version
    fail_version_calls = 0

    def flaky_fail_version(self, version_id, code, message):
        nonlocal fail_version_calls
        fail_version_calls += 1
        if fail_version_calls == 1:
            raise RuntimeError("transient fail_version failure")
        return original_fail_version(self, version_id, code, message)

    monkeypatch.setattr(RevisionRepository, "fail_version", flaky_fail_version)

    response = client.post(
        f"/api/v1/jobs/{seeded_edit_draft.job_id}/drafts/"
        f"{seeded_edit_draft.draft.draft_id}/reanalyze",
        json={
            "expected_draft_revision": seeded_edit_draft.draft.revision,
            "idempotency_key": "dispatch-terminalization-retry",
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "reanalysis_dispatch_failed"
    assert fail_version_calls == 2
    db_session.expire_all()
    versions = RevisionRepository(db_session).list_versions(seeded_edit_draft.job_id)
    failed = versions[-1]
    assert failed.status == DocumentVersionStatus.FAILED
    assert failed.failure_code == "reanalysis_dispatch_failed"
    assert [
        event.status
        for event in RevisionRepository(db_session).list_version_events_after(
            failed.version_id,
            0,
        )
    ].count(DocumentVersionStatus.FAILED) == 1


def test_dispatch_failure_propagates_unrecovered_terminalization_failure(
    client,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.api.routes import versions as version_routes

    monkeypatch.setattr(
        version_routes,
        "dispatch_process_document_version",
        lambda version_id: (_ for _ in ()).throw(RuntimeError(f"broker failed: {version_id}")),
    )
    fail_version_calls = 0

    def unavailable_fail_version(self, version_id, code, message):
        del self, version_id, code, message
        nonlocal fail_version_calls
        fail_version_calls += 1
        raise RuntimeError("terminal persistence unavailable")

    monkeypatch.setattr(RevisionRepository, "fail_version", unavailable_fail_version)

    response = client.post(
        f"/api/v1/jobs/{seeded_edit_draft.job_id}/drafts/"
        f"{seeded_edit_draft.draft.draft_id}/reanalyze",
        json={
            "expected_draft_revision": seeded_edit_draft.draft.revision,
            "idempotency_key": "dispatch-terminalization-unavailable",
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "reanalysis_dispatch_recovery_failed",
        "message": "重新分析调度失败且状态恢复未完成，请稍后重试。",
    }
    assert fail_version_calls == 3


def test_reanalysis_route_rejects_stale_expected_draft_revision(
    client,
    seeded_edit_draft: SeededEditDraft,
) -> None:
    response = client.post(
        f"/api/v1/jobs/{seeded_edit_draft.job_id}/drafts/{seeded_edit_draft.draft.draft_id}/reanalyze",
        json={
            "expected_draft_revision": seeded_edit_draft.draft.revision - 1,
            "idempotency_key": "stale-draft-reanalysis",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "stale_draft_revision",
        "message": "草稿已更新，请刷新后重试。",
        "current_revision": seeded_edit_draft.draft.revision,
    }


def test_reanalysis_submission_rejects_expired_job(
    client,
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification.api.routes import versions as version_routes

    job = db_session.get(JobRow, seeded_edit_draft.job_id)
    assert job is not None
    job.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    def reject_dispatch(version_id: str) -> None:
        raise RuntimeError(f"expired version dispatched: {version_id}")

    monkeypatch.setattr(
        version_routes,
        "dispatch_process_document_version",
        reject_dispatch,
    )

    response = client.post(
        f"/api/v1/jobs/{seeded_edit_draft.job_id}/drafts/"
        f"{seeded_edit_draft.draft.draft_id}/reanalyze",
        json={
            "expected_draft_revision": seeded_edit_draft.draft.revision,
            "idempotency_key": "expired-submission",
        },
    )

    assert response.status_code == 410
    assert response.json()["detail"] == {
        "code": "job_expired",
        "message": "作业已过期，请重新上传文件。",
    }
    assert len(RevisionRepository(db_session).list_versions(seeded_edit_draft.job_id)) == 1


def test_worker_terminalizes_version_when_job_expires_after_submission(
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    from text_verification.workers.reanalysis_tasks import process_document_version

    runner_calls = 0

    def runner_factory(session, repository):
        del session, repository
        nonlocal runner_calls
        runner_calls += 1
        raise AssertionError("expired reanalysis must not build a runner")

    _configure_reanalysis_worker(
        monkeypatch,
        db_session,
        runner_factory=runner_factory,
    )
    revisions = RevisionRepository(db_session)
    version = revisions.create_reanalysis_version(
        seeded_edit_draft.draft.draft_id,
        expected_draft_revision=seeded_edit_draft.draft.revision,
        idempotency_key="worker-expiry-race",
    ).version
    db_session.commit()
    job = db_session.get(JobRow, seeded_edit_draft.job_id)
    assert job is not None
    job.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    result = process_document_version.delay(str(version.version_id))

    assert result.successful()
    assert runner_calls == 0
    db_session.expire_all()
    stored = revisions.get_version(version.version_id)
    assert stored is not None
    assert stored.status == DocumentVersionStatus.FAILED
    assert stored.failure_code == "job_expired"
    assert [
        event.status for event in revisions.list_version_events_after(version.version_id, 0)
    ].count(DocumentVersionStatus.FAILED) == 1


def test_version_event_stream_terminates_as_expired_for_expired_job(
    client,
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_reanalysis_worker(monkeypatch, db_session)
    revisions = RevisionRepository(db_session)
    version = revisions.create_reanalysis_version(
        seeded_edit_draft.draft.draft_id,
        expected_draft_revision=seeded_edit_draft.draft.revision,
        idempotency_key="expired-version-stream",
    ).version
    db_session.commit()
    revisions.fail_version(
        version.version_id,
        code="job_expired",
        message="作业已过期，请重新上传文件。",
    )
    job = db_session.get(JobRow, seeded_edit_draft.job_id)
    assert job is not None
    job.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    response = client.get(
        f"/api/v1/jobs/{seeded_edit_draft.job_id}/versions/{version.version_id}/events"
    )

    assert response.status_code == 200
    assert "event: expired" in response.text
    assert "event: done" not in response.text


def test_reanalysis_idempotency_key_accepts_255_character_boundary(
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
) -> None:
    revisions = RevisionRepository(db_session)
    idempotency_key = "k" * 255

    first = revisions.create_reanalysis_version(
        seeded_edit_draft.draft.draft_id,
        expected_draft_revision=seeded_edit_draft.draft.revision,
        idempotency_key=idempotency_key,
    ).version
    db_session.commit()
    second = revisions.create_reanalysis_version(
        seeded_edit_draft.draft.draft_id,
        expected_draft_revision=seeded_edit_draft.draft.revision,
        idempotency_key=idempotency_key,
    ).version

    stored = db_session.get(DocumentVersionRow, first.version_id)
    assert stored is not None
    assert stored.idempotency_key is not None
    assert len(stored.idempotency_key) <= 255
    assert second.version_id == first.version_id


def test_version_progress_is_visible_across_sessions_before_atomic_completion(
    db_session: Session,
    db_session_factory: sessionmaker[Session],
) -> None:
    from text_verification.workers.pipeline import PipelineRunner

    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    revisions = RevisionRepository(db_session)
    version = revisions.create_queued_version(
        job_id,
        parent_version_id=None,
        reason="upload",
        idempotency_key=None,
    )
    db_session.commit()
    observer = db_session_factory()
    observed_statuses: list[DocumentVersionStatus] = []

    class ObservingCheckerRegistry:
        def run(self, document, context, options, on_progress=None) -> CheckRunResult:
            del document, context, options
            assert on_progress is not None
            on_progress(
                CheckerProgress(
                    current_category=CheckCategory.CHARACTER,
                    completed_categories=(CheckCategory.CHARACTER,),
                    issue_count=0,
                )
            )
            observer.expire_all()
            observer_revisions = RevisionRepository(observer)
            visible_statuses = [
                event.status
                for event in observer_revisions.list_version_events_after(
                    version.version_id,
                    0,
                )
            ]
            observer.rollback()
            assert visible_statuses == [
                DocumentVersionStatus.QUEUED,
                DocumentVersionStatus.ANALYZING,
                DocumentVersionStatus.ANALYZING,
            ]
            observed_version = observer_revisions.get_version(version.version_id)
            assert observed_version is not None
            observed_statuses.append(observed_version.status)
            observer.rollback()
            assert (
                AnalysisRepository(observer).get_document(job_id, version.version_id)
                is None
            )
            return CheckRunResult(
                issues=[],
                completed_categories={CheckCategory.CHARACTER},
                failures={},
            )

    runner = PipelineRunner(
        JobRepository(db_session),
        AnalysisRepository(db_session),
        None,
        None,
        ObservingCheckerRegistry(),
        revision_repository=revisions,
    )
    document = _build_document(["可见进度"], version=version.revision_number)

    runner.analyze_document(
        version.version_id,
        document,
        CheckOptions(enabled_categories=[CheckCategory.CHARACTER]),
    )

    observer.expire_all()
    visible_statuses = [
        event.status
        for event in RevisionRepository(observer).list_version_events_after(
            version.version_id,
            0,
        )
    ]
    visible_document = AnalysisRepository(observer).get_document(job_id, version.version_id)
    observer.rollback()
    assert visible_statuses[-1] == DocumentVersionStatus.ANALYZING
    assert visible_document is None

    db_session.commit()
    observer.expire_all()
    after_commit = RevisionRepository(observer).get_version(version.version_id)
    assert after_commit is not None
    assert after_commit.status == DocumentVersionStatus.SUCCEEDED
    assert AnalysisRepository(observer).get_document(job_id, version.version_id) is not None
    assert observed_statuses == [DocumentVersionStatus.ANALYZING]
    observer.close()


def test_process_document_version_retries_unexpected_failures_then_persists_one_terminal_failure(
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    from text_verification.workers.reanalysis_tasks import process_document_version

    attempts = 0

    class ExplodingRunner:
        def analyze_document(self, version_id, document, options) -> None:
            del version_id, document, options
            nonlocal attempts
            attempts += 1
            raise RuntimeError("transient checker failure")

    _configure_reanalysis_worker(
        monkeypatch,
        db_session,
        runner_factory=lambda session, repository: ExplodingRunner(),
    )
    revisions = RevisionRepository(db_session)
    version = revisions.create_reanalysis_version(
        seeded_edit_draft.draft.draft_id,
        expected_draft_revision=seeded_edit_draft.draft.revision,
        idempotency_key="request-retry",
    ).version
    db_session.commit()

    result = process_document_version.delay(str(version.version_id))

    assert result.failed()
    assert isinstance(result.result, RuntimeError)
    assert str(result.result) == "transient checker failure"
    assert attempts == 3
    db_session.expire_all()
    stored_version = revisions.get_version(version.version_id)
    assert stored_version is not None
    assert stored_version.status == DocumentVersionStatus.FAILED
    assert stored_version.failure_code == "reanalysis_failed"
    assert stored_version.failure_message == "重新分析失败，请稍后重试。"
    assert [
        event.status for event in revisions.list_version_events_after(version.version_id, 0)
    ].count(DocumentVersionStatus.FAILED) == 1
    active_version = revisions.get_active_version(seeded_edit_draft.job_id)
    assert active_version is not None
    assert active_version.version_id == seeded_edit_draft.parent.version_id
    draft = revisions.get_draft(seeded_edit_draft.job_id, seeded_edit_draft.draft.draft_id)
    assert draft is not None
    assert draft.consumed_at is None


def test_expected_failure_retries_fail_version_persistence_without_reanalyzing(
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    from text_verification.workers.reanalysis_tasks import process_document_version

    analysis_attempts = 0

    class InvalidConfigurationRunner:
        def analyze_document(self, version_id, document, options) -> None:
            del version_id, document, options
            nonlocal analysis_attempts
            analysis_attempts += 1
            raise RuleConfigurationError("invalid rules")

    _configure_reanalysis_worker(
        monkeypatch,
        db_session,
        runner_factory=lambda session, repository: InvalidConfigurationRunner(),
    )
    revisions = RevisionRepository(db_session)
    version = revisions.create_reanalysis_version(
        seeded_edit_draft.draft.draft_id,
        expected_draft_revision=seeded_edit_draft.draft.revision,
        idempotency_key="retry-fail-version-persistence",
    ).version
    db_session.commit()
    original_fail_version = RevisionRepository.fail_version
    fail_version_calls = 0

    def flaky_fail_version(self, version_id, code, message):
        nonlocal fail_version_calls
        fail_version_calls += 1
        if fail_version_calls == 1:
            raise RuntimeError("transient fail_version failure")
        return original_fail_version(self, version_id, code, message)

    monkeypatch.setattr(RevisionRepository, "fail_version", flaky_fail_version)

    result = process_document_version.delay(str(version.version_id))

    assert result.successful()
    assert analysis_attempts == 1
    assert fail_version_calls == 2
    db_session.expire_all()
    stored = revisions.get_version(version.version_id)
    assert stored is not None
    assert stored.status == DocumentVersionStatus.FAILED
    assert [
        event.status for event in revisions.list_version_events_after(version.version_id, 0)
    ].count(DocumentVersionStatus.FAILED) == 1


def test_expected_failure_retries_terminal_commit_without_duplicate_event(
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    from text_verification.workers.reanalysis_tasks import process_document_version

    class InvalidConfigurationRunner:
        def analyze_document(self, version_id, document, options) -> None:
            del version_id, document, options
            raise RuleConfigurationError("invalid rules")

    _configure_reanalysis_worker(
        monkeypatch,
        db_session,
        runner_factory=lambda session, repository: InvalidConfigurationRunner(),
    )
    revisions = RevisionRepository(db_session)
    version = revisions.create_reanalysis_version(
        seeded_edit_draft.draft.draft_id,
        expected_draft_revision=seeded_edit_draft.draft.revision,
        idempotency_key="retry-terminal-commit",
    ).version
    db_session.commit()
    original_commit = Session.commit
    commit_calls = 0

    def flaky_commit(self) -> None:
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 1:
            raise RuntimeError("transient terminal commit failure")
        original_commit(self)

    monkeypatch.setattr(Session, "commit", flaky_commit)

    result = process_document_version.delay(str(version.version_id))

    assert result.successful()
    assert commit_calls == 2
    db_session.expire_all()
    stored = revisions.get_version(version.version_id)
    assert stored is not None
    assert stored.status == DocumentVersionStatus.FAILED
    assert [
        event.status for event in revisions.list_version_events_after(version.version_id, 0)
    ].count(DocumentVersionStatus.FAILED) == 1


def test_unrecovered_terminal_persistence_failure_is_propagated_without_reanalysis(
    db_session: Session,
    seeded_edit_draft: SeededEditDraft,
    monkeypatch: pytest.MonkeyPatch,
    celery_eager,
) -> None:
    from text_verification.workers.reanalysis_tasks import process_document_version

    analysis_attempts = 0

    class InvalidConfigurationRunner:
        def analyze_document(self, version_id, document, options) -> None:
            del version_id, document, options
            nonlocal analysis_attempts
            analysis_attempts += 1
            raise RuleConfigurationError("invalid rules")

    _configure_reanalysis_worker(
        monkeypatch,
        db_session,
        runner_factory=lambda session, repository: InvalidConfigurationRunner(),
    )
    revisions = RevisionRepository(db_session)
    version = revisions.create_reanalysis_version(
        seeded_edit_draft.draft.draft_id,
        expected_draft_revision=seeded_edit_draft.draft.revision,
        idempotency_key="unrecovered-terminal-persistence",
    ).version
    db_session.commit()
    fail_version_calls = 0

    def unavailable_fail_version(self, version_id, code, message):
        del self, version_id, code, message
        nonlocal fail_version_calls
        fail_version_calls += 1
        raise RuntimeError("terminal persistence unavailable")

    monkeypatch.setattr(RevisionRepository, "fail_version", unavailable_fail_version)

    result = process_document_version.delay(str(version.version_id))

    assert result.failed()
    assert type(result.result).__name__ == "VersionFailurePersistenceError"
    assert analysis_attempts == 1
    assert fail_version_calls == 3
    db_session.expire_all()
    stored = revisions.get_version(version.version_id)
    assert stored is not None
    assert stored.status == DocumentVersionStatus.QUEUED


def test_complete_analysis_rejects_outdated_child_activation(db_session: Session) -> None:
    from text_verification.infrastructure.revision_repository import StaleDocumentVersionError

    job_id = _seed_job(db_session, status=JobStatus.COMPLETED)
    revisions = RevisionRepository(db_session)
    parent = revisions.create_queued_version(
        job_id,
        parent_version_id=None,
        reason="upload",
        idempotency_key=None,
    )
    revisions.complete_analysis(parent.version_id, _build_document(["初版"], version=1), [], {})
    older_child = revisions.create_queued_version(
        job_id,
        parent_version_id=parent.version_id,
        reason="edited",
        idempotency_key="older-child",
    )
    newer_child = revisions.create_queued_version(
        job_id,
        parent_version_id=parent.version_id,
        reason="edited",
        idempotency_key="newer-child",
    )
    revisions.complete_analysis(
        newer_child.version_id,
        _build_document(["第三版"], version=3),
        [],
        {},
    )

    with pytest.raises(StaleDocumentVersionError):
        revisions.complete_analysis(
            older_child.version_id,
            _build_document(["第二版"], version=2),
            [],
            {},
        )


def _configure_reanalysis_worker(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    *,
    runner_factory=None,
) -> None:
    from text_verification.api.routes import versions as version_routes
    from text_verification.workers import reanalysis_tasks

    session_factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    monkeypatch.setattr(reanalysis_tasks, "SESSION_FACTORY_PROVIDER", lambda: session_factory)
    monkeypatch.setattr(version_routes, "SESSION_FACTORY_PROVIDER", lambda: session_factory)
    if runner_factory is not None:
        monkeypatch.setattr(reanalysis_tasks, "RUNNER_FACTORY", runner_factory)


def _seed_job(db_session: Session, *, status: JobStatus) -> UUID:
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
            error_code="pipeline_failed" if status == JobStatus.FAILED else None,
            error_message="处理失败" if status == JobStatus.FAILED else None,
        )
    repository.commit()
    return job_id


def _build_document(texts: list[str], *, version: int) -> DocumentModel:
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="analysis.txt",
        version=version,
        blocks=[
            TextBlock(
                block_id=f"p-{index + 1:06d}",
                kind="paragraph",
                text=text,
                page=index + 1,
                paragraph_index=index,
                parent_id=None,
                style={"style_name": "Normal"},
                source_locator={"paragraph_index": index},
            )
            for index, text in enumerate(texts)
        ],
        metadata={"language": "zh-CN"},
    )
