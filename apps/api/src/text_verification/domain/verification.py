from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from text_verification.document_processing.pdf_models import OcrRequirement
from text_verification.domain.documents import DocumentMetadata, DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue

SummaryCount = Annotated[int, Field(ge=0)]
BoundedOptionText = Annotated[str, Field(strict=True, min_length=1, max_length=200)]
MAX_CUSTOM_GLOSSARY_TERMS = 500
MAX_BANNED_WORDS = 500
MAX_VERIFICATION_OPTIONS_JSON_BYTES = 64 * 1024

LEGACY_TYPE_LABELS = {
    "typo": "错别字",
    "variant_char": "异形词",
    "width_mixed": "全半角混用",
    "missing_char": "漏字/缺字",
    "idiom_misuse": "成语误用",
    "expression": "语病/表达",
    "grammar": "语法",
    "logic": "逻辑",
    "punctuation": "标点符号",
    "spacing": "多余空格",
    "number_format": "数字/格式",
    "repetition": "重复词语",
    "style": "文风/格式",
    "colloquial": "口语化",
    "term_consistency": "术语不一致",
    "pii_id": "身份证号",
    "pii_phone": "手机号",
    "pii_email": "邮箱地址",
    "pii_bank": "银行卡号",
    "pii_key": "密钥/凭证",
}
LEGACY_SEVERITY_LABELS = {
    "error": "错误",
    "warning": "警告",
    "info": "建议",
}
LEGACY_LAYER_LABELS = {
    "character": "字符层",
    "vocabulary": "词汇层",
    "sentence": "句子层",
    "format": "标点/格式层",
    "discourse": "语篇/语体层",
    "security": "合规/安全层",
}
LEGACY_SUMMARY_LABELS = {
    "by_type": LEGACY_TYPE_LABELS,
    "by_severity": LEGACY_SEVERITY_LABELS,
    "by_layer": LEGACY_LAYER_LABELS,
}


class Scenario(StrEnum):
    GENERAL = "general"
    ACADEMIC = "academic"
    BUSINESS = "business"
    LEGAL = "legal"
    NEWS = "news"
    TECHNICAL = "technical"


class GlossaryTerm(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    original: str = Field(min_length=1, max_length=200)
    standard: str = Field(max_length=200)


class VerificationOptions(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario: Scenario = Scenario.GENERAL
    enable_security: bool = True
    enable_sensitive: bool = True
    enable_ad_extreme: bool = False
    custom_glossary: tuple[GlossaryTerm, ...] = Field(
        default=(),
        max_length=MAX_CUSTOM_GLOSSARY_TERMS,
    )
    banned_words: tuple[BoundedOptionText, ...] = Field(
        default=(),
        max_length=MAX_BANNED_WORDS,
    )

    @field_validator("banned_words", mode="before")
    @classmethod
    def normalize_banned_words(cls, value: object) -> object:
        if not isinstance(value, tuple | list):
            return value
        normalized: list[object] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                normalized.append(item)
                continue
            word = item.strip()
            if word and word not in seen:
                normalized.append(word)
                seen.add(word)
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_serialized_size(self) -> VerificationOptions:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        if len(encoded) > MAX_VERIFICATION_OPTIONS_JSON_BYTES:
            raise ValueError("Verification options exceed the serialized size limit.")
        return self


def encode_verification_options(
    options: VerificationOptions,
) -> dict[str, JsonValue]:
    return options.model_dump(mode="json")


def decode_verification_options(payload: object) -> VerificationOptions:
    if payload is None or payload == {}:
        return VerificationOptions()
    if not isinstance(payload, dict):
        raise ValueError("Persisted verification options must be a JSON object.")
    return VerificationOptions.model_validate(payload)


class VerificationStatistics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    char_count: int = Field(ge=0)
    char_count_no_space: int = Field(ge=0)
    line_count: int = Field(ge=0)
    paragraph_count: int = Field(ge=0)
    language: Literal["zh", "en"]
    primary_count: int = Field(ge=0)
    primary_label: str


class VerificationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int = Field(ge=0)
    by_type: dict[str, SummaryCount] = Field(default_factory=dict)
    by_severity: dict[str, SummaryCount] = Field(default_factory=dict)
    by_rule: dict[str, SummaryCount] = Field(default_factory=dict)
    by_layer: dict[str, SummaryCount] = Field(default_factory=dict)
    llm_review: dict[str, JsonValue] | None = None

    @field_validator("llm_review", mode="before")
    @classmethod
    def canonicalize_review_metadata(cls, value: object) -> object:
        return _canonicalize_json_containers(value)


class VerificationExecutionMode(StrEnum):
    SYNCHRONOUS = "synchronous"
    ASYNCHRONOUS = "asynchronous"


class VerificationAnalysisMode(StrEnum):
    LOCAL_ONLY = "local_only"
    LOCAL_PLUS_LLM = "local_plus_llm"


class DocumentRevisionKind(StrEnum):
    REVIEW = "review"
    MANUAL = "manual"


class ReviewRevisionDraft(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    revision_id: UUID
    document_id: UUID
    verification_run_id: UUID
    source_version: str = Field(min_length=1)
    parent_revision_id: UUID | None = None
    kind: DocumentRevisionKind
    text: str

    @model_validator(mode="after")
    def validate_parent(self) -> ReviewRevisionDraft:
        if self.parent_revision_id == self.revision_id:
            raise ValueError("revision cannot be its own parent")
        return self


class PersistedDocumentRevision(ReviewRevisionDraft):
    revision_number: int = Field(gt=0)
    created_at: datetime
    persistence_state: Literal["persisted"] = "persisted"


class VerificationDegradation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_degraded: bool = False
    reasons: tuple[str, ...] = ()


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_run_id: UUID
    document_id: UUID
    source_version: str
    source_name: str
    file_type: FileType
    scenario: Scenario
    text: str
    blocks: tuple[TextBlock, ...]
    parser_name: str
    parser_version: str
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    ocr_requirement: OcrRequirement | None = None
    stats: VerificationStatistics
    issues: tuple[Issue, ...]
    summary: VerificationSummary
    execution_mode: VerificationExecutionMode
    analysis_mode: VerificationAnalysisMode
    dictionary_versions: dict[str, str] = Field(default_factory=dict)
    degradation: VerificationDegradation = Field(default_factory=VerificationDegradation)

    @model_validator(mode="after")
    def validate_issues_and_summary(self) -> VerificationResult:
        DocumentModel(
            document_id=self.document_id,
            source_version=self.source_version,
            file_type=self.file_type,
            source_name=self.source_name,
            text=self.text,
            blocks=list(self.blocks),
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            metadata=self.metadata,
        )
        if self.ocr_requirement != self.metadata.pdf_ocr_requirement:
            raise ValueError("OCR requirement must match document metadata")
        blocks_by_id = {block.block_id: block for block in self.blocks}
        for issue in self.issues:
            if issue.document_id != self.document_id:
                raise ValueError("issue document ownership must match the verification result")
            if issue.verification_run_id != self.verification_run_id:
                raise ValueError("issue run ownership must match the verification result")
            if issue.end > len(self.text):
                raise ValueError("issue range exceeds verification result text")
            if self.text[issue.start:issue.end] != issue.original:
                raise ValueError("issue original text must match verification result text")
            if issue.block_id is None:
                continue
            block = blocks_by_id.get(issue.block_id)
            if block is None:
                raise ValueError("issue block must exist in the verification result")
            if issue.start < block.global_start or issue.end > block.global_end:
                raise ValueError("issue global range must be contained by its block")
            if issue.block_start is None or issue.block_end is None:
                raise ValueError("issue block offsets must be present for its block")
            expected_block_start = block.block_start + issue.start - block.global_start
            expected_block_end = block.block_start + issue.end - block.global_start
            if (
                issue.block_start != expected_block_start
                or issue.block_end != expected_block_end
            ):
                raise ValueError("issue local offsets must map exactly to global offsets")
            local_start = issue.block_start - block.block_start
            local_end = issue.block_end - block.block_start
            if block.text[local_start:local_end] != issue.original:
                raise ValueError("issue original text must match its block slice")

        if self.summary.total != len(self.issues):
            raise ValueError("summary total must match the issue count")

        expected_counts = {
            "by_type": Counter(issue.type for issue in self.issues),
            "by_severity": Counter(issue.severity.value for issue in self.issues),
            "by_rule": Counter(issue.rule_id for issue in self.issues),
            "by_layer": Counter(issue.layer for issue in self.issues),
        }
        for field_name, expected in expected_counts.items():
            actual = getattr(self.summary, field_name)
            if sum(actual.values()) != len(self.issues):
                raise ValueError(f"summary {field_name} total must match the issue count")
            allowed_counts = [dict(expected)]
            if labels := LEGACY_SUMMARY_LABELS.get(field_name):
                localized: Counter[str] = Counter()
                for key, count in expected.items():
                    localized[labels.get(key, key)] += count
                allowed_counts.append(dict(localized))
            if actual not in allowed_counts:
                raise ValueError(f"summary {field_name} counts must match issues")
        return self


def _canonicalize_json_containers(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _canonicalize_json_containers(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonicalize_json_containers(item) for item in value]
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("JSON numbers must be finite")
    return value
