from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FileType(StrEnum):
    DOCX = "docx"
    PDF = "pdf"
    TXT = "txt"


class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    kind: Literal["paragraph", "heading", "table_cell", "header", "footer"]
    text: str
    page: int | None
    paragraph_index: int | None
    parent_id: str | None
    style: dict[str, Any]
    source_locator: dict[str, Any]


class DocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    file_type: FileType
    source_name: str
    blocks: list[TextBlock]
