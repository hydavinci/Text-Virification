from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, ConfigDict

from text_verification.domain.documents import FileType


class FormatCapability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file_type: FileType
    display_name: str
    extensions: tuple[str, ...]
    supports_structure: bool
    supports_ocr: bool
    supports_original_export: bool
    supports_track_changes: bool


class CapabilityManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    formats: tuple[FormatCapability, ...]

    def for_type(self, file_type: FileType) -> FormatCapability:
        for capability in self.formats:
            if capability.file_type == file_type:
                return capability
        raise KeyError(file_type.value)


@lru_cache(maxsize=1)
def default_capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        formats=(
            FormatCapability(
                file_type=FileType.DOCX,
                display_name="Word 文档",
                extensions=(".docx",),
                supports_structure=True,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.DOC,
                display_name="旧版 Word 文档",
                extensions=(".doc",),
                supports_structure=True,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.PDF,
                display_name="PDF 文档",
                extensions=(".pdf",),
                supports_structure=True,
                supports_ocr=True,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.TXT,
                display_name="纯文本文件",
                extensions=(".txt",),
                supports_structure=False,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.RTF,
                display_name="RTF 文档",
                extensions=(".rtf",),
                supports_structure=False,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.MARKDOWN,
                display_name="Markdown 文件",
                extensions=(".md",),
                supports_structure=False,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
            FormatCapability(
                file_type=FileType.CSV,
                display_name="CSV 文件",
                extensions=(".csv",),
                supports_structure=False,
                supports_ocr=False,
                supports_original_export=True,
                supports_track_changes=True,
            ),
        )
    )
