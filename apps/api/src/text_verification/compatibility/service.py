from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError

from text_verification.compatibility.adapters import (
    legacy_issues_to_domain,
    parsed_file_to_document_model,
    source_version_for_file,
    text_to_document_model,
)
from text_verification.compatibility.analyzer import SCENARIO_CONFIG, TextAnalyzer
from text_verification.compatibility.llm_review import (
    is_llm_review_configured,
    review_issues,
)
from text_verification.compatibility.models import GlossaryTerm, Scenario
from text_verification.compatibility.parser import parse_file
from text_verification.compatibility.statistics import text_statistics
from text_verification.config import Settings
from text_verification.domain.capabilities import (
    CapabilityProfile,
    default_capability_manifest,
)
from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.verification import (
    VerificationAnalysisMode,
    VerificationDegradation,
    VerificationExecutionMode,
    VerificationOptions,
    VerificationResult,
    VerificationStatistics,
    VerificationSummary,
)
from text_verification.infrastructure.dictionary_loader import DictionaryLoader
from text_verification.parsers.pdf_parser import PdfParser

_DICTIONARY_LOADER = DictionaryLoader()
_GLOSSARY_ADAPTER = TypeAdapter(list[GlossaryTerm])
_BANNED_WORDS_ADAPTER = TypeAdapter(list[str])


class AnalysisInputError(ValueError):
    pass


def parse_glossary(value: str) -> list[dict[str, str]]:
    if not value.strip():
        return []
    try:
        terms = _GLOSSARY_ADAPTER.validate_python(json.loads(value))
    except (json.JSONDecodeError, ValidationError) as error:
        raise AnalysisInputError(
            "custom_glossary must be a JSON array of glossary terms."
        ) from error
    return [term.model_dump() for term in terms if term.original != term.standard]


def parse_banned_words(value: str) -> list[str]:
    if not value.strip():
        return []
    try:
        words = _BANNED_WORDS_ADAPTER.validate_python(json.loads(value))
    except (json.JSONDecodeError, ValidationError) as error:
        raise AnalysisInputError("banned_words must be a JSON array of strings.") from error
    return list(dict.fromkeys(word.strip() for word in words if word.strip()))


def build_verification_options(
    *,
    scenario: Scenario,
    custom_glossary: list[dict[str, str]],
    banned_words: list[str],
    enable_security: bool,
    enable_sensitive: bool,
    enable_ad_extreme: bool,
) -> VerificationOptions:
    return VerificationOptions(
        scenario=scenario,
        custom_glossary=custom_glossary,
        banned_words=banned_words,
        enable_security=enable_security,
        enable_sensitive=enable_sensitive,
        enable_ad_extreme=enable_ad_extreme,
    )


def direct_text_document_id(text: str, *, source_name: str = "直接输入文本") -> UUID:
    return text_to_document_model(
        text=text,
        source_name=source_name,
        file_type=FileType.TXT,
    ).document_id


def analyze(
    settings: Settings,
    *,
    text: str,
    filename: str,
    file_id: UUID | None,
    file_extension: str | None,
    scenario: Scenario,
    custom_glossary: list[dict[str, str]],
    banned_words: list[str],
    enable_security: bool,
    enable_sensitive: bool,
    enable_ad_extreme: bool,
    document: DocumentModel | None = None,
) -> VerificationResult:
    analyzer = TextAnalyzer(dictionary_loader=_DICTIONARY_LOADER)
    document = document or text_to_document_model(
        text=text,
        source_name=filename,
        file_type=_file_type_for(file_extension),
        document_id=file_id,
    )
    verification_run_id = uuid4()
    issues = analyzer.analyze(
        text,
        scenario=scenario.value,
        custom_glossary=custom_glossary,
        banned_words=banned_words,
        enable_security=enable_security,
        enable_sensitive=enable_sensitive,
        enable_ad_extreme=enable_ad_extreme,
    )

    degradation_reasons: list[str] = []
    review_stats: dict[str, Any] | None = None
    analysis_mode = VerificationAnalysisMode.LOCAL_ONLY
    if is_llm_review_configured(settings):
        issues, review_stats = review_issues(settings, text, issues)
        if review_stats.get("failed"):
            degradation_reasons.append("llm_review_failed")
        elif review_stats.get("performed"):
            analysis_mode = VerificationAnalysisMode.LOCAL_PLUS_LLM

    summary_data: dict[str, Any] = analyzer.get_summary(issues)

    return VerificationResult(
        verification_run_id=verification_run_id,
        document_id=document.document_id,
        source_version=document.source_version,
        source_name=filename,
        file_type=document.file_type,
        scenario=scenario,
        text=text,
        blocks=tuple(document.blocks),
        parser_name=document.parser_name,
        parser_version=document.parser_version,
        metadata=document.metadata,
        ocr_requirement=document.metadata.pdf_ocr_requirement,
        stats=VerificationStatistics.model_validate(text_statistics(text)),
        issues=legacy_issues_to_domain(issues, document, verification_run_id),
        summary=VerificationSummary(
            total=int(summary_data["total"]),
            by_type=dict(summary_data["by_type"]),
            by_severity=dict(summary_data["by_severity"]),
            by_rule=dict(summary_data["by_rule"]),
            by_layer=dict(summary_data["by_layer"]),
            llm_review=review_stats,
        ),
        execution_mode=VerificationExecutionMode.SYNCHRONOUS,
        analysis_mode=analysis_mode,
        dictionary_versions=analyzer.dictionary_versions,
        degradation=VerificationDegradation(
            is_degraded=bool(degradation_reasons),
            reasons=tuple(degradation_reasons),
        ),
    )


def parse_uploaded_document(
    path: Path,
    extension: str,
    *,
    source_name: str,
    document_id: UUID | None = None,
) -> DocumentModel:
    if _file_type_for(extension) is FileType.PDF:
        return PdfParser().parse(path)
    source_version = source_version_for_file(path)
    text, parsed_format, page_map = parse_file(str(path), extension, str(path.parent))
    if not text.strip():
        raise AnalysisInputError("File content is empty or no text could be extracted.")
    return parsed_file_to_document_model(
        text=text,
        source_version=source_version,
        source_name=source_name,
        file_type=_file_type_for(extension),
        parser_name=f"compatibility-{parsed_format}",
        page_map=page_map,
        document_id=document_id,
    )


def parse_uploaded_file(path: Path, extension: str) -> str:
    if _file_type_for(extension) is FileType.PDF:
        return PdfParser().parse(path).text
    text, _, _ = parse_file(str(path), extension, str(path.parent))
    if not text.strip():
        raise AnalysisInputError("File content is empty or no text could be extracted.")
    return text


def scenarios() -> list[dict[str, str]]:
    return [
        {
            "id": scenario.value,
            "name": str(SCENARIO_CONFIG[scenario.value]["name"]),
            "description": str(SCENARIO_CONFIG[scenario.value]["description"]),
        }
        for scenario in Scenario
    ]


def formats() -> list[dict[str, str]]:
    return default_capability_manifest().api_formats(
        CapabilityProfile.SYNCHRONOUS_COMPATIBILITY
    )


def _file_type_for(file_extension: str | None) -> FileType:
    if not file_extension:
        return FileType.TXT
    return FileType(file_extension)
