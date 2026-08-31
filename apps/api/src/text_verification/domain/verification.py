from __future__ import annotations

from collections import Counter
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from text_verification.domain.documents import FileType
from text_verification.domain.issues import Issue

SummaryCount = Annotated[int, Field(ge=0)]


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
    model_config = ConfigDict(extra="forbid")

    scenario: Scenario = Scenario.GENERAL
    enable_security: bool = True
    enable_sensitive: bool = True
    enable_ad_extreme: bool = False
    custom_glossary: tuple[GlossaryTerm, ...] = ()
    banned_words: tuple[str, ...] = ()


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
    llm_review: dict[str, Any] | None = None


class VerificationExecutionMode(StrEnum):
    SYNCHRONOUS = "synchronous"
    ASYNCHRONOUS = "asynchronous"


class VerificationAnalysisMode(StrEnum):
    LOCAL_ONLY = "local_only"
    LOCAL_PLUS_LLM = "local_plus_llm"


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
    stats: VerificationStatistics
    issues: tuple[Issue, ...]
    summary: VerificationSummary
    execution_mode: VerificationExecutionMode
    analysis_mode: VerificationAnalysisMode
    dictionary_versions: dict[str, str] = Field(default_factory=dict)
    degradation: VerificationDegradation = Field(default_factory=VerificationDegradation)

    @model_validator(mode="after")
    def validate_issues_and_summary(self) -> VerificationResult:
        for issue in self.issues:
            if issue.document_id != self.document_id:
                raise ValueError("issue document ownership must match the verification result")
            if issue.verification_run_id != self.verification_run_id:
                raise ValueError("issue run ownership must match the verification result")
            if issue.end > len(self.text):
                raise ValueError("issue range exceeds verification result text")
            if self.text[issue.start:issue.end] != issue.original:
                raise ValueError("issue original text must match verification result text")

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
            if field_name == "by_rule" and actual != dict(expected):
                raise ValueError("summary by_rule counts must match issues")
            if set(actual).issubset(expected) and actual != dict(expected):
                raise ValueError(f"summary {field_name} counts must match issues")
        return self
