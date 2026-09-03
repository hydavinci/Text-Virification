from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

import pytest

from text_verification.application.errors import VerificationError
from text_verification.application.recheck_provenance import (
    RecheckGrantBinding,
    RecheckProvenanceGrantService,
)
from text_verification.application.review_revision import ReviewRevisionService
from text_verification.domain.documents import FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.verification import (
    DocumentRevisionKind,
    PersistedDocumentRevision,
    RecheckProvenance,
    ReviewRevisionDraft,
    ReviewRevisionSubmission,
    Scenario,
    VerificationAnalysisMode,
    VerificationDegradation,
    VerificationExecutionMode,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)
from text_verification.infrastructure.verification_repository import (
    JobResultSnapshot,
    JobResultState,
)

JOB_ID = UUID("10000000-0000-4000-8000-000000000001")
DOCUMENT_ID = UUID("20000000-0000-4000-8000-000000000002")
RUN_ID = UUID("30000000-0000-4000-8000-000000000003")
REVISION_ID = UUID("40000000-0000-4000-8000-000000000004")
CREATED_AT = datetime(2026, 9, 3, 4, 0, tzinfo=UTC)


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, ReviewRevisionDraft, datetime]] = []
        self.provenance_calls: list[object | None] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.error: Exception | None = None
        self.result_snapshot = JobResultSnapshot(
            JobResultState.READY,
            original_result(),
        )

    def read_revision_result(
        self,
        job_id: UUID,
        verification_run_id: UUID,
    ) -> VerificationResult:
        assert job_id == JOB_ID
        assert verification_run_id == RUN_ID
        assert self.result_snapshot.result is not None
        return self.result_snapshot.result

    def persist_review_revision(
        self,
        job_id: UUID,
        draft: ReviewRevisionDraft,
        *,
        created_at: datetime,
        verified_provenance: object | None = None,
    ) -> PersistedDocumentRevision:
        self.calls.append((job_id, draft, created_at))
        self.provenance_calls.append(verified_provenance)
        if self.error is not None:
            raise self.error
        persisted = PersistedDocumentRevision(
            revision_id=draft.revision_id,
            document_id=draft.document_id,
            verification_run_id=draft.verification_run_id,
            source_version=draft.source_version,
            revision_number=1,
            created_at=created_at,
            parent_revision_id=draft.parent_revision_id,
            persistence_state="persisted",
            kind=draft.kind,
            text=draft.text,
        )
        return persisted.model_copy(
            update={"verified_provenance": verified_provenance}
        )

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


def draft() -> ReviewRevisionDraft:
    return ReviewRevisionDraft(
        revision_id=REVISION_ID,
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
        source_version="sha256:source",
        parent_revision_id=None,
        kind=DocumentRevisionKind.REVIEW,
        text="修订文本",
    )


def original_result() -> VerificationResult:
    text = "帐号测试"
    block = TextBlock(
        block_id="p-0",
        kind="paragraph",
        text=text,
        global_start=0,
        global_end=len(text),
        block_start=0,
        block_end=len(text),
        page=None,
        paragraph_index=0,
        table_index=None,
        row_index=None,
        cell_index=None,
        bbox=None,
        parent_id=None,
        style={},
        source_locator={},
    )
    issue = Issue(
        issue_id=UUID("70000000-0000-4000-8000-000000000007"),
        document_id=DOCUMENT_ID,
        verification_run_id=RUN_ID,
        block_id=block.block_id,
        page=None,
        start=0,
        end=2,
        block_start=0,
        block_end=2,
        original="帐号",
        suggestion="账号",
        alternatives=[],
        type="typo",
        severity=IssueSeverity.WARNING,
        layer="character",
        message="疑似错别字",
        description="建议使用规范写法",
        rule_id="cn_typo",
        rule_version="1",
        source="local",
        source_version="1",
        confidence=0.9,
        auto_fixable=True,
        context=text,
    )
    return VerificationResult(
        verification_run_id=RUN_ID,
        document_id=DOCUMENT_ID,
        source_version="sha256:source",
        source_name="sample.txt",
        file_type=FileType.TXT,
        scenario=Scenario.GENERAL,
        text=text,
        blocks=(block,),
        parser_name="plain-text",
        parser_version="1",
        stats=VerificationStatistics(
            char_count=len(text),
            char_count_no_space=len(text),
            line_count=1,
            paragraph_count=1,
            language="zh",
            primary_count=len(text),
            primary_label="总字数",
        ),
        issues=(issue,),
        summary=VerificationSummary(
            total=1,
            by_type={"typo": 1},
            by_severity={"warning": 1},
            by_rule={"cn_typo": 1},
            by_layer={"character": 1},
        ),
        execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
        analysis_mode=VerificationAnalysisMode.LOCAL_ONLY,
        degradation=VerificationDegradation(),
    )


def base_result_payload(
    *,
    document_id: UUID = DOCUMENT_ID,
    verification_run_id: UUID = RUN_ID,
    source_version: str = "sha256:source",
) -> dict[str, str]:
    return {
        "document_id": str(document_id),
        "verification_run_id": str(verification_run_id),
        "source_version": source_version,
    }


def submission(
    *,
    text: str = "帐号测试",
    kind: DocumentRevisionKind = DocumentRevisionKind.REVIEW,
    base_result: dict[str, str] | None = None,
    recheck_provenance: RecheckProvenance | None = None,
) -> ReviewRevisionSubmission:
    return ReviewRevisionSubmission.model_validate(
        {
            **draft().model_copy(
                update={
                    "kind": kind,
                    "text": text,
                }
            ).model_dump(mode="json"),
            "base_result": base_result or base_result_payload(),
            **(
                {}
                if recheck_provenance is None
                else {
                    "recheck_provenance": recheck_provenance.model_dump(
                        mode="json"
                    )
                }
            ),
        }
    )


def service(
    repository: RecordingRepository,
    *,
    max_revision_bytes: int = 25 * 1024 * 1024,
    grant_service: RecheckProvenanceGrantService | None = None,
) -> ReviewRevisionService:
    @contextmanager
    def factory() -> Iterator[RecordingRepository]:
        yield repository

    return ReviewRevisionService(
        factory,
        now_factory=lambda: CREATED_AT,
        max_revision_bytes=max_revision_bytes,
        recheck_grant_service=grant_service,
    )


def test_persists_browser_revision_identity_and_commits_once() -> None:
    repository = RecordingRepository()
    submitted = submission()

    persisted = service(repository).persist(JOB_ID, submitted)

    assert persisted.revision_number == 1
    assert persisted.persistence_state == "persisted"
    assert repository.calls == [(JOB_ID, submitted.draft(), CREATED_AT)]
    assert repository.commit_calls == 1
    assert repository.rollback_calls == 0


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (LookupError("missing"), "revision_identity_not_found", False),
        (ValueError("stale"), "revision_conflict", False),
        (RuntimeError("database unavailable"), "revision_persistence_failed", True),
    ],
)
def test_rolls_back_and_maps_repository_failures(
    error: Exception,
    code: str,
    retryable: bool,
) -> None:
    repository = RecordingRepository()
    repository.error = error

    with pytest.raises(VerificationError) as raised:
        service(repository).persist(JOB_ID, submission())

    assert raised.value.code == code
    assert raised.value.stage == "revision_persistence"
    assert raised.value.retryable is retryable
    assert repository.commit_calls == 0
    assert repository.rollback_calls == 1


def test_rejects_revision_text_above_the_configured_byte_limit_before_persistence() -> None:
    repository = RecordingRepository()
    oversized = submission(
        text="😀a",
        kind=DocumentRevisionKind.MANUAL,
    )

    with pytest.raises(VerificationError) as raised:
        service(repository, max_revision_bytes=4).persist(JOB_ID, oversized)

    assert raised.value.code == "revision_text_too_large"
    assert raised.value.stage == "revision_persistence"
    assert raised.value.retryable is False
    assert repository.calls == []
    assert repository.commit_calls == 0
    assert repository.rollback_calls == 0


def test_valid_recheck_grant_authorizes_revision_persistence_idempotently() -> None:
    repository = RecordingRepository()
    grants = RecheckProvenanceGrantService(
        "server-owned-recheck-grant-secret-32-bytes",
        now_factory=lambda: CREATED_AT,
    )
    expected = RecheckGrantBinding(
        job_id=JOB_ID,
        original_document_id=DOCUMENT_ID,
        original_verification_run_id=RUN_ID,
        original_source_version="sha256:source",
        submitted_text="重新检查基线",
        result_document_id=UUID("50000000-0000-4000-8000-000000000005"),
        result_verification_run_id=UUID(
            "60000000-0000-4000-8000-000000000006"
        ),
        result_source_version="sha256:" + "b" * 64,
    )
    provenance = RecheckProvenance(
        grant=grants.issue(expected),
        result_document_id=expected.result_document_id,
        result_verification_run_id=expected.result_verification_run_id,
        result_source_version=expected.result_source_version,
    )
    submitted = submission(
        text=expected.submitted_text,
        kind=DocumentRevisionKind.MANUAL,
        base_result=base_result_payload(
            document_id=expected.result_document_id,
            verification_run_id=expected.result_verification_run_id,
            source_version=expected.result_source_version,
        ),
        recheck_provenance=provenance,
    )

    first = service(repository, grant_service=grants).persist(
        JOB_ID,
        submitted,
    )
    second = service(repository, grant_service=grants).persist(
        JOB_ID,
        submitted,
    )

    assert first == second
    assert len(repository.calls) == 2


def test_forged_recheck_grant_is_rejected_before_revision_persistence() -> None:
    repository = RecordingRepository()
    grants = RecheckProvenanceGrantService(
        "server-owned-recheck-grant-secret-32-bytes",
        now_factory=lambda: CREATED_AT,
    )
    provenance = RecheckProvenance(
        grant="client-recomputed-value",
        result_document_id=UUID("50000000-0000-4000-8000-000000000005"),
        result_verification_run_id=UUID(
            "60000000-0000-4000-8000-000000000006"
        ),
        result_source_version="sha256:" + "b" * 64,
    )

    with pytest.raises(VerificationError) as raised:
        service(repository, grant_service=grants).persist(
            JOB_ID,
            submission(
                text=draft().text,
                kind=DocumentRevisionKind.MANUAL,
                base_result=base_result_payload(
                    document_id=provenance.result_document_id,
                    verification_run_id=provenance.result_verification_run_id,
                    source_version=provenance.result_source_version,
                ),
                recheck_provenance=provenance,
            ),
        )

    assert raised.value.code == "recheck_provenance_invalid"
    assert repository.calls == []


def test_recheck_grant_rejects_a_different_submitted_recheck_text() -> None:
    repository = RecordingRepository()
    grants = RecheckProvenanceGrantService(
        "server-owned-recheck-grant-secret-32-bytes",
        now_factory=lambda: CREATED_AT,
    )
    expected = RecheckGrantBinding(
        job_id=JOB_ID,
        original_document_id=DOCUMENT_ID,
        original_verification_run_id=RUN_ID,
        original_source_version="sha256:source",
        submitted_text="重新检查基线",
        result_document_id=UUID("50000000-0000-4000-8000-000000000005"),
        result_verification_run_id=UUID(
            "60000000-0000-4000-8000-000000000006"
        ),
        result_source_version="sha256:" + "b" * 64,
    )
    provenance = RecheckProvenance(
        grant=grants.issue(expected),
        result_document_id=expected.result_document_id,
        result_verification_run_id=expected.result_verification_run_id,
        result_source_version=expected.result_source_version,
    )

    with pytest.raises(VerificationError) as raised:
        service(repository, grant_service=grants).persist(
            JOB_ID,
            submission(
                text="篡改后的基线",
                kind=DocumentRevisionKind.MANUAL,
                base_result=base_result_payload(
                    document_id=provenance.result_document_id,
                    verification_run_id=provenance.result_verification_run_id,
                    source_version=provenance.result_source_version,
                ),
                recheck_provenance=provenance,
            ),
        )

    assert raised.value.code == "recheck_provenance_invalid"
    assert repository.calls == []


@pytest.mark.parametrize(
    "kind",
    [DocumentRevisionKind.REVIEW, DocumentRevisionKind.MANUAL],
)
def test_omitted_recheck_grant_rejects_arbitrary_revision_text(
    kind: DocumentRevisionKind,
) -> None:
    repository = RecordingRepository()
    arbitrary = submission(
        text="客户端任意改写",
        kind=kind,
    )

    with pytest.raises(VerificationError) as raised:
        service(repository).persist(JOB_ID, arbitrary)

    assert raised.value.code == "revision_authorization_required"
    assert repository.calls == []


def test_valid_grant_for_a_different_text_does_not_authorize_revision() -> None:
    repository = RecordingRepository()
    grants = RecheckProvenanceGrantService(
        "server-owned-recheck-grant-secret-32-bytes",
        now_factory=lambda: CREATED_AT,
    )
    expected = RecheckGrantBinding(
        job_id=JOB_ID,
        original_document_id=DOCUMENT_ID,
        original_verification_run_id=RUN_ID,
        original_source_version="sha256:source",
        submitted_text="已重新检查的文本",
        result_document_id=UUID("50000000-0000-4000-8000-000000000005"),
        result_verification_run_id=UUID(
            "60000000-0000-4000-8000-000000000006"
        ),
        result_source_version="sha256:" + "b" * 64,
    )
    provenance = RecheckProvenance(
        grant=grants.issue(expected),
        result_document_id=expected.result_document_id,
        result_verification_run_id=expected.result_verification_run_id,
        result_source_version=expected.result_source_version,
    )

    with pytest.raises(VerificationError) as raised:
        service(repository, grant_service=grants).persist(
            JOB_ID,
            submission(
                text="未重新检查的任意文本",
                kind=DocumentRevisionKind.MANUAL,
                base_result=base_result_payload(
                    document_id=provenance.result_document_id,
                    verification_run_id=provenance.result_verification_run_id,
                    source_version=provenance.result_source_version,
                ),
                recheck_provenance=provenance,
            ),
        )

    assert raised.value.code == "recheck_provenance_invalid"
    assert repository.calls == []


def test_valid_direct_accepted_replacement_is_authorized_from_original_result() -> None:
    repository = RecordingRepository()
    submission = ReviewRevisionSubmission.model_validate(
        {
            **draft().model_copy(
                update={
                    "kind": DocumentRevisionKind.REVIEW,
                    "text": "账号测试",
                }
            ).model_dump(mode="json"),
            "base_result": base_result_payload(),
        }
    )

    persisted = service(repository).persist(JOB_ID, submission)

    assert persisted.text == "账号测试"
    assert len(repository.provenance_calls) == 1
    stored = repository.provenance_calls[0]
    assert stored is not None
    assert stored.kind.value == "original_result"


def test_valid_recheck_grant_authorizes_exact_rechecked_revision_text() -> None:
    repository = RecordingRepository()
    grants = RecheckProvenanceGrantService(
        "server-owned-recheck-grant-secret-32-bytes",
        now_factory=lambda: CREATED_AT,
    )
    expected = RecheckGrantBinding(
        job_id=JOB_ID,
        original_document_id=DOCUMENT_ID,
        original_verification_run_id=RUN_ID,
        original_source_version="sha256:source",
        submitted_text="已重新检查的文本",
        result_document_id=UUID("50000000-0000-4000-8000-000000000005"),
        result_verification_run_id=UUID(
            "60000000-0000-4000-8000-000000000006"
        ),
        result_source_version="sha256:" + "b" * 64,
    )
    submission = ReviewRevisionSubmission.model_validate(
        {
            **draft().model_copy(
                update={
                    "kind": DocumentRevisionKind.MANUAL,
                    "text": expected.submitted_text,
                }
            ).model_dump(mode="json"),
            "base_result": base_result_payload(
                document_id=expected.result_document_id,
                verification_run_id=expected.result_verification_run_id,
                source_version=expected.result_source_version,
            ),
            "recheck_provenance": {
                "grant": grants.issue(expected),
                "result_document_id": str(expected.result_document_id),
                "result_verification_run_id": str(
                    expected.result_verification_run_id
                ),
                "result_source_version": expected.result_source_version,
            },
        }
    )

    persisted = service(repository, grant_service=grants).persist(
        JOB_ID,
        submission,
    )

    assert persisted.text == expected.submitted_text
    stored = repository.provenance_calls[0]
    assert stored is not None
    assert stored.kind.value == "recheck_result"
