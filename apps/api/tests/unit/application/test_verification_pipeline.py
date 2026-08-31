from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from text_verification.application.errors import VerificationError
from text_verification.application.factory import build_default_verification_pipeline
from text_verification.application.verification_pipeline import (
    VerificationCommand,
    VerificationPipeline,
)
from text_verification.checkers.registry import CheckerRegistry
from text_verification.config import Settings
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.ports import CheckContext, CheckResult
from text_verification.domain.verification import (
    Scenario,
    VerificationAnalysisMode,
    VerificationExecutionMode,
    VerificationOptions,
)
from text_verification.infrastructure.dictionary_loader import DictionaryLoadError
from text_verification.parsers.registry import ParserRegistry


@dataclass
class RecordingParser:
    document: DocumentModel
    calls: list[str]
    supported_type: FileType = FileType.TXT

    def parse(self, source_path: Path) -> DocumentModel:
        assert source_path.name == "source.txt"
        self.calls.append("parse")
        return self.document


@dataclass
class RecordingChecker:
    calls: list[str]
    dictionary_versions: dict[str, str] = field(
        default_factory=lambda: {"sensitive_rules": "sha256:rules"}
    )
    name: str = "recording"
    version: str = "1"
    supported_languages: set[str] = field(default_factory=lambda: {"zh", "en"})
    contexts: list[CheckContext] = field(default_factory=list)

    def check(self, document: DocumentModel, context: CheckContext) -> CheckResult:
        self.calls.append("check")
        self.contexts.append(context)
        return CheckResult(
            issues=(_issue(document, context.verification_run_id),),
            dictionary_versions=self.dictionary_versions,
        )


@dataclass
class RecordingReviewer:
    calls: list[str]
    metadata: dict[str, Any] | None = field(
        default_factory=lambda: {
            "enabled": True,
            "performed": True,
            "failed": False,
            "failure_code": None,
            "reason": "",
        }
    )
    run_ids: list[UUID] = field(default_factory=list)

    def review(
        self,
        document: DocumentModel,
        issues: tuple[Issue, ...],
    ) -> tuple[tuple[Issue, ...], dict[str, Any] | None]:
        del document
        self.calls.append("review")
        self.run_ids.extend(issue.verification_run_id for issue in issues)
        return issues, self.metadata


def test_pipeline_parses_checks_reviews_and_summarizes_in_order(tmp_path: Path) -> None:
    calls: list[str] = []
    document_id = uuid4()
    parsed_document = _document(
        document_id=document_id,
        source_name="source.txt",
        text="帐号 测试",
    )
    parser = RecordingParser(parsed_document, calls)
    checker = RecordingChecker(calls)
    reviewer = RecordingReviewer(calls)
    source_path = tmp_path / "source.txt"
    source_path.write_text("帐号 测试", encoding="utf-8")
    command = VerificationCommand(
        document_id=document_id,
        source_path=source_path,
        direct_text=None,
        source_name="用户原始名称.txt",
        file_type=FileType.TXT,
        options=VerificationOptions(scenario=Scenario.BUSINESS),
        execution_mode=VerificationExecutionMode.ASYNCHRONOUS,
    )
    pipeline = VerificationPipeline(
        parsers=ParserRegistry([parser]),
        checkers=CheckerRegistry([checker]),
        reviewer=reviewer,
    )

    result = pipeline.run(command)

    assert calls == ["parse", "check", "review"]
    assert result.document_id == document_id
    assert result.source_name == "用户原始名称.txt"
    assert result.source_version == parsed_document.source_version
    assert result.execution_mode is VerificationExecutionMode.ASYNCHRONOUS
    assert result.analysis_mode is VerificationAnalysisMode.LOCAL_PLUS_LLM
    assert result.verification_run_id == checker.contexts[0].verification_run_id
    assert reviewer.run_ids == [result.verification_run_id]
    assert result.dictionary_versions == {"sensitive_rules": "sha256:rules"}
    assert result.stats.model_dump() == {
        "char_count": 5,
        "char_count_no_space": 4,
        "line_count": 1,
        "paragraph_count": 1,
        "language": "zh",
        "primary_count": 4,
        "primary_label": "总字数",
    }
    assert result.summary.model_dump() == {
        "total": 1,
        "by_type": {"typo": 1},
        "by_severity": {"warning": 1},
        "by_rule": {"cn_typo": 1},
        "by_layer": {"character": 1},
        "llm_review": reviewer.metadata,
    }


def test_direct_text_builds_document_without_parser_and_preserves_execution_mode() -> None:
    calls: list[str] = []
    checker = RecordingChecker(calls, dictionary_versions={})
    reviewer = RecordingReviewer(calls, metadata=None)
    command = VerificationCommand(
        document_id=uuid4(),
        source_path=None,
        direct_text="帐号 测试",
        source_name="直接输入文本",
        file_type=FileType.TXT,
        options=VerificationOptions(),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
    )
    pipeline = VerificationPipeline(
        parsers=ParserRegistry(),
        checkers=CheckerRegistry([checker]),
        reviewer=reviewer,
    )

    result = pipeline.run(command)

    assert calls == ["check", "review"]
    assert result.document_id == command.document_id
    assert result.source_name == command.source_name
    assert result.execution_mode is VerificationExecutionMode.SYNCHRONOUS
    assert result.analysis_mode is VerificationAnalysisMode.LOCAL_ONLY
    assert result.degradation.is_degraded is False


def test_failed_llm_review_retains_local_issues_and_marks_degradation() -> None:
    calls: list[str] = []
    reviewer = RecordingReviewer(
        calls,
        metadata={
            "enabled": True,
            "performed": False,
            "failed": True,
            "failure_code": "llm_provider_error",
            "reason": "大模型调用失败，已回退纯规则结果",
        },
    )
    pipeline = VerificationPipeline(
        parsers=ParserRegistry(),
        checkers=CheckerRegistry([RecordingChecker(calls)]),
        reviewer=reviewer,
    )

    result = pipeline.run(_direct_command())

    assert len(result.issues) == 1
    assert result.issues[0].rule_id == "cn_typo"
    assert result.analysis_mode is VerificationAnalysisMode.LOCAL_ONLY
    assert result.degradation.is_degraded is True
    assert result.degradation.reasons == ("llm_review_failed",)
    assert result.summary.llm_review == {
        **reviewer.metadata,
        "stage": "reviewing",
        "retryable": True,
    }


def test_invalid_llm_response_degrades_with_stable_failure_metadata() -> None:
    calls: list[str] = []
    pipeline = VerificationPipeline(
        parsers=ParserRegistry(),
        checkers=CheckerRegistry([RecordingChecker(calls)]),
        reviewer=FailingReviewer(ValueError("invalid provider response")),
    )

    result = pipeline.run(_direct_command())

    assert len(result.issues) == 1
    assert result.analysis_mode is VerificationAnalysisMode.LOCAL_ONLY
    assert result.degradation.reasons == ("llm_review_failed",)
    assert result.summary.llm_review == {
        "enabled": True,
        "performed": False,
        "failed": True,
        "failure_code": "llm_invalid_response",
        "stage": "reviewing",
        "retryable": True,
        "reason": "大模型复核失败，已回退纯规则结果",
    }


@pytest.mark.parametrize(
    ("source_path", "direct_text"),
    [
        (None, None),
        (Path("source.txt"), "direct"),
    ],
)
def test_pipeline_rejects_ambiguous_input(
    source_path: Path | None,
    direct_text: str | None,
) -> None:
    pipeline = VerificationPipeline(
        parsers=ParserRegistry(),
        checkers=CheckerRegistry(),
        reviewer=None,
    )
    command = VerificationCommand(
        document_id=uuid4(),
        source_path=source_path,
        direct_text=direct_text,
        source_name="sample.txt",
        file_type=FileType.TXT,
        options=VerificationOptions(),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
    )

    with pytest.raises(VerificationError) as raised:
        pipeline.run(command)

    assert raised.value.code == "invalid_verification_input"
    assert raised.value.stage == "input"
    assert raised.value.retryable is False


def test_pipeline_wraps_known_parser_failure() -> None:
    parser = FailingParser(ValueError("empty extraction"))
    pipeline = VerificationPipeline(
        parsers=ParserRegistry([parser]),
        checkers=CheckerRegistry(),
        reviewer=None,
    )

    with pytest.raises(VerificationError) as raised:
        pipeline.run(_stored_command())

    assert raised.value.code == "parser_failed"
    assert raised.value.stage == "parsing"
    assert raised.value.retryable is False
    assert str(raised.value) == "The source document could not be parsed."
    assert isinstance(raised.value.__cause__, ValueError)


def test_pipeline_wraps_dictionary_checker_failure() -> None:
    pipeline = VerificationPipeline(
        parsers=ParserRegistry(),
        checkers=CheckerRegistry([FailingChecker(DictionaryLoadError("private path"))]),
        reviewer=None,
    )

    with pytest.raises(VerificationError) as raised:
        pipeline.run(_direct_command())

    assert raised.value.code == "dictionary_load_failed"
    assert raised.value.stage == "checking"
    assert raised.value.retryable is False
    assert str(raised.value) == "A verification dictionary could not be loaded."
    assert isinstance(raised.value.__cause__, DictionaryLoadError)


def test_pipeline_wraps_known_checker_validation_failure() -> None:
    pipeline = VerificationPipeline(
        parsers=ParserRegistry(),
        checkers=CheckerRegistry([FailingChecker(ValueError("invalid checker input"))]),
        reviewer=None,
    )

    with pytest.raises(VerificationError) as raised:
        pipeline.run(_direct_command())

    assert raised.value.code == "checker_failed"
    assert raised.value.stage == "checking"
    assert raised.value.retryable is False
    assert str(raised.value) == "A checker returned an invalid result."
    assert isinstance(raised.value.__cause__, ValueError)


def test_pipeline_leaves_checker_programming_errors_visible() -> None:
    pipeline = VerificationPipeline(
        parsers=ParserRegistry(),
        checkers=CheckerRegistry([FailingChecker(TypeError("programming defect"))]),
        reviewer=None,
    )

    with pytest.raises(TypeError, match="programming defect"):
        pipeline.run(_direct_command())


def test_default_factory_runs_direct_text_through_compatibility_checker() -> None:
    pipeline = build_default_verification_pipeline(Settings(llm_api_key=""))
    command = VerificationCommand(
        document_id=uuid4(),
        source_path=None,
        direct_text="这是测试。",
        source_name="直接输入文本",
        file_type=FileType.TXT,
        options=VerificationOptions(
            enable_security=False,
            enable_sensitive=False,
        ),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
    )

    result = pipeline.run(command)

    assert result.document_id == command.document_id
    assert result.source_name == command.source_name
    assert result.execution_mode is VerificationExecutionMode.SYNCHRONOUS
    assert result.analysis_mode is VerificationAnalysisMode.LOCAL_ONLY
    assert result.degradation.is_degraded is False


@dataclass
class FailingParser:
    error: Exception
    supported_type: FileType = FileType.TXT

    def parse(self, source_path: Path) -> DocumentModel:
        del source_path
        raise self.error


@dataclass
class FailingChecker:
    error: Exception
    name: str = "failing"
    version: str = "1"
    supported_languages: set[str] = field(default_factory=lambda: {"zh", "en"})

    def check(self, document: DocumentModel, context: CheckContext) -> CheckResult:
        del document, context
        raise self.error


@dataclass
class FailingReviewer:
    error: Exception

    def review(
        self,
        document: DocumentModel,
        issues: tuple[Issue, ...],
    ) -> tuple[tuple[Issue, ...], dict[str, Any] | None]:
        del document, issues
        raise self.error


def _direct_command() -> VerificationCommand:
    return VerificationCommand(
        document_id=uuid4(),
        source_path=None,
        direct_text="帐号 测试",
        source_name="直接输入文本",
        file_type=FileType.TXT,
        options=VerificationOptions(),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
    )


def _stored_command() -> VerificationCommand:
    return VerificationCommand(
        document_id=uuid4(),
        source_path=Path("source.txt"),
        direct_text=None,
        source_name="sample.txt",
        file_type=FileType.TXT,
        options=VerificationOptions(),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
    )


def _document(
    *,
    document_id: UUID | None = None,
    source_name: str = "sample.txt",
    text: str = "帐号 测试",
) -> DocumentModel:
    return DocumentModel(
        document_id=document_id or uuid4(),
        source_version="sha256:sample",
        file_type=FileType.TXT,
        source_name=source_name,
        text=text,
        blocks=[
            TextBlock(
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
                source_locator={"paragraph_index": 0},
            )
        ],
        parser_name="recording",
        parser_version="1",
    )


def _issue(document: DocumentModel, verification_run_id: UUID) -> Issue:
    return Issue(
        issue_id=uuid4(),
        document_id=document.document_id,
        verification_run_id=verification_run_id,
        block_id="p-0",
        page=None,
        start=0,
        end=2,
        block_start=0,
        block_end=2,
        original="帐号",
        suggestion="账号",
        alternatives=["账号"],
        type="typo",
        severity=IssueSeverity.WARNING,
        layer="character",
        message="疑似错别字",
        description="疑似错别字",
        rule_id="cn_typo",
        rule_version="1",
        source="test",
        source_version="1",
        confidence=0.8,
        auto_fixable=True,
        context=document.text,
    )
