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
from text_verification.document_processing.errors import (
    OcrLayoutError,
    OcrOutputError,
    OcrProcessingError,
    OcrUnavailableError,
)
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.issues import (
    Issue,
    IssueLimitExceededError,
    validate_issue_count,
)
from text_verification.domain.ports import (
    CheckContext,
    CheckResult,
    OcrDeferrableParser,
    ProgressAwareParser,
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
from text_verification.parsers.errors import ParserError, PdfResourceLimitError
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
        ocr_in_synchronous_mode: bool = True,
    ) -> None:
        self._parsers = parsers
        self._checkers = checkers
        self._reviewer = reviewer
        self._ocr_in_synchronous_mode = ocr_in_synchronous_mode

    def run(
        self,
        command: VerificationCommand,
        *,
        progress_observer: VerificationProgressObserver | None = None,
    ) -> VerificationResult:
        if command.source_path is not None and progress_observer is not None:
            progress_observer(VerificationProgressStage.PARSING)
        document = self._load_document(
            command,
            progress_observer=progress_observer,
        )
        ocr_requirement = document.metadata.pdf_ocr_requirement
        if ocr_requirement is not None and ocr_requirement.mode == "required":
            pages = ", ".join(str(page) for page in ocr_requirement.pages)
            raise VerificationError(
                "ocr_required",
                "ocr",
                f"OCR is required for scanned PDF pages: {pages}.",
                False,
            )
        context = CheckContext.from_options(command.options)
        check_result = self._run_checks(
            document,
            context,
            progress_observer=progress_observer,
        )
        issues, review_metadata = self._review(document, check_result.issues)

        analysis_mode = VerificationAnalysisMode.LOCAL_ONLY
        degradation_reasons: tuple[str, ...] = (
            ("ocr_required_pages",)
            if ocr_requirement is not None and ocr_requirement.mode == "partial"
            else ()
        )
        if review_metadata is not None:
            if review_metadata.get("failed"):
                issues = check_result.issues
                review_metadata = {
                    **review_metadata,
                    "stage": "reviewing",
                    "retryable": bool(review_metadata.get("retryable", False)),
                }
                degradation_reasons = (*degradation_reasons, "llm_review_failed")
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
            blocks=tuple(document.blocks),
            parser_name=document.parser_name,
            parser_version=document.parser_version,
            metadata=document.metadata,
            ocr_requirement=ocr_requirement,
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

    def _load_document(
        self,
        command: VerificationCommand,
        *,
        progress_observer: VerificationProgressObserver | None,
    ) -> DocumentModel:
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
            if (
                command.execution_mode is VerificationExecutionMode.SYNCHRONOUS
                and not self._ocr_in_synchronous_mode
                and isinstance(parser, OcrDeferrableParser)
            ):
                parsed = parser.parse_without_ocr(source_path)
            elif progress_observer is not None and isinstance(parser, ProgressAwareParser):
                parsed = parser.parse_with_progress(
                    source_path,
                    progress_observer=progress_observer,
                )
            else:
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
        except OcrUnavailableError as error:
            raise VerificationError(
                error.code,
                error.stage,
                error.message,
                error.retryable,
            ) from error
        except OcrProcessingError as error:
            raise VerificationError(
                error.code,
                error.stage,
                error.message,
                error.retryable,
            ) from error
        except (OcrLayoutError, OcrOutputError) as error:
            raise VerificationError(
                "ocr_output_invalid",
                "ocr",
                "The OCR provider returned invalid output.",
                False,
            ) from error
        except PdfResourceLimitError as error:
            is_ocr_limit = error.limit.startswith("max_ocr")
            raise VerificationError(
                "ocr_resource_limit" if is_ocr_limit else "parser_resource_limit",
                "ocr" if is_ocr_limit else "parsing",
                (
                    "OCR resource limits were exceeded."
                    if is_ocr_limit
                    else "Document parsing resource limits were exceeded."
                ),
                False,
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
        except IssueLimitExceededError as error:
            raise VerificationError(
                "issue_limit_exceeded",
                "checking",
                "Verification produced too many issues.",
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
            reviewed, metadata = self._reviewer.review(document, issues)
            validate_issue_count(reviewed)
            return reviewed, metadata
        except ReviewerError as error:
            return issues, _failed_review_metadata(error)
        except IssueLimitExceededError as error:
            raise VerificationError(
                "issue_limit_exceeded",
                "reviewing",
                "Verification review produced too many issues.",
                False,
            ) from error


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
