from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from text_verification.compatibility.adapters import source_version_for_file
from text_verification.document_processing.errors import (
    OcrProcessingError,
    OcrUnavailableError,
)
from text_verification.document_processing.image_regions import (
    ImageRegion,
    detect_non_text_image_regions,
)
from text_verification.document_processing.image_tables import detect_grid_tables
from text_verification.document_processing.image_validation import (
    ImageValidationError,
    validate_image_file,
)
from text_verification.document_processing.layout import (
    OcrLayoutElement,
    build_ocr_layout,
)
from text_verification.document_processing.ocr_normalization import (
    coalesce_image_ocr_boxes,
    normalize_ocr_boxes,
)
from text_verification.document_processing.ocr_provider import (
    OcrRecognizer,
    OcrTextBox,
    SupportedOcrLanguage,
)
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.ports import (
    VerificationProgressObserver,
    VerificationProgressStage,
)
from text_verification.parsers.errors import ParserError

_PARSER_NAME = "rapidocr-image"
_PARSER_VERSION = "1"


@dataclass(frozen=True)
class ImageResourceLimits:
    max_file_bytes: int = 25 * 1024 * 1024
    max_width: int = 5_000
    max_height: int = 5_000
    max_pixels: int = 20_000_000
    max_decoded_bytes: int = 60_000_000
    max_ocr_boxes: int = 5_000
    max_ocr_text_characters: int = 1_000_000
    max_ocr_candidate_checks: int = 250_000


@dataclass(frozen=True)
class ImageParser:
    file_type: Literal[FileType.PNG, FileType.JPG]
    ocr: OcrRecognizer | None
    limits: ImageResourceLimits = ImageResourceLimits()
    ocr_language: SupportedOcrLanguage = "zh"

    @property
    def supported_type(self) -> FileType:
        return self.file_type

    def with_ocr_language(self, language: SupportedOcrLanguage) -> ImageParser:
        return ImageParser(
            file_type=self.file_type,
            ocr=self.ocr,
            limits=self.limits,
            ocr_language=language,
        )

    def parse(self, source_path: Path) -> DocumentModel:
        return self._parse(source_path, progress_observer=None)

    def parse_with_progress(
        self,
        source_path: Path,
        *,
        progress_observer: VerificationProgressObserver,
    ) -> DocumentModel:
        return self._parse(source_path, progress_observer=progress_observer)

    def _parse(
        self,
        source_path: Path,
        *,
        progress_observer: VerificationProgressObserver | None,
    ) -> DocumentModel:
        try:
            image = validate_image_file(
                source_path,
                self.file_type,
                max_file_bytes=self.limits.max_file_bytes,
                max_width=self.limits.max_width,
                max_height=self.limits.max_height,
                max_pixels=self.limits.max_pixels,
                max_decoded_bytes=self.limits.max_decoded_bytes,
            )
        except ImageValidationError as error:
            raise ParserError(str(error)) from error
        if self.ocr is None:
            raise OcrUnavailableError()
        if progress_observer is not None:
            progress_observer(VerificationProgressStage.OCR)
        recognized = self.ocr.recognize(image.content, self.ocr_language)
        boxes = coalesce_image_ocr_boxes(
            normalize_ocr_boxes(
                recognized,
                page_number=1,
                page_bbox=(0.0, 0.0, float(image.width), float(image.height)),
                raster_width=image.width,
                raster_height=image.height,
                max_boxes=self.limits.max_ocr_boxes,
                max_text_characters=self.limits.max_ocr_text_characters,
            ),
            max_candidate_checks=self.limits.max_ocr_candidate_checks,
        )
        layout = build_ocr_layout(
            boxes,
            language=self.ocr_language,
            max_boxes=self.limits.max_ocr_boxes,
            max_candidate_checks=self.limits.max_ocr_candidate_checks,
            grid_tables=detect_grid_tables(
                image, boxes, language=self.ocr_language,
                max_candidate_checks=self.limits.max_ocr_candidate_checks,
            ),
        )
        image_regions = detect_non_text_image_regions(
            image,
            [OcrTextBox(text=box.text, confidence=box.confidence, bbox=box.quad) for box in boxes],
            excluded_bboxes=tuple(table.bbox for table in layout.tables),
        )
        blocks, text = _canonical_blocks(layout.elements, image_regions, dpi=image.dpi)
        if not text.strip():
            raise OcrProcessingError(
                "OCR did not detect any text in the image.",
                code="ocr_no_text",
                retryable=False,
            )
        source_version = source_version_for_file(source_path)
        return DocumentModel(
            document_id=uuid5(
                NAMESPACE_URL,
                f"document:{self.file_type.value}:{source_path.name}:{source_version}",
            ),
            source_version=source_version,
            file_type=self.file_type,
            source_name=source_path.name,
            text=text,
            blocks=blocks,
            parser_name=_PARSER_NAME,
            parser_version=_PARSER_VERSION,
        )


def _canonical_blocks(
    elements: tuple[OcrLayoutElement, ...],
    image_regions: tuple[ImageRegion, ...],
    *,
    dpi: float,
) -> tuple[list[TextBlock], str]:
    text_parts: list[str] = []
    blocks: list[TextBlock] = []
    cursor = 0
    for element in elements:
        if text_parts:
            text_parts.append("\n")
            cursor += 1
        start = cursor
        text_parts.append(element.text)
        cursor += len(element.text)
        if element.kind == "table_cell":
            block_id = (
                f"ocr-image-table-{element.table_index}"
                f"-row-{element.row_index}-cell-{element.cell_index}"
            )
        else:
            block_id = f"ocr-image-{element.kind}-{element.paragraph_index}"
        source_locator: dict[str, object] = {
            "locator_kind": "ocr",
            "source": "ocr",
            "page": 1,
            "language": element.language,
            "confidence": element.confidence,
            "bbox": list(element.bbox),
            "boxes": [
                {
                    "box_index": box.box_index,
                    "text": box.text,
                    "confidence": box.confidence,
                    "bbox": list(box.bbox),
                    "quad": [list(point) for point in box.quad],
                }
                for box in element.boxes
            ],
        }
        if element.paragraph_index is not None:
            source_locator["paragraph_index"] = element.paragraph_index
        if element.table_index is not None:
            source_locator.update(
                {
                    "table_index": element.table_index,
                    "row_index": element.row_index,
                    "cell_index": element.cell_index,
                }
            )
        if (
            element.table_row_count is not None
            and element.table_column_count is not None
            and element.table_bbox is not None
            and element.table_row_bands is not None
        ):
            source_locator["table_shape"] = {
                "rows": element.table_row_count,
                "columns": element.table_column_count,
            }
            source_locator["table_bbox"] = list(element.table_bbox)
            source_locator["table_row_bands"] = [
                list(band) for band in element.table_row_bands
            ]
        style: dict[str, object] = {
            "ocr_confidence": element.confidence,
            "ocr_language": element.language,
        }
        if element.heading_level is not None:
            style["level"] = element.heading_level
        if element.estimated_font_size is not None:
            style["font"] = {"size": element.estimated_font_size * 72.0 / dpi}
        blocks.append(
            TextBlock(
                block_id=block_id,
                kind=element.kind,
                text=element.text,
                global_start=start,
                global_end=cursor,
                block_start=0,
                block_end=len(element.text),
                page=1,
                paragraph_index=element.paragraph_index,
                table_index=element.table_index,
                row_index=element.row_index,
                cell_index=element.cell_index,
                bbox=element.bbox,
                parent_id=None,
                style=style,
                source_locator=source_locator,
            )
        )
    blocks.extend(
        TextBlock(
            block_id=f"source-image-region-{index}",
            kind="image",
            text="",
            global_start=0,
            global_end=0,
            block_start=0,
            block_end=0,
            page=1,
            paragraph_index=None,
            table_index=None,
            row_index=None,
            cell_index=None,
            bbox=region.bbox,
            parent_id=None,
            style={},
            source_locator={
                "locator_kind": "source_image_region",
                "source": "source_image",
                "page": 1,
                "image_index": index,
                "crop_bbox": [region.x0, region.y0, region.x1, region.y1],
            },
        )
        for index, region in enumerate(image_regions)
    )
    ordered = sorted(
        blocks,
        key=lambda block: (
            block.bbox[1] if block.bbox is not None else 0.0,
            block.bbox[0] if block.bbox is not None else 0.0,
            1 if block.kind == "image" else 0,
            block.block_id,
        ),
    )
    text_parts = []
    cursor = 0
    anchored: list[TextBlock] = []
    for block in ordered:
        if block.text:
            if text_parts:
                text_parts.append("\n")
                cursor += 1
            start = cursor
            text_parts.append(block.text)
            cursor += len(block.text)
        else:
            start = cursor
        anchored.append(
            block.model_copy(
                update={
                    "global_start": start,
                    "global_end": cursor,
                }
            )
        )
    return anchored, "".join(text_parts)
