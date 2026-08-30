from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FileType(StrEnum):
    DOCX = "docx"
    DOC = "doc"
    PDF = "pdf"
    TXT = "txt"
    RTF = "rtf"
    MARKDOWN = "md"
    CSV = "csv"


class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    kind: Literal["paragraph", "heading", "table_cell", "header", "footer"]
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
        return self


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

    @model_validator(mode="after")
    def validate_blocks(self) -> "DocumentModel":
        for block in self.blocks:
            if block.global_end > len(self.text):
                raise ValueError("block range exceeds document text")
            if self.text[block.global_start:block.global_end] != block.text:
                raise ValueError("block text does not match document text")
        return self
