from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from text_verification.domain import verification as domain_verification

Scenario = domain_verification.Scenario

# Temporary compatibility re-export while callers migrate to the canonical domain model.
__all__ = [
    "Scenario",
    "GlossaryTerm",
    "ExportReplacement",
    "ExportOriginalRequest",
    "ReportRequest",
]


class GlossaryTerm(BaseModel):
    model_config = ConfigDict(extra="ignore")

    original: str = Field(min_length=1, max_length=200)
    standard: str = Field(max_length=200)


class ExportReplacement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    original: str = Field(min_length=1, max_length=10_000)
    suggestion: str = Field(default="", max_length=10_000)
    position: int | None = Field(default=None, ge=0)
    end_position: int | None = Field(default=None, ge=0)


class ExportOriginalRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_id: UUID
    filename: str = Field(default="修改后文本", max_length=500)
    replacements: list[ExportReplacement] = Field(default_factory=list, max_length=10_000)
    modified_text: str | None = None
    track_changes: bool = False


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    filename: str = Field(default="未知", max_length=500)
    stats: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    issues: list[dict[str, Any]] = Field(default_factory=list, max_length=100_000)
