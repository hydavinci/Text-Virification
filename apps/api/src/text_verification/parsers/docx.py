from __future__ import annotations

from pathlib import Path
from typing import Literal
from uuid import UUID

from docx import Document as WordDocument

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

        for paragraph_index, paragraph in enumerate(document.paragraphs):
            text = "".join(run.text for run in paragraph.runs)
            if not text.strip():
                continue

            runs: list[dict[str, int]] = []
            offset = 0
            for run_index, run in enumerate(paragraph.runs):
                end = offset + len(run.text)
                runs.append({"run_index": run_index, "start": offset, "end": end})
                offset = end

            style_name = paragraph.style.name if paragraph.style is not None else ""
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
                    paragraph_index=paragraph_index,
                    parent_id=None,
                    style={"name": style_name},
                    source_locator={"paragraph_index": paragraph_index, "runs": runs},
                )
            )

        for table_index, table in enumerate(document.tables, start=1):
            cell_index = 1
            for row_index, row in enumerate(table.rows):
                for column_index, cell in enumerate(row.cells):
                    text = "\n".join(
                        paragraph.text.strip() for paragraph in cell.paragraphs if paragraph.text.strip()
                    )
                    if not text:
                        cell_index += 1
                        continue
                    blocks.append(
                        TextBlock(
                            block_id=f"t-{table_index:06d}-{cell_index:06d}",
                            kind="table_cell",
                            text=text,
                            page=None,
                            paragraph_index=None,
                            parent_id=None,
                            style={},
                            source_locator={
                                "table_index": table_index - 1,
                                "row_index": row_index,
                                "column_index": column_index,
                            },
                        )
                    )
                    cell_index += 1

        return DocumentModel(
            document_id=document_id,
            file_type=self.supported_type,
            source_name=source_name,
            version=1,
            blocks=blocks,
            metadata={},
        )
