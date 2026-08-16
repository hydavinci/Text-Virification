from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from docx import Document as WordDocument
from docx.document import Document as WordProcessingDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from text_verification.domain.documents import DocumentModel, FileType, ParseError, TextBlock


class DocxParser:
    supported_type = FileType.DOCX

    def parse(
        self,
        source_path: Path,
        *,
        document_id: UUID,
        source_name: str,
    ) -> DocumentModel:
        try:
            document = WordDocument(str(source_path))
        except Exception as error:
            raise ParseError("docx_parse_error", "无法解析 DOCX 文件。") from error

        blocks: list[TextBlock] = []
        heading_index = 1
        paragraph_block_index = 1
        table_block_index = 0
        paragraph_index = 0
        for block in self._iter_body_blocks(document):
            if isinstance(block, Paragraph):
                current_paragraph_index = paragraph_index
                paragraph_index += 1
                text = "".join(run.text for run in block.runs)
                if not text.strip():
                    continue

                style_name = block.style.name if block.style is not None else ""
                if style_name.startswith("Heading"):
                    block_id = f"h-{heading_index:06d}"
                    kind: Literal["heading", "paragraph"] = "heading"
                    heading_index += 1
                else:
                    block_id = f"p-{paragraph_block_index:06d}"
                    kind = "paragraph"
                    paragraph_block_index += 1

                blocks.append(
                    TextBlock(
                        block_id=block_id,
                        kind=kind,
                        text=text,
                        page=None,
                        paragraph_index=current_paragraph_index,
                        parent_id=None,
                        style={"name": style_name},
                        source_locator={
                            "paragraph_index": current_paragraph_index,
                            "runs": self._build_runs(block.runs),
                        },
                    )
                )
                continue

            cell_index = 1
            for row_index, row in enumerate(block.rows):
                for column_index, cell in enumerate(row.cells):
                    text, locator = self._build_cell_locator(
                        cell,
                        table_index=table_block_index,
                        row_index=row_index,
                        column_index=column_index,
                    )
                    if not text:
                        cell_index += 1
                        continue
                    blocks.append(
                        TextBlock(
                            block_id=f"t-{table_block_index + 1:06d}-{cell_index:06d}",
                            kind="table_cell",
                            text=text,
                            page=None,
                            paragraph_index=None,
                            parent_id=None,
                            style={},
                            source_locator=locator,
                        )
                    )
                    cell_index += 1
            table_block_index += 1

        return DocumentModel(
            document_id=document_id,
            file_type=self.supported_type,
            source_name=source_name,
            version=1,
            blocks=blocks,
            metadata={},
        )

    def _iter_body_blocks(
        self,
        document: WordProcessingDocument,
    ) -> Iterator[Paragraph | Table]:
        for child in document.element.body.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, document)
            elif isinstance(child, CT_Tbl):
                yield Table(child, document)

    def _build_runs(self, runs: list[Any]) -> list[dict[str, int]]:
        locators: list[dict[str, int]] = []
        offset = 0
        for run_index, run in enumerate(runs):
            end = offset + len(run.text)
            locators.append({"run_index": run_index, "start": offset, "end": end})
            offset = end
        return locators

    def _build_cell_locator(
        self,
        cell: _Cell,
        *,
        table_index: int,
        row_index: int,
        column_index: int,
    ) -> tuple[str, dict[str, Any]]:
        paragraphs: list[dict[str, Any]] = []
        text_parts: list[str] = []
        text_offset = 0

        for paragraph_index, paragraph in enumerate(cell.paragraphs):
            text = "".join(run.text for run in paragraph.runs)
            if not text.strip():
                continue
            if text_parts:
                text_offset += 1

            runs = self._build_runs(paragraph.runs)
            paragraph_start = text_offset
            paragraph_end = paragraph_start + len(text)
            paragraphs.append(
                {
                    "paragraph_index": paragraph_index,
                    "start": paragraph_start,
                    "end": paragraph_end,
                    "runs": [
                        {
                            "run_index": run["run_index"],
                            "start": paragraph_start + run["start"],
                            "end": paragraph_start + run["end"],
                        }
                        for run in runs
                    ],
                }
            )
            text_parts.append(text)
            text_offset = paragraph_end

        return (
            "\n".join(text_parts),
            {
                "table_index": table_index,
                "row_index": row_index,
                "column_index": column_index,
                "paragraphs": paragraphs,
            },
        )
