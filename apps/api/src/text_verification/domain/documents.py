from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from text_verification.document_processing.pdf_models import OcrRequirement, PdfDocumentMetadata
from text_verification.domain.text_edits import (
    MAX_REVISION_TEXT_CODEPOINTS,
    MAX_REVISION_TEXT_UTF8_BYTES,
    TextDiffLimitError,
    validate_revision_text,
)

MAX_CANONICAL_RESULT_BLOCKS = 20_000
MAX_CANONICAL_RESULT_TOTAL_CODEPOINTS = 3 * MAX_REVISION_TEXT_CODEPOINTS
MAX_CANONICAL_RESULT_TOTAL_UTF8_BYTES = 3 * MAX_REVISION_TEXT_UTF8_BYTES


class DocumentPayloadLimitError(ValueError):
    pass


class DocumentPayloadShapeError(ValueError):
    pass


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

    @model_validator(mode="before")
    @classmethod
    def preflight_payload(cls, value: object) -> object:
        preflight_document_payload(value)
        return value

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

        depth_by_id: dict[str, int] = {}
        for block in self.blocks:
            if block.block_id in depth_by_id:
                continue
            path: list[TextBlock] = []
            path_indexes: dict[str, int] = {}
            current = block
            parent_depth = -1
            while True:
                known_depth = depth_by_id.get(current.block_id)
                if known_depth is not None:
                    parent_depth = known_depth
                    break
                if current.block_id in path_indexes:
                    raise ValueError("block parent relationships must not contain cycles")
                path_indexes[current.block_id] = len(path)
                path.append(current)
                if current.parent_id is None:
                    break
                current = blocks_by_id[current.parent_id]
            for path_block in reversed(path):
                parent_depth += 1
                depth_by_id[path_block.block_id] = parent_depth

        children_by_id: dict[str, list[str]] = {
            block.block_id: [] for block in self.blocks
        }
        roots: list[str] = []
        for block in self.blocks:
            if block.parent_id is None:
                roots.append(block.block_id)
            else:
                children_by_id[block.parent_id].append(block.block_id)

        entered_at: dict[str, int] = {}
        exited_at: dict[str, int] = {}
        traversal_index = 0
        for root in roots:
            traversal = [(root, False)]
            while traversal:
                block_id, exiting = traversal.pop()
                if exiting:
                    exited_at[block_id] = traversal_index
                    traversal_index += 1
                    continue
                entered_at[block_id] = traversal_index
                traversal_index += 1
                traversal.append((block_id, True))
                for child_id in reversed(children_by_id[block_id]):
                    traversal.append((child_id, False))

        ordered_blocks = sorted(
            self.blocks,
            key=lambda block: (
                block.global_start,
                -block.global_end,
                depth_by_id[block.block_id],
                block.block_id,
            ),
        )
        active: list[TextBlock] = []
        for block in ordered_blocks:
            while active and active[-1].global_end <= block.global_start:
                active.pop()
            overlapping = (
                _last_block_starting_before(active, block.global_start)
                if block.global_start == block.global_end
                else (active[-1] if active else None)
            )
            if overlapping is not None and not _is_ancestor(
                overlapping.block_id,
                block.block_id,
                entered_at,
                exited_at,
            ):
                raise ValueError(
                    "block ranges may overlap only through ancestor-descendant containment"
                )
            if block.global_start < block.global_end:
                active.append(block)
        return self


def preflight_document_payload(
    value: object,
    *,
    max_blocks: int = MAX_CANONICAL_RESULT_BLOCKS,
    max_total_codepoints: int = MAX_CANONICAL_RESULT_TOTAL_CODEPOINTS,
    max_total_utf8_bytes: int = MAX_CANONICAL_RESULT_TOTAL_UTF8_BYTES,
) -> None:
    if not isinstance(value, Mapping):
        raise DocumentPayloadShapeError(
            "Canonical document payload must be an object."
        )
    text = value.get("text")
    blocks = value.get("blocks")
    if not isinstance(text, str) or not isinstance(blocks, list | tuple):
        raise DocumentPayloadShapeError(
            "Canonical document text and blocks are required."
        )
    if len(blocks) > max_blocks:
        raise DocumentPayloadLimitError(
            "Canonical document block count exceeds the configured limit."
        )
    try:
        validate_revision_text(text)
        total_codepoints = len(text)
        total_utf8_bytes = len(text.encode("utf-8"))
        for entry in blocks:
            block_text: object
            if isinstance(entry, TextBlock):
                block_text = entry.text
            elif isinstance(entry, Mapping):
                block_text = entry.get("text")
            else:
                raise DocumentPayloadShapeError(
                    "Canonical document blocks must be objects."
                )
            if not isinstance(block_text, str):
                raise DocumentPayloadShapeError(
                    "Canonical document block text must be a string."
                )
            total_codepoints += len(block_text)
            total_utf8_bytes += len(block_text.encode("utf-8"))
            if (
                total_codepoints > max_total_codepoints
                or total_utf8_bytes > max_total_utf8_bytes
            ):
                raise DocumentPayloadLimitError(
                    "Canonical document aggregate text exceeds the configured limit."
                )
    except (TextDiffLimitError, UnicodeEncodeError) as error:
        raise DocumentPayloadLimitError(
            "Canonical document text exceeds the configured limit."
        ) from error


def _last_block_starting_before(
    blocks: list[TextBlock],
    position: int,
) -> TextBlock | None:
    low = 0
    high = len(blocks)
    while low < high:
        middle = low + (high - low) // 2
        if blocks[middle].global_start < position:
            low = middle + 1
        else:
            high = middle
    return None if low == 0 else blocks[low - 1]


def _is_ancestor(
    ancestor_id: str,
    descendant_id: str,
    entered_at: dict[str, int],
    exited_at: dict[str, int],
) -> bool:
    return (
        entered_at[ancestor_id] <= entered_at[descendant_id]
        and exited_at[descendant_id] <= exited_at[ancestor_id]
    )
