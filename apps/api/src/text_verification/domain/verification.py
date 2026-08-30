from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from text_verification.domain.documents import FileType
from text_verification.domain.issues import Issue


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
    by_type: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_rule: dict[str, int] = Field(default_factory=dict)
    by_layer: dict[str, int] = Field(default_factory=dict)
    llm_review: dict[str, Any] | None = None


class VerificationExecutionMode(StrEnum):
    RULES_ONLY = "rules_only"
    RULES_WITH_OPTIONAL_LLM = "rules_with_optional_llm"


class VerificationDegradation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_degraded: bool = False
    reasons: tuple[str, ...] = ()


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verification_run_id: UUID
    document_id: UUID
    source_name: str
    file_type: FileType
    scenario: Scenario
    text: str
    stats: VerificationStatistics
    issues: tuple[Issue, ...]
    summary: VerificationSummary
    execution_mode: VerificationExecutionMode
    degradation: VerificationDegradation = Field(default_factory=VerificationDegradation)
