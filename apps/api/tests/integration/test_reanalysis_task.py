from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from text_verification.api.dependencies import get_db_session
from text_verification.checkers.rule_loader import RuleConfigurationError
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.jobs import JobStatus
from text_verification.domain.revisions import (
    DocumentVersionRead,
    DocumentVersionStatus,
    DraftBlock,
)
from text_verification.infrastructure.analysis_repositories import AnalysisRepository
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
    )
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
    )
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
    )
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
    revisions.complete_analysis(newer_child.version_id, _build_document(["第三版"], version=3), [], {})

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
