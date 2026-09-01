from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from text_verification.compatibility.analyzer import Issue as LegacyIssue
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.verification import LEGACY_SUMMARY_LABELS, VerificationResult

_LEGACY_SOURCE = "compatibility.analyzer"
_LEGACY_SOURCE_VERSION = "1"
_LEGACY_RULE_VERSION = "1"
_PARAGRAPH_LABEL_PATTERN = re.compile(r"^第(\d+)段$")
_PAGE_LABEL_PATTERN = re.compile(r"^第(\d+)页$")
_CONFIDENCE_BY_SEVERITY = {
    IssueSeverity.ERROR: 1.0,
    IssueSeverity.WARNING: 0.8,
    IssueSeverity.INFO: 0.6,
}


def confidence_for_severity(severity: IssueSeverity | str) -> float:
    return _CONFIDENCE_BY_SEVERITY[IssueSeverity(severity)]


def source_version_for_text(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def source_version_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def text_to_document_model(
    *,
    text: str,
    source_name: str,
    file_type: FileType,
    document_id: UUID | None = None,
) -> DocumentModel:
    source_version = source_version_for_text(text)
    resolved_document_id = document_id or uuid5(
        NAMESPACE_URL,
        f"document:{file_type.value}:{source_name}:{source_version}",
    )
    return DocumentModel(
        document_id=resolved_document_id,
        source_version=source_version,
        file_type=file_type,
        source_name=source_name,
        text=text,
        blocks=[_direct_text_block(text)],
        parser_name="compatibility-flat-text",
        parser_version="1",
    )


def parsed_file_to_document_model(
    *,
    text: str,
    source_version: str,
    source_name: str,
    file_type: FileType,
    parser_name: str,
    page_map: Sequence[tuple[int, int, str]],
    document_id: UUID | None = None,
) -> DocumentModel:
    resolved_document_id = document_id or uuid5(
        NAMESPACE_URL,
        f"document:{file_type.value}:{source_name}:{source_version}",
    )
    return DocumentModel(
        document_id=resolved_document_id,
        source_version=source_version,
        file_type=file_type,
        source_name=source_name,
        text=text,
        blocks=_uploaded_blocks(text, page_map),
        parser_name=parser_name,
        parser_version="1",
    )


def legacy_issue_to_domain(
    legacy_issue: LegacyIssue,
    document: DocumentModel,
    run_id: UUID,
) -> Issue:
    severity = IssueSeverity(legacy_issue.severity)
    start = legacy_issue.position
    end = max(legacy_issue.end_position, start + len(legacy_issue.original))
    block = _find_block(document, start, end)
    issue_id = uuid5(
        NAMESPACE_URL,
        (
            f"{document.source_version}:{legacy_issue.rule_id}:{legacy_issue.position}:"
            f"{legacy_issue.end_position}:{legacy_issue.original}"
        ),
    )

    return Issue(
        issue_id=issue_id,
        document_id=document.document_id,
        verification_run_id=run_id,
        block_id=block.block_id if block is not None else None,
        page=block.page if block is not None else None,
        start=start,
        end=end,
        block_start=(start - block.global_start) if block is not None else None,
        block_end=(end - block.global_start) if block is not None else None,
        original=document.text[start:end],
        suggestion=legacy_issue.suggestion,
        alternatives=list(legacy_issue.alternatives or []),
        type=legacy_issue.type,
        severity=severity,
        layer=legacy_issue.layer,
        message=legacy_issue.description,
        description=legacy_issue.description,
        rule_id=legacy_issue.rule_id,
        rule_version=_LEGACY_RULE_VERSION,
        source=_LEGACY_SOURCE,
        source_version=_LEGACY_SOURCE_VERSION,
        confidence=confidence_for_severity(severity),
        auto_fixable=bool(legacy_issue.suggestion),
        context=legacy_issue.context,
        review=legacy_issue.review or None,
        review_reason=legacy_issue.review_reason or None,
    )


def legacy_issues_to_domain(
    legacy_issues: Iterable[LegacyIssue],
    document: DocumentModel,
    run_id: UUID,
) -> tuple[Issue, ...]:
    return tuple(legacy_issue_to_domain(issue, document, run_id) for issue in legacy_issues)


def verification_result_to_legacy_response(result: VerificationResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "success": True,
        "filename": result.source_name,
        "source_name": result.source_name,
        "file_type": result.file_type.value,
        "text": result.text,
        "blocks": [block.model_dump(mode="json") for block in result.blocks],
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
        "stats": result.stats.model_dump(mode="json"),
        "issues": [
            _domain_issue_to_legacy_payload(issue)
            for issue in sorted(result.issues, key=lambda item: (item.start, item.end))
        ],
        "summary": _legacy_summary(result),
        "file_id": str(result.document_id),
        "file_ext": f".{result.file_type.value}",
        "scenario": result.scenario.value,
        "document_id": str(result.document_id),
        "verification_run_id": str(result.verification_run_id),
        "source_version": result.source_version,
        "execution_mode": result.execution_mode.value,
        "analysis_mode": result.analysis_mode.value,
        "dictionary_versions": dict(result.dictionary_versions),
        "degradation": result.degradation.model_dump(mode="json"),
    }
    if result.metadata.pdf is not None:
        payload["pdf_metadata"] = result.metadata.pdf.model_dump(mode="json")
    if result.ocr_requirement is not None:
        payload["ocr_requirement"] = result.ocr_requirement.model_dump(mode="json")
    return payload


def _legacy_summary(result: VerificationResult) -> dict[str, object]:
    summary = result.summary.model_dump(mode="json", exclude_none=True)
    for bucket_name, labels in LEGACY_SUMMARY_LABELS.items():
        bucket = summary[bucket_name]
        summary[bucket_name] = {
            labels.get(key, key): count
            for key, count in bucket.items()
        }
    return summary


def _domain_issue_to_legacy_payload(issue: Issue) -> dict[str, object]:
    return {
        "type": issue.type,
        "severity": issue.severity.value,
        "original": issue.original,
        "suggestion": issue.suggestion,
        "position": issue.start,
        "end_position": issue.end,
        "start": issue.start,
        "end": issue.end,
        "context": issue.context,
        "description": issue.description,
        "rule_id": issue.rule_id,
        "alternatives": issue.alternatives or None,
        "layer": issue.layer,
        "review": issue.review or "",
        "review_reason": issue.review_reason or "",
        "issue_id": str(issue.issue_id),
        "document_id": str(issue.document_id),
        "verification_run_id": str(issue.verification_run_id),
        "block_id": issue.block_id,
        "page": issue.page,
        "block_start": issue.block_start,
        "block_end": issue.block_end,
        "message": issue.message,
        "rule_version": issue.rule_version,
        "source": issue.source,
        "source_version": issue.source_version,
        "confidence": issue.confidence,
        "auto_fixable": issue.auto_fixable,
    }


def _find_block(document: DocumentModel, start: int, end: int) -> TextBlock | None:
    for block in document.blocks:
        if block.global_start <= start and end <= block.global_end:
            return block
    return None


def _direct_text_block(text: str) -> TextBlock:
    return TextBlock(
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


def _uploaded_blocks(
    text: str,
    page_map: Sequence[tuple[int, int, str]],
) -> list[TextBlock]:
    blocks = [
        _uploaded_block(text, start, end, label, ordinal)
        for ordinal, (start, end, label) in enumerate(page_map)
        if text[start:end]
    ]
    return blocks or [_file_level_block(text)]


def _uploaded_block(
    text: str,
    start: int,
    end: int,
    label: str,
    ordinal: int,
) -> TextBlock:
    block_text = text[start:end]
    source_locator = _source_locator(label)
    paragraph_index = source_locator.get("paragraph_index")
    page = source_locator.get("page")
    return TextBlock(
        block_id=_block_id(source_locator, ordinal),
        kind="paragraph",
        text=block_text,
        global_start=start,
        global_end=end,
        block_start=0,
        block_end=len(block_text),
        page=page if isinstance(page, int) else None,
        paragraph_index=paragraph_index if isinstance(paragraph_index, int) else None,
        table_index=None,
        row_index=None,
        cell_index=None,
        bbox=None,
        parent_id=None,
        style={},
        source_locator=source_locator,
    )


def _file_level_block(text: str) -> TextBlock:
    return TextBlock(
        block_id="file-0",
        kind="paragraph",
        text=text,
        global_start=0,
        global_end=len(text),
        block_start=0,
        block_end=len(text),
        page=None,
        paragraph_index=None,
        table_index=None,
        row_index=None,
        cell_index=None,
        bbox=None,
        parent_id=None,
        style={},
        source_locator={
            "locator_kind": "file",
            "note": "parser returned no structural location map",
        },
    )


def _block_id(source_locator: dict[str, object], ordinal: int) -> str:
    if source_locator.get("locator_kind") == "paragraph":
        paragraph_index = source_locator.get("paragraph_index")
        if isinstance(paragraph_index, int):
            return f"paragraph-{paragraph_index}"
    if source_locator.get("locator_kind") == "page":
        page = source_locator.get("page")
        if isinstance(page, int):
            return f"page-{page}"
    return f"block-{ordinal}"


def _source_locator(label: str) -> dict[str, object]:
    if paragraph_match := _PARAGRAPH_LABEL_PATTERN.match(label):
        paragraph_number = int(paragraph_match.group(1))
        return {
            "label": label,
            "paragraph_index": paragraph_number - 1,
            "paragraph_number": paragraph_number,
            "locator_kind": "paragraph",
        }
    if page_match := _PAGE_LABEL_PATTERN.match(label):
        return {
            "label": label,
            "page": int(page_match.group(1)),
            "locator_kind": "page",
        }
    return {"label": label, "locator_kind": "unknown"}
