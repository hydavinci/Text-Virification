from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

import pytest

from text_verification.application.errors import VerificationError
from text_verification.application.job_recheck import JobRecheckService
from text_verification.application.recheck_provenance import (
    RecheckGrantBinding,
    RecheckProvenanceGrantService,
)
from text_verification.domain.documents import FileType
from text_verification.domain.verification import (
    Scenario,
    VerificationAnalysisMode,
    VerificationDegradation,
    VerificationExecutionMode,
    VerificationOptions,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)
from text_verification.infrastructure.verification_repository import (
    JobResultSnapshot,
    JobResultState,
)

JOB_ID = UUID("10000000-0000-4000-8000-000000000001")
ORIGINAL_RUN_ID = UUID("20000000-0000-4000-8000-000000000002")
FRESH_DOCUMENT_ID = UUID("30000000-0000-4000-8000-000000000003")
FRESH_RUN_ID = UUID("40000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


def result(
    *,
    document_id: UUID,
    run_id: UUID,
    source_version: str,
    text: str,
    mode: VerificationExecutionMode,
) -> VerificationResult:
    return VerificationResult(
        verification_run_id=run_id,
        document_id=document_id,
        source_version=source_version,
        source_name="source.txt",
        file_type=FileType.TXT,
        scenario=Scenario.GENERAL,
        text=text,
        blocks=(),
        parser_name="test",
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
        issues=(),
        summary=VerificationSummary(total=0),
        execution_mode=mode,
        analysis_mode=VerificationAnalysisMode.LOCAL_ONLY,
        degradation=VerificationDegradation(),
    )


class Repository:
    def __init__(self, original: VerificationResult) -> None:
        self.original = original
        self.rollback_calls = 0

    def read_result_snapshot(self, job_id: UUID) -> JobResultSnapshot:
        assert job_id == JOB_ID
        return JobResultSnapshot(JobResultState.READY, self.original)

    def rollback(self) -> None:
        self.rollback_calls += 1


class Pipeline:
    def __init__(self, fresh: VerificationResult) -> None:
        self.fresh = fresh
        self.commands: list[object] = []

    def run(self, command):
        self.commands.append(command)
        return self.fresh


def test_job_recheck_issues_grant_bound_to_original_and_fresh_results() -> None:
    original = result(
        document_id=JOB_ID,
        run_id=ORIGINAL_RUN_ID,
        source_version="sha256:" + "a" * 64,
        text="原文",
        mode=VerificationExecutionMode.ASYNCHRONOUS,
    )
    fresh = result(
        document_id=FRESH_DOCUMENT_ID,
        run_id=FRESH_RUN_ID,
        source_version="sha256:" + "b" * 64,
        text="重新检查文本",
        mode=VerificationExecutionMode.SYNCHRONOUS,
    )
    repository = Repository(original)
    pipeline = Pipeline(fresh)
    grants = RecheckProvenanceGrantService(
        "server-owned-recheck-grant-secret-32-bytes",
        now_factory=lambda: NOW,
    )

    @contextmanager
    def repository_factory() -> Iterator[Repository]:
        yield repository

    outcome = JobRecheckService(
        repository_factory,
        pipeline,  # type: ignore[arg-type]
        grants,
        max_text_bytes=1024,
    ).recheck(
        JOB_ID,
        fresh.text,
        VerificationOptions(),
    )

    assert outcome.result == fresh
    grants.verify(
        outcome.grant,
        RecheckGrantBinding(
            job_id=JOB_ID,
            original_document_id=JOB_ID,
            original_verification_run_id=ORIGINAL_RUN_ID,
            original_source_version=original.source_version,
            submitted_text=fresh.text,
            result_document_id=FRESH_DOCUMENT_ID,
            result_verification_run_id=FRESH_RUN_ID,
            result_source_version=fresh.source_version,
        ),
    )
    assert repository.rollback_calls == 1
    assert len(pipeline.commands) == 1


def test_job_recheck_fails_closed_without_server_secret() -> None:
    original = result(
        document_id=JOB_ID,
        run_id=ORIGINAL_RUN_ID,
        source_version="sha256:" + "a" * 64,
        text="原文",
        mode=VerificationExecutionMode.ASYNCHRONOUS,
    )
    repository = Repository(original)

    @contextmanager
    def repository_factory() -> Iterator[Repository]:
        yield repository

    with pytest.raises(VerificationError) as raised:
        JobRecheckService(
            repository_factory,
            Pipeline(original),  # type: ignore[arg-type]
            None,
            max_text_bytes=1024,
        ).recheck(
            JOB_ID,
            "重新检查文本",
            VerificationOptions(),
        )

    assert raised.value.code == "recheck_provenance_unavailable"
    assert repository.rollback_calls == 0
