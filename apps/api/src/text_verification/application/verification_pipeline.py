from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from text_verification.application.errors import ReviewerError, VerificationError
from text_verification.checkers.registry import CheckerRegistry
from text_verification.compatibility.adapters import text_to_document_model
from text_verification.compatibility.statistics import text_statistics
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.issues import Issue
from text_verification.domain.ports import (
    CheckContext,
    CheckResult,
    VerificationProgressObserver,
    VerificationProgressStage,
)
from text_verification.domain.verification import (
    VerificationAnalysisMode,
    VerificationDegradation,
    VerificationExecutionMode,
    VerificationOptions,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)
from text_verification.infrastructure.dictionary_loader import DictionaryLoadError
from text_verification.parsers.errors import ParserError
from text_verification.parsers.registry import ParserRegistry
from text_verification.registry_errors import MissingCapabilityError

ReviewMetadata = dict[str, Any]


class IssueReviewer(Protocol):
    def review(
        self,
        document: DocumentModel,
        issues: tuple[Issue, ...],
    ) -> tuple[tuple[Issue, ...], ReviewMetadata | None]: ...


@dataclass(frozen=True)
class VerificationCommand:
    document_id: UUID
    source_path: Path | None
    direct_text: str | None
    source_name: str
    file_type: FileType
    options: VerificationOptions
    execution_mode: VerificationExecutionMode


class VerificationPipeline:
    def __init__(
        self,
        *,
        parsers: ParserRegistry,
        checkers: CheckerRegistry,
        reviewer: IssueReviewer | None,
    ) -> None:
        self._parsers = parsers
        self._checkers = checkers
        self._reviewer = reviewer

    def run(
        self,
        command: VerificationCommand,
        *,
        progress_observer: VerificationProgressObserver | None = None,
    ) -> VerificationResult:
        if command.source_path is not None and progress_observer is not None:
            progress_observer(VerificationProgressStage.PARSING)
        document = self._load_document(command)
        context = CheckContext.from_options(command.options)
        check_result = self._run_checks(
            document,
            context,
            progress_observer=progress_observer,
        )
        issues, review_metadata = self._review(document, check_result.issues)

        analysis_mode = VerificationAnalysisMode.LOCAL_ONLY
        degradation_reasons: tuple[str, ...] = ()
        if review_metadata is not None:
            if review_metadata.get("failed"):
                issues = check_result.issues
                review_metadata = {
                    **review_metadata,
                    "stage": "reviewing",
                    "retryable": bool(review_metadata.get("retryable", False)),
                }
                degradation_reasons = ("llm_review_failed",)
            elif review_metadata.get("performed"):
                analysis_mode = VerificationAnalysisMode.LOCAL_PLUS_LLM

        return VerificationResult(
            verification_run_id=context.verification_run_id,
            document_id=document.document_id,
            source_version=document.source_version,
            source_name=document.source_name,
            file_type=document.file_type,
            scenario=command.options.scenario,
            text=document.text,
            stats=VerificationStatistics.model_validate(text_statistics(document.text)),
            issues=issues,
            summary=_summarize(issues, review_metadata),
            execution_mode=command.execution_mode,
            analysis_mode=analysis_mode,
            dictionary_versions=dict(check_result.dictionary_versions),
            degradation=VerificationDegradation(
                is_degraded=bool(degradation_reasons),
                reasons=degradation_reasons,
            ),
        )

    def _load_document(self, command: VerificationCommand) -> DocumentModel:
        if (command.source_path is None) == (command.direct_text is None):
            raise VerificationError(
                "invalid_verification_input",
                "input",
                "Provide either direct text or a stored source path.",
                False,
            )

        if command.direct_text is not None:
            return text_to_document_model(
                text=command.direct_text,
                source_name=command.source_name,
                file_type=command.file_type,
                document_id=command.document_id,
            )

        try:
            parser = self._parsers.get(command.file_type)
        except MissingCapabilityError as error:
            raise VerificationError(
                "parser_unavailable",
                "parsing",
                "No parser is available for the source document.",
                False,
            ) from error

        source_path = command.source_path
        if source_path is None:
            raise AssertionError("source_path must be set for stored input")
        try:
            parsed = parser.parse(source_path)
        except FileNotFoundError as error:
            raise VerificationError(
                "source_not_found",
                "parsing",
                "The stored source document is unavailable.",
                False,
            ) from error
        except PermissionError as error:
            raise VerificationError(
                "source_read_failed",
                "parsing",
                "The stored source document could not be read.",
                True,
            ) from error
        except ParserError as error:
            raise VerificationError(
                "parser_failed",
                "parsing",
                "The source document could not be parsed.",
                False,
            ) from error
        except OSError as error:
            raise VerificationError(
                "source_read_failed",
                "parsing",
                "The stored source document could not be read.",
                True,
            ) from error

        return parsed.model_copy(
            update={
                "document_id": command.document_id,
                "source_name": command.source_name,
                "file_type": command.file_type,
            }
        )

    def _run_checks(
        self,
        document: DocumentModel,
        context: CheckContext,
        *,
        progress_observer: VerificationProgressObserver | None,
    ) -> CheckResult:
        try:
            return self._checkers.run(
                document,
                context,
                progress_observer=progress_observer,
            )
        except MissingCapabilityError as error:
            raise VerificationError(
                "checker_unavailable",
                "checking",
                "No checker is available for this verification.",
                False,
            ) from error
        except DictionaryLoadError as error:
            raise VerificationError(
                "dictionary_load_failed",
                "checking",
                "A verification dictionary could not be loaded.",
                False,
            ) from error

    def _review(
        self,
        document: DocumentModel,
        issues: tuple[Issue, ...],
    ) -> tuple[tuple[Issue, ...], ReviewMetadata | None]:
        if self._reviewer is None:
            return issues, None
        try:
            return self._reviewer.review(document, issues)
        except ReviewerError as error:
            return issues, _failed_review_metadata(error)


def _failed_review_metadata(error: ReviewerError) -> ReviewMetadata:
    return {
        **error.metadata,
        "enabled": True,
        "performed": False,
        "failed": True,
        "failure_code": error.code,
        "stage": "reviewing",
        "retryable": error.retryable,
        "reason": str(error),
    }


def _summarize(
    issues: tuple[Issue, ...],
    review_metadata: ReviewMetadata | None,
) -> VerificationSummary:
    return VerificationSummary(
        total=len(issues),
        by_type=dict(Counter(issue.type for issue in issues)),
        by_severity=dict(Counter(issue.severity.value for issue in issues)),
        by_rule=dict(Counter(issue.rule_id for issue in issues)),
        by_layer=dict(Counter(issue.layer for issue in issues)),
        llm_review=review_metadata,
    )
