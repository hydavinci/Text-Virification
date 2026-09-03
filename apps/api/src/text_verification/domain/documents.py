from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from text_verification.document_processing.pdf_models import OcrRequirement, PdfDocumentMetadata


class FileType(StrEnum):
    DOCX = "docx"
    DOC = "doc"
    PDF = "pdf"
    TXT = "txt"
    RTF = "rtf"
    MARKDOWN = "md"
    CSV = "csv"


class ExportFormat(StrEnum):
    DOCX_RECONSTRUCTION = "docx_reconstruction"
    ORIGINAL_FORMAT = "original_format"


class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    kind: Literal["paragraph", "heading", "table_cell", "header", "footer", "image"]
    text: str
    global_start: int = Field(ge=0)
    global_end: int = Field(ge=0)
    block_start: int = Field(ge=0)
    block_end: int = Field(ge=0)
    page: int | None
    paragraph_index: int | None
    table_index: int | None
    row_index: int | None
    cell_index: int | None
    bbox: tuple[float, float, float, float] | None
    parent_id: str | None
    style: dict[str, Any]
    source_locator: dict[str, Any]

    @model_validator(mode="after")
    def validate_offsets(self) -> "TextBlock":
        if self.global_end < self.global_start:
            raise ValueError("global_end must be greater than or equal to global_start")
        if self.block_end < self.block_start:
            raise ValueError("block_end must be greater than or equal to block_start")
        if (self.global_end - self.global_start) != len(self.text):
            raise ValueError("global range must match block text length")
        if (self.block_end - self.block_start) != len(self.text):
            raise ValueError("block range must match block text length")
        if self.block_start != 0 or self.block_end != len(self.text):
            raise ValueError("local block range must be anchored to block text")
        return self


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pdf: PdfDocumentMetadata | None = None

    @property
    def pdf_ocr_requirement(self) -> OcrRequirement | None:
        return self.pdf.ocr_requirement if self.pdf is not None else None


class DocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    source_version: str
    file_type: FileType
    source_name: str
    text: str
    blocks: list[TextBlock]
    parser_name: str
    parser_version: str
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)

    @model_validator(mode="after")
    def validate_blocks(self) -> "DocumentModel":
        blocks_by_id = {block.block_id: block for block in self.blocks}
        if len(blocks_by_id) != len(self.blocks):
            raise ValueError("block IDs must be unique")

        for block in self.blocks:
            if block.global_end > len(self.text):
                raise ValueError("block range exceeds document text")
            if self.text[block.global_start:block.global_end] != block.text:
                raise ValueError("block text does not match document text")
            if block.parent_id is not None:
                parent = blocks_by_id.get(block.parent_id)
                if parent is None:
                    raise ValueError("parent block must exist in the document")
                if parent.block_id == block.block_id:
                    raise ValueError("block cannot be its own parent")
                if not (
                    parent.global_start <= block.global_start
                    and block.global_end <= parent.global_end
                ):
                    raise ValueError("parent block must contain its child block")

        ancestors_by_id: dict[str, set[str]] = {}
        for block in self.blocks:
            visited = {block.block_id}
            ancestors: set[str] = set()
            parent_id = block.parent_id
            while parent_id is not None:
                if parent_id in visited:
                    raise ValueError("block parent relationships must not contain cycles")
                visited.add(parent_id)
                ancestors.add(parent_id)
                parent_id = blocks_by_id[parent_id].parent_id
            ancestors_by_id[block.block_id] = ancestors

        for index, first in enumerate(self.blocks):
            for second in self.blocks[index + 1 :]:
                if not (
                    first.global_start < second.global_end
                    and second.global_start < first.global_end
                ):
                    continue
                if (
                    second.block_id in ancestors_by_id[first.block_id]
                    or first.block_id in ancestors_by_id[second.block_id]
                ):
                    continue
                raise ValueError(
                    "block ranges may overlap only through ancestor-descendant containment"
                )
        return self
