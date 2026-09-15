from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from text_verification.application.errors import ReviewerError
from text_verification.application.verification_pipeline import (
    ReviewMetadata,
    VerificationPipeline,
)
from text_verification.checkers.compatibility_checker import CompatibilityChecker
from text_verification.checkers.registry import CheckerRegistry
from text_verification.compatibility.analyzer import Issue as LegacyIssue
from text_verification.compatibility.llm_review import (
    is_llm_review_configured,
    review_issues,
)
from text_verification.compatibility.semantic_discovery import discover_issues
from text_verification.config import Settings, get_settings
from text_verification.document_processing.ocr_provider import OcrProvider
from text_verification.domain.documents import DocumentModel, ExportFormat, FileType
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.ports import (
    AnchoredSourcePathResolver,
    CheckContext,
    Parser,
    SourcePathResolver,
)
from text_verification.exporters.compatibility_exporter import CompatibilityExporter
from text_verification.exporters.docx_reconstruction import (
    DocxReconstructionExporter,
    DocxReconstructionLimits,
)
from text_verification.exporters.registry import ExporterRegistry
from text_verification.parsers.compatibility_parser import CompatibilityParser
from text_verification.parsers.image_parser import ImageParser
from text_verification.parsers.pdf_parser import PdfParser
from text_verification.parsers.registry import ParserRegistry


@dataclass(frozen=True)
class CompatibilityIssueReviewer:
    settings: Settings

    def review(
        self,
        document: DocumentModel,
        issues: tuple[Issue, ...],
        context: CheckContext | None = None,
    ) -> tuple[tuple[Issue, ...], ReviewMetadata | None]:
        if not is_llm_review_configured(self.settings):
            return issues, None

        legacy_issues = [_to_legacy_issue(issue) for issue in issues]
        source_by_legacy_id = {
            id(legacy_issue): issue
            for legacy_issue, issue in zip(legacy_issues, issues, strict=True)
        }
        reviewed, metadata = (
            review_issues(self.settings, document.text, legacy_issues, context)
            if context is not None
            else review_issues(self.settings, document.text, legacy_issues)
        )
        if metadata.get("failed"):
            failure_code = str(metadata.get("failure_code") or "llm_review_failed")
            retryable = metadata.get("retryable")
            if not isinstance(retryable, bool):
                retryable = failure_code in {"llm_provider_error", "llm_timeout"}
            raise ReviewerError(
                code=failure_code,
                message=str(metadata.get("reason") or "LLM review failed."),
                retryable=retryable,
                metadata=dict(metadata),
            )
        return (
            tuple(
                _apply_legacy_review(source_by_legacy_id[id(legacy_issue)], legacy_issue)
                for legacy_issue in reviewed
            ),
            dict(metadata),
        )

    def review_with_context(
        self, document: DocumentModel, issues: tuple[Issue, ...], context: CheckContext,
    ) -> tuple[tuple[Issue, ...], ReviewMetadata | None]:
        reviewed, metadata = self.review(document, issues, context)
        if not context.enable_semantic_discovery:
            return reviewed, metadata
        discovered, discovery_metadata = discover_issues(self.settings, document, context, issues)
        return (
            (*reviewed, *discovered),
            {**(metadata or {}), "semantic_discovery": discovery_metadata},
        )


def build_default_verification_pipeline(
    settings: Settings | None = None,
) -> VerificationPipeline:
    resolved_settings = settings or get_settings()
    ocr = OcrProvider()
    return VerificationPipeline(
        parsers=ParserRegistry(
            (
                cast(Parser, PdfParser(ocr=ocr)),
                cast(Parser, ImageParser(file_type=FileType.PNG, ocr=ocr)),
                cast(Parser, ImageParser(file_type=FileType.JPG, ocr=ocr)),
                *(
                    cast(Parser, CompatibilityParser(file_type))
                    for file_type in FileType
                    if file_type not in {FileType.PDF, FileType.PNG, FileType.JPG}
                ),
            )
        ),
        checkers=CheckerRegistry([CompatibilityChecker()]),
        reviewer=CompatibilityIssueReviewer(resolved_settings),
        ocr_in_synchronous_mode=False,
    )


def build_default_exporter_registry(
    *,
    anchored_source_resolver: AnchoredSourcePathResolver,
    max_output_bytes: int,
) -> ExporterRegistry:
    return ExporterRegistry(
        (
            DocxReconstructionExporter(
                limits=DocxReconstructionLimits(max_output_bytes=max_output_bytes),
                anchored_source_resolver=anchored_source_resolver,
                file_type=ExportFormat.DOCX_RECONSTRUCTION,
            ),
            *(
                CompatibilityExporter(
                    file_type=file_type,
                    source_path_resolver=cast(
                        SourcePathResolver,
                        anchored_source_resolver,
                    ),
                    max_text_bytes=max_output_bytes,
                )
                for file_type in FileType
            ),
        )
    )


def _to_legacy_issue(issue: Issue) -> LegacyIssue:
    legacy = LegacyIssue(
        type=issue.type,
        severity=issue.severity.value,
        original=issue.original,
        suggestion=issue.suggestion,
        position=issue.start,
        end_position=issue.end,
        context=issue.context,
        description=issue.description,
        rule_id=issue.rule_id,
        alternatives=list(issue.alternatives),
        layer=issue.layer,
        review=issue.review or "",
        review_reason=issue.review_reason or "",
    )
    legacy.confidence = issue.confidence
    return legacy


def _apply_legacy_review(issue: Issue, reviewed: LegacyIssue) -> Issue:
    severity = IssueSeverity(reviewed.severity)
    confidence = getattr(reviewed, "confidence", None)
    updates: dict[str, Any] = {
        "severity": severity,
        "confidence": confidence if confidence is not None else issue.confidence,
        "description": reviewed.description,
        "review": reviewed.review or None,
        "review_reason": reviewed.review_reason or None,
    }
    if reviewed.review == "uncertain":
        updates["auto_fixable"] = False
    return issue.model_copy(update=updates)
