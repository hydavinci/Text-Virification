from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel, ConfigDict

from text_verification.domain.documents import FileType


class CapabilityProfile(StrEnum):
    SYNCHRONOUS_COMPATIBILITY = "synchronous_compatibility"
    ASYNCHRONOUS_JOB = "asynchronous_job"


class FormatCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file_type: FileType
    display_name: str
    extensions: tuple[str, ...]
    mime_types: tuple[str, ...]
    profiles: tuple[CapabilityProfile, ...]
    supports_structure: bool
    supports_ocr: bool
    supports_original_export: bool
    supports_track_changes: bool


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    formats: tuple[FormatCapability, ...]
    format_order_by_profile: dict[CapabilityProfile, tuple[FileType, ...]]

    def for_type(self, file_type: FileType) -> FormatCapability:
        for capability in self.formats:
            if capability.file_type == file_type:
                return capability
        raise KeyError(file_type.value)

    def formats_for_profile(
        self,
        profile: CapabilityProfile,
    ) -> tuple[FormatCapability, ...]:
        return tuple(
            self.for_type(file_type)
            for file_type in self.format_order_by_profile[profile]
        )

    def file_types_for_profile(self, profile: CapabilityProfile) -> tuple[FileType, ...]:
        return tuple(
            capability.file_type for capability in self.formats_for_profile(profile)
        )

    def extensions_for_profile(self, profile: CapabilityProfile) -> frozenset[str]:
        return frozenset(
            extension.removeprefix(".")
            for capability in self.formats_for_profile(profile)
            for extension in capability.extensions
        )

    def api_formats(self, profile: CapabilityProfile) -> list[dict[str, str]]:
        return [
            {
                "ext": capability.file_type.value,
                "name": capability.display_name,
                "accept": ",".join(capability.extensions),
            }
            for capability in self.formats_for_profile(profile)
        ]


@lru_cache(maxsize=1)
def default_capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        formats=(
            FormatCapability(
                file_type=FileType.DOCX,
                display_name="Word 文档",
                extensions=(".docx",),
                mime_types=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
                profiles=(
                    CapabilityProfile.SYNCHRONOUS_COMPATIBILITY,
                    CapabilityProfile.ASYNCHRONOUS_JOB,
                ),
                supports_structure=True,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.DOC,
                display_name="旧版 Word 文档",
                extensions=(".doc",),
                mime_types=("application/msword",),
                profiles=(
                    CapabilityProfile.SYNCHRONOUS_COMPATIBILITY,
                    CapabilityProfile.ASYNCHRONOUS_JOB,
                ),
                supports_structure=True,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.PDF,
                display_name="PDF 文档",
                extensions=(".pdf",),
                mime_types=("application/pdf",),
                profiles=(
                    CapabilityProfile.SYNCHRONOUS_COMPATIBILITY,
                    CapabilityProfile.ASYNCHRONOUS_JOB,
                ),
                supports_structure=True,
                supports_ocr=True,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.TXT,
                display_name="纯文本文件",
                extensions=(".txt",),
                mime_types=("text/plain",),
                profiles=(
                    CapabilityProfile.SYNCHRONOUS_COMPATIBILITY,
                    CapabilityProfile.ASYNCHRONOUS_JOB,
                ),
                supports_structure=False,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.RTF,
                display_name="RTF 文档",
                extensions=(".rtf",),
                mime_types=("application/rtf", "text/rtf"),
                profiles=(
                    CapabilityProfile.SYNCHRONOUS_COMPATIBILITY,
                    CapabilityProfile.ASYNCHRONOUS_JOB,
                ),
                supports_structure=False,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.MARKDOWN,
                display_name="Markdown 文件",
                extensions=(".md",),
                mime_types=("text/markdown", "text/plain"),
                profiles=(
                    CapabilityProfile.SYNCHRONOUS_COMPATIBILITY,
                    CapabilityProfile.ASYNCHRONOUS_JOB,
                ),
                supports_structure=False,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.CSV,
                display_name="CSV 文件",
                extensions=(".csv",),
                mime_types=("text/csv", "text/plain"),
                profiles=(
                    CapabilityProfile.SYNCHRONOUS_COMPATIBILITY,
                    CapabilityProfile.ASYNCHRONOUS_JOB,
                ),
                supports_structure=False,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
        ),
        format_order_by_profile={
            CapabilityProfile.SYNCHRONOUS_COMPATIBILITY: (
                FileType.TXT,
                FileType.DOCX,
                FileType.DOC,
                FileType.PDF,
                FileType.RTF,
                FileType.MARKDOWN,
                FileType.CSV,
            ),
            CapabilityProfile.ASYNCHRONOUS_JOB: (
                FileType.DOCX,
                FileType.DOC,
                FileType.PDF,
                FileType.TXT,
                FileType.RTF,
                FileType.MARKDOWN,
                FileType.CSV,
            ),
        },
    )
