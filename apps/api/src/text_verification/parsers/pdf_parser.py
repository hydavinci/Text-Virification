from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import groupby
from math import ceil, isfinite
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

import pymupdf
from pydantic import ValidationError

from text_verification.compatibility.adapters import source_version_for_file
from text_verification.document_processing.errors import OcrOutputError
from text_verification.document_processing.layout import (
    OcrLayoutBox,
    OcrLayoutElement,
    build_ocr_layout,
)
from text_verification.document_processing.ocr_provider import (
    OcrRecognizer,
    OcrTextBox,
    SupportedOcrLanguage,
)
from text_verification.document_processing.pdf_classifier import classify_page
from text_verification.document_processing.pdf_models import (
    OcrRequirement,
    PdfCharacterMappingState,
    PdfDocumentMetadata,
    PdfExtractionWarning,
    PdfImage,
    PdfPageMetadata,
    PdfResourceLimits,
    PdfTable,
    PdfTableCell,
    PdfTextCharacter,
    PdfTextSpan,
    PdfWritingMode,
)
from text_verification.domain.documents import DocumentMetadata, DocumentModel, FileType, TextBlock
from text_verification.parsers.errors import ParserError, PdfResourceLimitError

_PARSER_NAME = "pymupdf-pdf"
_PARSER_VERSION = "3"
_PYMUPDF: Any = pymupdf
_MIN_VISUAL_GAP = 0.5
_FONT_GAP_RATIO = 0.08
_GLYPH_GAP_RATIO = 0.2
_RAWDICT_TEXT_FLAGS = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES
_TABLE_SPATIAL_VISITS_PER_DEPTH = 3
_MAX_TABLE_SPATIAL_NODE_VISITS_PER_PAGE = (
    PdfResourceLimits().max_table_spatial_node_visits_per_page
)
OCR_RENDER_DPI = 144
# A 1% floor removes effectively empty signals without discarding low-confidence text.
MIN_USABLE_OCR_CONFIDENCE = 0.01
_OCR_RASTER_CHANNELS = 3
_OCR_DEDUPE_IOU_THRESHOLD = 0.5
_OCR_DEDUPE_COVERAGE_THRESHOLD = 0.9
_OCR_DUPLICATE_IOU_THRESHOLD = 0.95
_NATIVE_DEDUPE_GRID_SIZE = 64.0
_MAX_NATIVE_GRID_CELLS_PER_REGION = 4_096


@dataclass(frozen=True)
class PdfParser:
    ocr: OcrRecognizer | None = None
    limits: PdfResourceLimits = field(default_factory=PdfResourceLimits)
    ocr_language: SupportedOcrLanguage = "zh"
    supported_type: FileType = field(default=FileType.PDF, init=False)

    def parse(self, source_path: Path) -> DocumentModel:
        source_version = source_version_for_file(source_path)
        try:
            pdf: Any = _PYMUPDF.open(source_path)
        except (pymupdf.FileDataError, OSError) as error:
            raise ParserError("PDF source could not be read.") from error
        try:
            if pdf.is_encrypted and not pdf.authenticate(""):
                raise ParserError("PDF source is encrypted and cannot be read.")
            if pdf.page_count > self.limits.max_pages:
                raise PdfResourceLimitError(
                    limit="max_pages",
                    maximum=self.limits.max_pages,
                    actual=pdf.page_count,
                )
            extracted_pages = tuple(
                _extract_page(
                    page,
                    page_number,
                    self.limits,
                    ocr=self.ocr,
                    ocr_language=self.ocr_language,
                )
                for page_number, page in enumerate(pdf, start=1)
            )
        finally:
            pdf.close()

        pages = tuple(extracted.metadata for extracted in extracted_pages)
        metadata = PdfDocumentMetadata(
            pages=pages,
            warnings=tuple(
                warning
                for extracted in extracted_pages
                for warning in extracted.warnings
            ),
            ocr_requirement=_ocr_requirement(pages),
        )
        blocks, text = _canonical_blocks(
            pages,
            ocr_elements_by_page={
                extracted.metadata.page: extracted.ocr_elements
                for extracted in extracted_pages
                if extracted.ocr_elements
            },
        )
        return DocumentModel(
            document_id=uuid5(
                NAMESPACE_URL,
                f"document:{FileType.PDF.value}:{source_path.name}:{source_version}",
            ),
            source_version=source_version,
            file_type=FileType.PDF,
            source_name=source_path.name,
            text=text,
            blocks=blocks,
            parser_name=_PARSER_NAME,
            parser_version=_PARSER_VERSION,
            metadata=DocumentMetadata(pdf=metadata),
        )


def _extract_page(
    page: Any,
    page_number: int,
    limits: PdfResourceLimits,
    *,
    ocr: OcrRecognizer | None = None,
    ocr_language: SupportedOcrLanguage = "zh",
) -> _ExtractedPage:
    geometry = _PageGeometry(
        page_bbox=_bbox(page.rect),
        rotation_matrix=page.rotation_matrix,
    )
    raw_spans = _extract_raw_spans(page, geometry)
    images, image_warnings = _extract_images(page, page_number, limits, geometry)
    classification = classify_page(
        page,
        page_number,
        image_rectangles=(image.bbox for image in images),
    )
    recognized_boxes: tuple[OcrLayoutBox, ...] | None = None
    if classification.ocr_required and ocr is not None:
        recognized_boxes = _recognize_page(
            page,
            page_number=page_number,
            geometry=geometry,
            ocr=ocr,
            language=ocr_language,
            limits=limits,
        )
    tables, table_warnings = _extract_tables(page, page_number, limits)
    tables = _normalize_tables(tables, geometry)
    all_spans = _extract_spans(raw_spans, [])
    tables, table_character_groups = _align_table_characters(
        tables,
        all_spans,
        limits=limits,
    )
    spans = _residual_spans(all_spans, table_character_groups)
    ocr_elements: tuple[OcrLayoutElement, ...] = ()
    ocr_warnings: tuple[PdfExtractionWarning, ...] = ()
    ocr_resolved = False
    if recognized_boxes is not None:
        if recognized_boxes:
            unique_boxes = _deduplicate_ocr_boxes(
                recognized_boxes,
                spans=tuple(spans),
                tables=tuple(tables),
                limits=limits,
            )
            layout = build_ocr_layout(
                unique_boxes,
                language=ocr_language,
                max_boxes=limits.max_ocr_boxes_per_page,
            )
            ocr_elements = layout.elements
            ocr_resolved = bool(ocr_elements)
        if not ocr_resolved:
            ocr_warnings = (_ocr_warning(page_number),)
    return _ExtractedPage(
        metadata=PdfPageMetadata(
            page=page_number,
            kind=classification.kind,
            page_bbox=geometry.page_bbox,
            text_length=classification.text_length,
            text_density=classification.text_density,
            image_coverage=classification.image_coverage,
            ocr_required=classification.ocr_required and not ocr_resolved,
            spans=tuple(spans),
            tables=tuple(tables),
            images=tuple(images),
        ),
        warnings=tuple((*image_warnings, *table_warnings, *ocr_warnings)),
        ocr_elements=ocr_elements,
    )


def _recognize_page(
    page: Any,
    *,
    page_number: int,
    geometry: _PageGeometry,
    ocr: OcrRecognizer,
    language: SupportedOcrLanguage,
    limits: PdfResourceLimits,
) -> tuple[OcrLayoutBox, ...]:
    payload, raster_width, raster_height = _render_page_for_ocr(page, limits)
    raw_boxes = ocr.recognize(payload, language)
    return _normalize_ocr_boxes(
        raw_boxes,
        page_number=page_number,
        page_bbox=geometry.page_bbox,
        raster_width=raster_width,
        raster_height=raster_height,
        limits=limits,
    )


def _render_page_for_ocr(
    page: Any,
    limits: PdfResourceLimits,
) -> tuple[bytes, int, int]:
    scale = OCR_RENDER_DPI / 72.0
    estimated_width = max(1, ceil(float(page.rect.width) * scale))
    estimated_height = max(1, ceil(float(page.rect.height) * scale))
    _enforce_ocr_raster_limits(
        estimated_width,
        estimated_height,
        estimated_width * estimated_height * _OCR_RASTER_CHANNELS,
        limits,
    )

    pixmap: Any = page.get_pixmap(
        matrix=_PYMUPDF.Matrix(scale, scale),
        colorspace=_PYMUPDF.csRGB,
        alpha=False,
        annots=False,
    )
    try:
        width = int(pixmap.width)
        height = int(pixmap.height)
        raw_bytes = int(pixmap.stride) * height
        _enforce_ocr_raster_limits(width, height, raw_bytes, limits)
        payload = bytes(pixmap.tobytes("png"))
        if len(payload) > limits.max_ocr_raster_bytes:
            raise PdfResourceLimitError(
                limit="max_ocr_raster_bytes",
                maximum=limits.max_ocr_raster_bytes,
                actual=len(payload),
            )
        return payload, width, height
    finally:
        close = getattr(pixmap, "close", None)
        if callable(close):
            close()
        del pixmap


def _enforce_ocr_raster_limits(
    width: int,
    height: int,
    byte_count: int,
    limits: PdfResourceLimits,
) -> None:
    for limit_name, actual, maximum in (
        ("max_ocr_raster_width", width, limits.max_ocr_raster_width),
        ("max_ocr_raster_height", height, limits.max_ocr_raster_height),
        ("max_ocr_raster_pixels", width * height, limits.max_ocr_raster_pixels),
        ("max_ocr_raster_bytes", byte_count, limits.max_ocr_raster_bytes),
    ):
        if actual > maximum:
            raise PdfResourceLimitError(
                limit=limit_name,
                maximum=maximum,
                actual=actual,
            )


def _normalize_ocr_boxes(
    raw_boxes: object,
    *,
    page_number: int,
    page_bbox: tuple[float, float, float, float],
    raster_width: int,
    raster_height: int,
    limits: PdfResourceLimits,
) -> tuple[OcrLayoutBox, ...]:
    if not isinstance(raw_boxes, list):
        raise OcrOutputError("OCR provider must return a list of OcrTextBox values")
    if len(raw_boxes) > limits.max_ocr_boxes_per_page:
        raise PdfResourceLimitError(
            limit="max_ocr_boxes_per_page",
            maximum=limits.max_ocr_boxes_per_page,
            actual=len(raw_boxes),
        )

    normalized: list[
        tuple[str, float, tuple[tuple[float, float], ...]]
    ] = []
    text_characters = 0
    page_width = page_bbox[2] - page_bbox[0]
    page_height = page_bbox[3] - page_bbox[1]
    for raw_box in raw_boxes:
        try:
            box = (
                raw_box
                if isinstance(raw_box, OcrTextBox)
                else OcrTextBox.model_validate(raw_box)
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise OcrOutputError(str(error)) from error
        text_characters += len(box.text)
        if text_characters > limits.max_ocr_text_chars_per_page:
            raise PdfResourceLimitError(
                limit="max_ocr_text_chars_per_page",
                maximum=limits.max_ocr_text_chars_per_page,
                actual=text_characters,
            )
        if any(
            x < 0.0 or x > raster_width or y < 0.0 or y > raster_height
            for x, y in box.bbox
        ):
            raise OcrOutputError("OCR bbox coordinates must be within the rendered page")
        quad = tuple(
            (
                page_bbox[0] + (x / raster_width) * page_width,
                page_bbox[1] + (y / raster_height) * page_height,
            )
            for x, y in box.bbox
        )
        normalized.append((box.text, box.confidence, quad))

    normalized.sort(
        key=lambda item: (
            min(point[1] for point in item[2]),
            min(point[0] for point in item[2]),
            item[0],
            -item[1],
            item[2],
        )
    )
    mapped = tuple(
        OcrLayoutBox(
            page=page_number,
            box_index=index,
            text=text,
            confidence=confidence,
            quad=quad,
        )
        for index, (text, confidence, quad) in enumerate(normalized)
    )
    usable = tuple(
        box
        for box in mapped
        if box.confidence >= MIN_USABLE_OCR_CONFIDENCE
    )
    return _coalesce_ocr_boxes(usable, limits=limits)


def _coalesce_ocr_boxes(
    boxes: tuple[OcrLayoutBox, ...],
    *,
    limits: PdfResourceLimits,
) -> tuple[OcrLayoutBox, ...]:
    if len(boxes) < 2:
        return tuple(
            box.model_copy(update={"box_index": index})
            for index, box in enumerate(boxes)
        )

    ordered = tuple(
        sorted(
            _preconsolidate_exact_ocr_boxes(boxes),
            key=_ocr_box_preference_order,
        )
    )
    if len(ordered) < 2:
        return tuple(
            box.model_copy(update={"box_index": index})
            for index, box in enumerate(ordered)
        )
    ordered_features = tuple(
        _ocr_duplicate_feature(box_index, box)
        for box_index, box in enumerate(ordered)
    )
    candidate_index = _OcrDuplicateCandidateIndex()
    budget = _DuplicateInspectionBudget(
        maximum=limits.max_ocr_duplicate_candidate_inspections_per_page
    )
    clusters: list[_OcrDuplicateCluster] = []
    for box_index, box in enumerate(ordered):
        feature = ordered_features[box_index]
        selected_cluster: int | None = None
        for cluster_index in candidate_index.query(feature, budget=budget):
            if _duplicate_cluster_accepts(
                clusters[cluster_index],
                box,
                feature,
                ordered,
                ordered_features,
            ):
                selected_cluster = cluster_index
                break
        if selected_cluster is None:
            selected_cluster = len(clusters)
            clusters.append(
                _OcrDuplicateCluster.from_feature(
                    representative_index=box_index,
                    feature=feature,
                )
            )
            candidate_index.add(
                selected_cluster,
                _ocr_duplicate_feature(selected_cluster, box),
            )
        else:
            clusters[selected_cluster].add(feature)

    winners = [ordered[cluster.representative_index] for cluster in clusters]
    return tuple(
        box.model_copy(update={"box_index": index})
        for index, box in enumerate(sorted(winners, key=_ocr_box_stable_order))
    )


@dataclass(frozen=True)
class _OcrDuplicateFeature:
    box_index: int
    identity: str
    center_x: float
    center_y: float
    width: float
    height: float


@dataclass
class _DuplicateInspectionBudget:
    maximum: int
    count: int = 0

    def visit(self) -> None:
        self.count += 1
        if self.count > self.maximum:
            raise PdfResourceLimitError(
                limit="max_ocr_duplicate_candidate_inspections_per_page",
                maximum=self.maximum,
                actual=self.count,
            )


@dataclass
class _OcrDuplicateCluster:
    representative_index: int
    min_center_x: float
    max_center_x: float
    min_center_y: float
    max_center_y: float
    min_width: float
    max_width: float
    min_height: float
    max_height: float

    @classmethod
    def from_feature(
        cls,
        *,
        representative_index: int,
        feature: _OcrDuplicateFeature,
    ) -> _OcrDuplicateCluster:
        return cls(
            representative_index=representative_index,
            min_center_x=feature.center_x,
            max_center_x=feature.center_x,
            min_center_y=feature.center_y,
            max_center_y=feature.center_y,
            min_width=feature.width,
            max_width=feature.width,
            min_height=feature.height,
            max_height=feature.height,
        )

    def add(self, feature: _OcrDuplicateFeature) -> None:
        self.min_center_x = min(self.min_center_x, feature.center_x)
        self.max_center_x = max(self.max_center_x, feature.center_x)
        self.min_center_y = min(self.min_center_y, feature.center_y)
        self.max_center_y = max(self.max_center_y, feature.center_y)
        self.min_width = min(self.min_width, feature.width)
        self.max_width = max(self.max_width, feature.width)
        self.min_height = min(self.min_height, feature.height)
        self.max_height = max(self.max_height, feature.height)


@dataclass
class _OcrDuplicateCandidateIndex:
    all_by_x: list[tuple[float, int]] = field(default_factory=list)
    all_x_values: list[float] = field(default_factory=list)
    all_by_y: list[tuple[float, int]] = field(default_factory=list)
    all_y_values: list[float] = field(default_factory=list)
    center_x_by_cluster: dict[int, float] = field(default_factory=dict)
    center_y_by_cluster: dict[int, float] = field(default_factory=dict)

    def add(self, cluster_index: int, feature: _OcrDuplicateFeature) -> None:
        x_position = bisect_right(self.all_x_values, feature.center_x)
        self.all_x_values.insert(x_position, feature.center_x)
        self.all_by_x.insert(x_position, (feature.center_x, cluster_index))
        y_position = bisect_right(self.all_y_values, feature.center_y)
        self.all_y_values.insert(y_position, feature.center_y)
        self.all_by_y.insert(y_position, (feature.center_y, cluster_index))
        self.center_x_by_cluster[cluster_index] = feature.center_x
        self.center_y_by_cluster[cluster_index] = feature.center_y

    def query(
        self,
        feature: _OcrDuplicateFeature,
        *,
        budget: _DuplicateInspectionBudget,
    ) -> Iterator[int]:
        tolerance_x = _ocr_duplicate_position_tolerance(feature.width)
        tolerance_y = _ocr_duplicate_position_tolerance(feature.height)
        yield from _duplicate_xy_range(
            self.all_by_x,
            self.all_x_values,
            self.all_by_y,
            self.all_y_values,
            self.center_x_by_cluster,
            self.center_y_by_cluster,
            feature.center_x,
            tolerance_x,
            feature.center_y,
            tolerance_y,
            budget=budget,
        )


def _preconsolidate_exact_ocr_boxes(
    boxes: tuple[OcrLayoutBox, ...],
) -> tuple[OcrLayoutBox, ...]:
    by_text_geometry: dict[
        tuple[str, tuple[int, ...]],
        OcrLayoutBox,
    ] = {}
    for box in boxes:
        text_geometry_key = (
            _normalized_ocr_identity(box.text),
            _exact_ocr_geometry_key(box),
        )
        existing = by_text_geometry.get(text_geometry_key)
        by_text_geometry[text_geometry_key] = (
            box
            if existing is None
            else min((existing, box), key=_ocr_box_preference_order)
        )

    by_geometry: dict[tuple[int, ...], OcrLayoutBox] = {}
    for box in by_text_geometry.values():
        geometry_key = _exact_ocr_geometry_key(box)
        existing = by_geometry.get(geometry_key)
        by_geometry[geometry_key] = (
            box
            if existing is None
            else min((existing, box), key=_ocr_box_preference_order)
        )
    return tuple(by_geometry.values())


def _exact_ocr_geometry_key(box: OcrLayoutBox) -> tuple[int, ...]:
    return tuple(
        round(coordinate * 1_000_000)
        for point in box.quad
        for coordinate in point
    )


def _ocr_duplicate_feature(
    box_index: int,
    box: OcrLayoutBox,
) -> _OcrDuplicateFeature:
    x0, y0, x1, y1 = box.bbox
    return _OcrDuplicateFeature(
        box_index=box_index,
        identity=_normalized_ocr_identity(box.text),
        center_x=(x0 + x1) / 2.0,
        center_y=(y0 + y1) / 2.0,
        width=x1 - x0,
        height=y1 - y0,
    )


def _duplicate_xy_range(
    x_entries: list[tuple[float, int]],
    x_values: list[float],
    y_entries: list[tuple[float, int]],
    y_values: list[float],
    center_x_by_cluster: dict[int, float],
    center_y_by_cluster: dict[int, float],
    center_x: float,
    tolerance_x: float,
    center_y: float,
    tolerance_y: float,
    *,
    budget: _DuplicateInspectionBudget,
) -> Iterator[int]:
    x_start = bisect_left(x_values, center_x - tolerance_x)
    x_end = bisect_right(x_values, center_x + tolerance_x)
    y_start = bisect_left(y_values, center_y - tolerance_y)
    y_end = bisect_right(y_values, center_y + tolerance_y)
    if x_end - x_start <= y_end - y_start:
        for entry_index in range(x_start, x_end):
            budget.visit()
            entry = x_entries[entry_index]
            if abs(center_y_by_cluster[entry[1]] - center_y) <= tolerance_y:
                yield entry[1]
        return
    for entry_index in range(y_start, y_end):
        budget.visit()
        entry = y_entries[entry_index]
        if abs(center_x_by_cluster[entry[1]] - center_x) <= tolerance_x:
            yield entry[1]


def _duplicate_features_may_match(
    first: _OcrDuplicateFeature,
    second: _OcrDuplicateFeature,
) -> bool:
    return (
        abs(first.center_y - second.center_y)
        <= _ocr_duplicate_position_tolerance(max(first.height, second.height))
        and abs(first.width - second.width)
        <= _ocr_duplicate_size_tolerance(max(first.width, second.width))
        and abs(first.height - second.height)
        <= _ocr_duplicate_size_tolerance(max(first.height, second.height))
    )


def _ocr_duplicate_position_tolerance(size: float) -> float:
    return max(0.25, size * 0.03)


def _ocr_duplicate_size_tolerance(size: float) -> float:
    return max(0.25, size * 0.05)


def _duplicate_cluster_accepts(
    cluster: _OcrDuplicateCluster,
    box: OcrLayoutBox,
    feature: _OcrDuplicateFeature,
    boxes: tuple[OcrLayoutBox, ...],
    features: tuple[_OcrDuplicateFeature, ...],
) -> bool:
    representative = boxes[cluster.representative_index]
    representative_feature = features[cluster.representative_index]
    if not _duplicate_features_may_match(representative_feature, feature):
        return False
    if not _ocr_boxes_are_near_identical(representative, box):
        return False
    return (
        max(cluster.max_center_x, feature.center_x)
        - min(cluster.min_center_x, feature.center_x)
        <= _ocr_duplicate_position_tolerance(
            max(cluster.max_width, feature.width)
        )
        and max(cluster.max_center_y, feature.center_y)
        - min(cluster.min_center_y, feature.center_y)
        <= _ocr_duplicate_position_tolerance(
            max(cluster.max_height, feature.height)
        )
        and max(cluster.max_width, feature.width)
        - min(cluster.min_width, feature.width)
        <= _ocr_duplicate_size_tolerance(
            max(cluster.max_width, feature.width)
        )
        and max(cluster.max_height, feature.height)
        - min(cluster.min_height, feature.height)
        <= _ocr_duplicate_size_tolerance(
            max(cluster.max_height, feature.height)
        )
    )


def _ocr_boxes_are_near_identical(
    first: OcrLayoutBox,
    second: OcrLayoutBox,
) -> bool:
    overlap = _bbox_overlap_area(first.bbox, second.bbox)
    union = _bbox_area(first.bbox) + _bbox_area(second.bbox) - overlap
    return overlap / max(union, 1e-9) >= _OCR_DUPLICATE_IOU_THRESHOLD


def _ocr_box_preference_order(
    box: OcrLayoutBox,
) -> tuple[float, str, tuple[tuple[float, float], ...]]:
    return -box.confidence, _normalized_ocr_identity(box.text), box.quad


def _ocr_box_stable_order(
    box: OcrLayoutBox,
) -> tuple[float, float, float, float, float, str, tuple[tuple[float, float], ...]]:
    x0, y0, x1, y1 = box.bbox
    return (
        y0,
        x0,
        y1,
        x1,
        -box.confidence,
        _normalized_ocr_identity(box.text),
        box.quad,
    )


def _deduplicate_ocr_boxes(
    boxes: tuple[OcrLayoutBox, ...],
    *,
    spans: tuple[PdfTextSpan, ...],
    tables: tuple[PdfTable, ...],
    limits: PdfResourceLimits,
) -> tuple[OcrLayoutBox, ...]:
    spatial_index = _NativeTextSpatialIndex.build(
        _native_text_regions(spans, tables)
    )
    if not spatial_index.has_regions:
        return boxes

    inspection_count = 0
    unique: list[OcrLayoutBox] = []
    for box in sorted(boxes, key=lambda value: (value.bbox[1], value.bbox[0])):
        duplicate = False
        for region in spatial_index.query(box):
            inspection_count += 1
            if inspection_count > limits.max_ocr_dedupe_candidate_inspections_per_page:
                raise PdfResourceLimitError(
                    limit="max_ocr_dedupe_candidate_inspections_per_page",
                    maximum=limits.max_ocr_dedupe_candidate_inspections_per_page,
                    actual=inspection_count,
                )
            if _ocr_box_duplicates_native(box, region.text, region.bbox):
                duplicate = True
                break
        if duplicate:
            continue
        unique.append(box)
    return tuple(unique)


@dataclass(frozen=True)
class _NativeTextRegion:
    region_index: int
    text: str
    identity: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class _NativeTextSpatialIndex:
    buckets: dict[tuple[str, int, int], tuple[_NativeTextRegion, ...]]
    oversized: dict[str, tuple[_NativeTextRegion, ...]]

    @property
    def has_regions(self) -> bool:
        return bool(self.buckets or self.oversized)

    @classmethod
    def build(
        cls,
        raw_regions: list[
            tuple[str, tuple[float, float, float, float] | None]
        ],
    ) -> _NativeTextSpatialIndex:
        mutable_buckets: dict[
            tuple[str, int, int],
            list[_NativeTextRegion],
        ] = {}
        mutable_oversized: dict[str, list[_NativeTextRegion]] = {}
        for region_index, (text, bbox) in enumerate(raw_regions):
            identity = _normalized_ocr_identity(text)
            if not identity or bbox is None:
                continue
            region = _NativeTextRegion(
                region_index=region_index,
                text=text,
                identity=identity,
                bbox=bbox,
            )
            cells = _native_grid_cells(bbox)
            if len(cells) > _MAX_NATIVE_GRID_CELLS_PER_REGION:
                mutable_oversized.setdefault(identity, []).append(region)
                continue
            for cell_x, cell_y in cells:
                mutable_buckets.setdefault(
                    (identity, cell_x, cell_y),
                    [],
                ).append(region)
        return cls(
            buckets={
                key: tuple(sorted(values, key=lambda value: value.region_index))
                for key, values in mutable_buckets.items()
            },
            oversized={
                key: tuple(sorted(values, key=lambda value: value.region_index))
                for key, values in mutable_oversized.items()
            },
        )

    def query(self, box: OcrLayoutBox) -> tuple[_NativeTextRegion, ...]:
        identity = _normalized_ocr_identity(box.text)
        candidates = {
            region.region_index: region
            for cell_x, cell_y in _native_grid_cells(box.bbox)
            for region in self.buckets.get((identity, cell_x, cell_y), ())
        }
        candidates.update(
            (region.region_index, region)
            for region in self.oversized.get(identity, ())
        )
        return tuple(candidates[index] for index in sorted(candidates))


def _native_grid_cells(
    bbox: tuple[float, float, float, float],
) -> tuple[tuple[int, int], ...]:
    x0, y0, x1, y1 = bbox
    first_x = int(x0 // _NATIVE_DEDUPE_GRID_SIZE)
    last_x = int((x1 - 1e-9) // _NATIVE_DEDUPE_GRID_SIZE)
    first_y = int(y0 // _NATIVE_DEDUPE_GRID_SIZE)
    last_y = int((y1 - 1e-9) // _NATIVE_DEDUPE_GRID_SIZE)
    return tuple(
        (cell_x, cell_y)
        for cell_x in range(first_x, last_x + 1)
        for cell_y in range(first_y, last_y + 1)
    )


def _native_text_regions(
    spans: tuple[PdfTextSpan, ...],
    tables: tuple[PdfTable, ...],
) -> list[tuple[str, tuple[float, float, float, float] | None]]:
    regions: list[
        tuple[str, tuple[float, float, float, float] | None]
    ] = [(span.text, span.bbox) for span in spans]
    regions.extend(
        (character.text, character.bbox)
        for span in spans
        for character in span.characters
    )
    regions.extend(
        (cell.text, cell.bbox)
        for table in tables
        for row in table.rows
        for cell in row
    )
    regions.extend(
        (character.text, character.bbox)
        for table in tables
        for row in table.rows
        for cell in row
        for character in cell.characters
    )
    return regions


def _ocr_box_duplicates_native(
    box: OcrLayoutBox,
    native_text: str,
    native_bbox: tuple[float, float, float, float],
) -> bool:
    if _normalized_ocr_identity(box.text) != _normalized_ocr_identity(native_text):
        return False
    overlap = _bbox_overlap_area(box.bbox, native_bbox)
    first_area = _bbox_area(box.bbox)
    second_area = _bbox_area(native_bbox)
    union = first_area + second_area - overlap
    coverage = overlap / max(min(first_area, second_area), 1e-9)
    iou = overlap / max(union, 1e-9)
    return (
        iou >= _OCR_DEDUPE_IOU_THRESHOLD
        or coverage >= _OCR_DEDUPE_COVERAGE_THRESHOLD
    )


def _normalized_ocr_identity(text: str) -> str:
    return "".join(text.split()).casefold()


def _extract_images(
    page: Any,
    page_number: int,
    limits: PdfResourceLimits,
    geometry: _PageGeometry,
) -> tuple[list[PdfImage], list[PdfExtractionWarning]]:
    try:
        raw_images = page.get_images(full=True)
    except pymupdf.FileDataError:
        return [], [_warning(page_number, "image")]
    if len(raw_images) > limits.max_images_per_page:
        raise PdfResourceLimitError(
            limit="max_images_per_page",
            maximum=limits.max_images_per_page,
            actual=len(raw_images),
        )
    xrefs = tuple(dict.fromkeys(int(image[0]) for image in raw_images))
    if len(xrefs) > limits.max_image_xrefs_per_page:
        raise PdfResourceLimitError(
            limit="max_image_xrefs_per_page",
            maximum=limits.max_image_xrefs_per_page,
            actual=len(xrefs),
        )
    images: list[PdfImage] = []
    rectangle_count = 0
    for xref in xrefs:
        try:
            rectangles = page.get_image_rects(xref)
        except pymupdf.FileDataError:
            return images, [_warning(page_number, "image")]
        rectangle_count += len(rectangles)
        if rectangle_count > limits.max_image_rectangles_per_page:
            raise PdfResourceLimitError(
                limit="max_image_rectangles_per_page",
                maximum=limits.max_image_rectangles_per_page,
                actual=rectangle_count,
            )
        for rectangle in rectangles:
            bbox = _normalized_bbox(rectangle, geometry)
            if bbox is None:
                continue
            images.append(PdfImage(image_index=len(images), xref=xref, bbox=bbox))
    return images, []


def _extract_tables(
    page: Any,
    page_number: int,
    limits: PdfResourceLimits,
) -> tuple[list[Any], list[PdfExtractionWarning]]:
    try:
        found_tables = page.find_tables().tables
    except pymupdf.FileDataError:
        return [], [_warning(page_number, "table")]
    if len(found_tables) > limits.max_tables_per_page:
        raise PdfResourceLimitError(
            limit="max_tables_per_page",
            maximum=limits.max_tables_per_page,
            actual=len(found_tables),
        )
    tables: list[Any] = []
    cell_count = 0
    table_text_characters = 0
    for table_index, table in enumerate(found_tables):
        rows = table.rows
        cell_count += sum(len(row.cells) for row in rows)
        if cell_count > limits.max_table_cells_per_page:
            raise PdfResourceLimitError(
                limit="max_table_cells_per_page",
                maximum=limits.max_table_cells_per_page,
                actual=cell_count,
            )
        try:
            extracted_rows = table.extract()
        except pymupdf.FileDataError:
            return tables, [_warning(page_number, "table")]
        column_count = max((len(row.cells) for row in rows), default=0)
        if not rows or not column_count:
            continue
        normalized_rows: list[tuple[tuple[str, object | None], ...]] = []
        for row_index, row in enumerate(rows):
            extracted_row = extracted_rows[row_index] if row_index < len(extracted_rows) else []
            cells: list[tuple[str, object | None]] = []
            for cell_index in range(column_count):
                raw_bbox = row.cells[cell_index] if cell_index < len(row.cells) else None
                raw_text = (
                    extracted_row[cell_index]
                    if cell_index < len(extracted_row)
                    else ""
                )
                text = _normalize_block_text(raw_text or "")
                if len(text) > limits.max_table_text_chars_per_cell:
                    raise PdfResourceLimitError(
                        limit="max_table_text_chars_per_cell",
                        maximum=limits.max_table_text_chars_per_cell,
                        actual=len(text),
                    )
                table_text_characters += len(text)
                if table_text_characters > limits.max_table_text_chars_per_page:
                    raise PdfResourceLimitError(
                        limit="max_table_text_chars_per_page",
                        maximum=limits.max_table_text_chars_per_page,
                        actual=table_text_characters,
                    )
                cells.append((text, raw_bbox))
            normalized_rows.append(tuple(cells))
        tables.append((table_index, table.bbox, tuple(normalized_rows)))
    return tables, []


def _normalize_tables(
    raw_tables: list[Any],
    geometry: _PageGeometry,
) -> list[PdfTable]:
    tables: list[PdfTable] = []
    for table_index, table_bbox, raw_rows in raw_tables:
        normalized_table_bbox = _normalized_bbox(table_bbox, geometry)
        if normalized_table_bbox is None:
            continue
        rows: list[tuple[PdfTableCell, ...]] = []
        for row_index, raw_row in enumerate(raw_rows):
            rows.append(
                tuple(
                    PdfTableCell(
                        text=text,
                        bbox=_normalized_bbox(bbox, geometry) if bbox is not None else None,
                        table_index=table_index,
                        row_index=row_index,
                        cell_index=cell_index,
                    )
                    for cell_index, (text, bbox) in enumerate(raw_row)
                )
            )
        tables.append(
            PdfTable(
                table_index=table_index,
                bbox=normalized_table_bbox,
                row_count=len(rows),
                column_count=len(rows[0]),
                rows=tuple(rows),
            )
        )
    return tables


def _extract_raw_spans(page: Any, geometry: _PageGeometry) -> list[_RawSpan]:
    raw_spans: list[_RawSpan] = []
    raw_line_index = 0
    for block in page.get_text("rawdict", flags=_RAWDICT_TEXT_FLAGS).get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            line_direction = _line_direction(line.get("dir"))
            writing_mode = _writing_mode(line.get("wmode"))
            for span_order, raw_span in enumerate(line.get("spans", [])):
                characters = _raw_span_characters(
                    raw_span,
                    geometry,
                    line_direction=line_direction,
                    writing_mode=writing_mode,
                    line_index=raw_line_index,
                    span_order=span_order,
                )
                if not characters:
                    continue
                bbox = _raw_span_bbox(raw_span, characters, geometry)
                raw_spans.append(
                    _RawSpan(
                        bbox=bbox,
                        raw=raw_span,
                        characters=characters,
                        line_direction=line_direction,
                        writing_mode=writing_mode,
                        line_index=raw_line_index,
                        span_order=span_order,
                    )
                )
            raw_line_index += 1
    return raw_spans


def _extract_spans(raw_spans: list[_RawSpan], tables: list[PdfTable]) -> list[PdfTextSpan]:
    del tables
    spans = [
        PdfTextSpan(
            text=raw_span.text,
            bbox=raw_span.bbox,
            font_name=str(raw_span.raw.get("font", "")) or "unknown",
            font_size=float(_as_any(raw_span.raw.get("size", 0.0))),
            font_flags=int(_as_any(raw_span.raw.get("flags", 0))),
            color=int(_as_any(raw_span.raw.get("color", 0))),
            span_index=index,
            characters=raw_span.characters,
            line_direction=raw_span.line_direction,
            writing_mode=raw_span.writing_mode,
            line_index=raw_span.line_index,
            span_order=raw_span.span_order,
        )
        for index, raw_span in enumerate(raw_spans)
    ]
    return _normalize_span_boundaries(spans)


def _align_table_characters(
    tables: list[PdfTable],
    spans: list[PdfTextSpan],
    *,
    limits: PdfResourceLimits,
) -> tuple[list[PdfTable], set[str]]:
    candidate_index = _build_table_candidate_index(
        tables,
        spans,
        hard_max_node_visits=limits.max_table_spatial_node_visits_per_page,
    )
    aligned_tables: list[PdfTable] = []
    owned_group_ids: set[str] = set()
    for table_position, table in enumerate(tables):
        aligned_rows: list[tuple[PdfTableCell, ...]] = []
        for row_position, row in enumerate(table.rows):
            aligned_cells: list[PdfTableCell] = []
            for cell_position, cell in enumerate(row):
                if not cell.text or cell.bbox is None:
                    aligned_cells.append(cell)
                    continue
                candidates = candidate_index.groups_by_cell.get(
                    (table_position, row_position, cell_position),
                    (),
                )
                candidate_count = sum(
                    len(candidate.character.text) for candidate in candidates
                )
                if candidate_count > limits.max_table_glyph_candidates_per_cell:
                    raise PdfResourceLimitError(
                        limit="max_table_glyph_candidates_per_cell",
                        maximum=limits.max_table_glyph_candidates_per_cell,
                        actual=candidate_count,
                    )
                characters = _align_cell_characters(
                    cell.text,
                    cell.bbox,
                    spans,
                    candidate_groups=_ordered_table_candidate_groups(candidates),
                )
                candidate_group_ids = {
                    candidate.character.group_id for candidate in candidates
                }
                owned_group_ids.update(
                    character.group_id
                    for character in characters
                    if character.group_id is not None
                    and character.group_id in candidate_group_ids
                )
                aligned_cells.append(
                    cell.model_copy(update={"characters": characters})
                )
            aligned_rows.append(tuple(aligned_cells))
        aligned_tables.append(
            table.model_copy(update={"rows": tuple(aligned_rows)})
        )
    return aligned_tables, owned_group_ids


def _residual_spans(
    spans: list[PdfTextSpan],
    owned_group_ids: set[str],
) -> list[PdfTextSpan]:
    residual: list[PdfTextSpan] = []
    for span in spans:
        for owned, characters in groupby(
            span.characters,
            key=lambda character: character.group_id in owned_group_ids,
        ):
            if owned:
                continue
            retained = list(characters)
            retained_bboxes = [
                character.bbox
                for character in retained
                if character.bbox is not None
            ]
            residual_span = _span_with_characters(span, retained)
            if retained_bboxes:
                residual_span = residual_span.model_copy(
                    update={"bbox": _combined_bbox(retained_bboxes)}
                )
            residual.append(residual_span)
    return residual


def _align_cell_characters(
    text: str,
    bbox: tuple[float, float, float, float],
    spans: list[PdfTextSpan],
    *,
    candidate_groups: tuple[dict[str, object], ...] | None = None,
) -> tuple[PdfTextCharacter, ...]:
    resolved_candidates = candidate_groups
    if resolved_candidates is None:
        direct_index = _build_candidate_index(
            (
                _TableCellCandidate(
                    key=(0, 0, 0),
                    bbox=bbox,
                    order=0,
                ),
            ),
            spans,
        )
        resolved_candidates = _ordered_table_candidate_groups(
            direct_index.groups_by_cell.get((0, 0, 0), ())
        )
    if not resolved_candidates:
        return _unmapped_character_models(text)
    target_units = _normalized_alignment_units(text)
    source_groups = [
        (candidate_group, units)
        for candidate_group in resolved_candidates
        if isinstance(candidate_group.get("text"), str)
        and (units := _normalized_alignment_units(str(candidate_group["text"])))
    ]
    source_tokens = [
        unit[0]
        for _, candidate_units in source_groups
        for unit in candidate_units
    ]
    target_tokens = [unit[0] for unit in target_units]
    exact_start = _alignment_pattern_start(source_tokens, target_tokens)
    mapped: dict[int, PdfTextCharacter] = {}
    if exact_start is not None:
        target_index = exact_start
        for candidate_group, candidate_units in source_groups:
            target_start = target_units[target_index][1]
            target_end = target_units[target_index + len(candidate_units) - 1][2]
            aligned_character = _aligned_table_character(
                text=text[target_start:target_end],
                source_start=target_start,
                source_end=target_end,
                source_group=candidate_group,
            )
            if aligned_character is not None:
                mapped[target_start] = aligned_character
            target_index += len(candidate_units)
    else:
        _align_table_subsequence(
            text=text,
            source_groups=source_groups,
            target_units=target_units,
            mapped=mapped,
        )
    aligned: list[PdfTextCharacter] = []
    cursor = 0
    while cursor < len(text):
        mapped_group = mapped.get(cursor)
        if mapped_group is not None:
            aligned.append(mapped_group)
            cursor = mapped_group.source_end
            continue
        character = text[cursor]
        mapping_state = (
            PdfCharacterMappingState.SYNTHETIC_SPACE
            if character.isspace()
            else PdfCharacterMappingState.UNMAPPED
        )
        aligned.append(
            PdfTextCharacter(
                text=character,
                bbox=None,
                source_start=cursor,
                source_end=cursor + 1,
                mapping_state=mapping_state,
                group_id=f"cell-unaligned-{cursor}",
            )
        )
        cursor += 1
    return tuple(aligned)


@dataclass(frozen=True)
class _TableCellCandidate:
    key: tuple[int, int, int]
    bbox: tuple[float, float, float, float]
    order: int


@dataclass(frozen=True)
class _OwnedTableCandidate:
    character: PdfTextCharacter
    span_index: int
    page_order: int
    anchor_bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class _TableCandidateIndex:
    groups_by_cell: dict[tuple[int, int, int], tuple[_OwnedTableCandidate, ...]]


@dataclass(frozen=True)
class _IndexedTableCell:
    candidate: _TableCellCandidate
    bbox: tuple[float, float, float, float]
    area: float


@dataclass(frozen=True)
class _TableCellSpatialNode:
    bbox: tuple[float, float, float, float]
    best_priority: tuple[float, int]
    entry: _IndexedTableCell | None = None
    left: _TableCellSpatialNode | None = None
    right: _TableCellSpatialNode | None = None


@dataclass
class _TableCellSpatialIndex:
    root: _TableCellSpatialNode | None
    unique_cell_count: int
    hard_max_node_visits: int = _MAX_TABLE_SPATIAL_NODE_VISITS_PER_PAGE
    max_node_visits: int | None = None
    node_visits: int = 0
    query_count: int = 0

    @classmethod
    def build(
        cls,
        cells: tuple[_TableCellCandidate, ...],
        *,
        max_node_visits: int | None = None,
        hard_max_node_visits: int = _MAX_TABLE_SPATIAL_NODE_VISITS_PER_PAGE,
    ) -> _TableCellSpatialIndex:
        entries_by_bbox: dict[
            tuple[float, float, float, float],
            _IndexedTableCell,
        ] = {}
        for cell in cells:
            bbox = cell.bbox
            existing = entries_by_bbox.get(bbox)
            if existing is None or cell.order < existing.candidate.order:
                entries_by_bbox[bbox] = _IndexedTableCell(
                    candidate=cell,
                    bbox=bbox,
                    area=_bbox_area(bbox),
                )
        entries = tuple(entries_by_bbox.values())
        return cls(
            root=_build_table_cell_spatial_node(
                entries,
                axis=_table_cell_spatial_axis(entries),
            ),
            unique_cell_count=len(entries),
            hard_max_node_visits=hard_max_node_visits,
            max_node_visits=max_node_visits,
        )

    def owner(
        self,
        bbox: tuple[float, float, float, float],
    ) -> _TableCellCandidate | None:
        if self.root is None:
            return None
        self.query_count += 1
        maximum = (
            self.max_node_visits
            if self.max_node_visits is not None
            else _table_spatial_node_visit_budget(
                self.unique_cell_count,
                self.query_count,
                self.hard_max_node_visits,
            )
        )
        best: _TableCellCandidate | None = None
        best_score: tuple[bool, bool, float, float, int] | None = None

        def node_upper_bound(
            node: _TableCellSpatialNode,
        ) -> tuple[bool, bool, float, float, int] | None:
            self.node_visits += 1
            if self.node_visits > maximum:
                raise PdfResourceLimitError(
                    limit="max_table_spatial_node_visits_per_page",
                    maximum=maximum,
                    actual=self.node_visits,
                )
            return _table_cell_node_upper_bound(node, bbox)

        def search(
            node: _TableCellSpatialNode,
            upper_bound: tuple[bool, bool, float, float, int],
        ) -> None:
            nonlocal best, best_score
            if best_score is not None and upper_bound <= best_score:
                return
            if node.entry is not None:
                cell = node.entry.candidate
                cell_bbox = cell.bbox
                score = _table_cell_ownership_score(cell_bbox, bbox, cell.order)
                if score is not None and (best_score is None or score > best_score):
                    best = cell
                    best_score = score
                return
            ranked_children = [
                (child_bound, child)
                for child in (node.left, node.right)
                if child is not None
                and (child_bound := node_upper_bound(child)) is not None
            ]
            ranked_children.sort(key=lambda value: value[0], reverse=True)
            for child_bound, child in ranked_children:
                search(child, child_bound)

        root_bound = node_upper_bound(self.root)
        if root_bound is not None:
            search(self.root, root_bound)
        return best


def _build_table_cell_spatial_node(
    entries: tuple[_IndexedTableCell, ...],
    *,
    axis: int,
) -> _TableCellSpatialNode | None:
    if not entries:
        return None
    if len(entries) == 1:
        entry = entries[0]
        return _TableCellSpatialNode(
            bbox=entry.bbox,
            best_priority=(entry.area, entry.candidate.order),
            entry=entry,
        )
    bbox = _combined_bbox(entry.bbox for entry in entries)
    other_axis = 1 - axis
    ordered = tuple(
        sorted(
            entries,
            key=lambda entry: (
                entry.bbox[axis] + entry.bbox[axis + 2],
                entry.bbox[other_axis] + entry.bbox[other_axis + 2],
                entry.candidate.order,
            )
        )
    )
    middle = len(ordered) // 2
    left = _build_table_cell_spatial_node(
        ordered[:middle],
        axis=other_axis,
    )
    right = _build_table_cell_spatial_node(
        ordered[middle:],
        axis=other_axis,
    )
    assert left is not None and right is not None
    return _TableCellSpatialNode(
        bbox=bbox,
        best_priority=min(left.best_priority, right.best_priority),
        left=left,
        right=right,
    )


def _table_cell_spatial_axis(entries: tuple[_IndexedTableCell, ...]) -> int:
    if not entries:
        return 0
    x_centers = [entry.bbox[0] + entry.bbox[2] for entry in entries]
    y_centers = [entry.bbox[1] + entry.bbox[3] for entry in entries]
    return (
        0
        if max(x_centers) - min(x_centers) >= max(y_centers) - min(y_centers)
        else 1
    )


def _table_spatial_node_visit_budget(
    unique_cell_count: int,
    glyph_count: int,
    hard_maximum: int,
) -> int:
    if unique_cell_count == 0 or glyph_count == 0:
        return 0
    depth = (unique_cell_count - 1).bit_length() + 1
    workload_budget = (
        unique_cell_count * 2
        + glyph_count * depth * _TABLE_SPATIAL_VISITS_PER_DEPTH
    )
    return min(workload_budget, hard_maximum)


def _table_cell_node_upper_bound(
    node: _TableCellSpatialNode,
    bbox: tuple[float, float, float, float],
) -> tuple[bool, bool, float, float, int] | None:
    overlap_area = _bbox_overlap_area(node.bbox, bbox)
    if overlap_area <= 0.0:
        return None
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    return (
        _bbox_contains(node.bbox, bbox),
        node.bbox[0] <= center_x <= node.bbox[2]
        and node.bbox[1] <= center_y <= node.bbox[3],
        overlap_area,
        -node.best_priority[0],
        -node.best_priority[1],
    )


def _table_cell_ownership_score(
    cell_bbox: tuple[float, float, float, float],
    bbox: tuple[float, float, float, float],
    order: int,
) -> tuple[bool, bool, float, float, int] | None:
    overlap_area = _bbox_overlap_area(cell_bbox, bbox)
    if overlap_area <= 0.0:
        return None
    center_x = (bbox[0] + bbox[2]) / 2
    center_y = (bbox[1] + bbox[3]) / 2
    return (
        _bbox_contains(cell_bbox, bbox),
        cell_bbox[0] <= center_x <= cell_bbox[2]
        and cell_bbox[1] <= center_y <= cell_bbox[3],
        overlap_area,
        -_bbox_area(cell_bbox),
        -order,
    )


def _bbox_contains(
    outer: tuple[float, float, float, float],
    inner: tuple[float, float, float, float],
) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _bbox_overlap_area(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    width = min(first[2], second[2]) - max(first[0], second[0])
    height = min(first[3], second[3]) - max(first[1], second[1])
    return max(width, 0.0) * max(height, 0.0)


def _bbox_area(bbox: tuple[float, float, float, float]) -> float:
    return (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])


def _build_table_candidate_index(
    tables: list[PdfTable],
    spans: list[PdfTextSpan],
    *,
    hard_max_node_visits: int = _MAX_TABLE_SPATIAL_NODE_VISITS_PER_PAGE,
) -> _TableCandidateIndex:
    cells: list[_TableCellCandidate] = []
    order = 0
    for table_position, table in enumerate(tables):
        for row_position, row in enumerate(table.rows):
            for cell_position, cell in enumerate(row):
                if cell.text and cell.bbox is not None:
                    cells.append(
                        _TableCellCandidate(
                            key=(table_position, row_position, cell_position),
                            bbox=cell.bbox,
                            order=order,
                        )
                    )
                order += 1
    return _build_candidate_index(
        tuple(cells),
        spans,
        hard_max_node_visits=hard_max_node_visits,
    )


def _build_candidate_index(
    cells: tuple[_TableCellCandidate, ...],
    spans: list[PdfTextSpan],
    *,
    hard_max_node_visits: int = _MAX_TABLE_SPATIAL_NODE_VISITS_PER_PAGE,
) -> _TableCandidateIndex:
    groups_by_cell: dict[
        tuple[int, int, int],
        list[_OwnedTableCandidate],
    ] = {cell.key: [] for cell in cells}
    if not cells:
        return _TableCandidateIndex(groups_by_cell={})
    spatial_index = _TableCellSpatialIndex.build(
        cells,
        hard_max_node_visits=hard_max_node_visits,
    )
    seen_group_ids: set[str] = set()
    page_order = 0
    for span in spans:
        for character in span.characters:
            group_id = character.group_id
            if group_id is not None:
                if group_id in seen_group_ids:
                    page_order += 1
                    continue
                seen_group_ids.add(group_id)
            owner = spatial_index.owner(character.bbox or span.bbox)
            if owner is not None:
                groups_by_cell[owner.key].append(
                    _OwnedTableCandidate(
                        character=character,
                        span_index=span.span_index,
                        page_order=page_order,
                        anchor_bbox=character.bbox or span.bbox,
                    )
                )
            page_order += 1
    return _TableCandidateIndex(
        groups_by_cell={
            key: tuple(candidates)
            for key, candidates in groups_by_cell.items()
        },
    )


@dataclass(frozen=True)
class _TableCandidateLine:
    candidates: tuple[_OwnedTableCandidate, ...]
    bbox: tuple[float, float, float, float]
    line_index: int
    line_direction: tuple[float, float]
    writing_mode: PdfWritingMode


def _ordered_table_candidate_groups(
    candidates: tuple[_OwnedTableCandidate, ...],
) -> tuple[dict[str, object], ...]:
    if not candidates:
        return ()
    grouped: dict[int, list[_OwnedTableCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.character.raw_line_index, []).append(candidate)
    lines = [
        _TableCandidateLine(
            candidates=tuple(sorted(line, key=lambda candidate: candidate.page_order)),
            bbox=_combined_bbox(candidate.anchor_bbox for candidate in line),
            line_index=line_index,
            line_direction=line[0].character.line_direction,
            writing_mode=line[0].character.writing_mode,
        )
        for line_index, line in grouped.items()
    ]
    visual_order = sorted(
        lines,
        key=lambda line: (
            line.bbox[1],
            line.bbox[0],
            line.line_index,
        ),
    )
    ordered_lines = visual_order.copy()
    run_start = 0
    while run_start < len(ordered_lines):
        if not _candidate_line_preserves_raw_flow(ordered_lines[run_start]):
            run_start += 1
            continue
        run_end = run_start + 1
        while (
            run_end < len(ordered_lines)
            and _candidate_line_preserves_raw_flow(ordered_lines[run_end])
        ):
            run_end += 1
        ordered_lines[run_start:run_end] = sorted(
            ordered_lines[run_start:run_end],
            key=lambda line: line.line_index,
        )
        run_start = run_end
    source_groups: list[dict[str, object]] = []
    for line_position, line in enumerate(ordered_lines):
        if line_position:
            source_groups.append(
                _source_character(
                    text="\n",
                    bbox=None,
                    source_start=0,
                    mapping_state=PdfCharacterMappingState.SYNTHETIC_SPACE,
                    line_index=line.line_index - 1,
                    span_index=None,
                    group_id=f"line-{line.line_index}-separator-before",
                    line_direction=line.line_direction,
                    writing_mode=line.writing_mode,
                    raw_line_index=line.line_index,
                    span_order=None,
                )
            )
        source_groups.extend(
            _source_character(
                text=candidate.character.text,
                bbox=candidate.character.bbox,
                source_start=candidate.character.source_start,
                mapping_state=candidate.character.mapping_state,
                line_index=candidate.character.raw_line_index,
                span_index=candidate.span_index,
                group_id=candidate.character.group_id,
                line_direction=candidate.character.line_direction,
                writing_mode=candidate.character.writing_mode,
                raw_line_index=candidate.character.raw_line_index,
                span_order=candidate.character.span_order,
            )
            for candidate in line.candidates
        )
    return tuple(source_groups)


def _candidate_line_preserves_raw_flow(line: _TableCandidateLine) -> bool:
    return (
        line.writing_mode is PdfWritingMode.VERTICAL
        or line.line_direction[0] <= 0.0
        or line.line_direction[1] != 0.0
    )


def _align_table_subsequence(
    *,
    text: str,
    source_groups: list[
        tuple[dict[str, object], list[tuple[str, int, int]]]
    ],
    target_units: list[tuple[str, int, int]],
    mapped: dict[int, PdfTextCharacter],
) -> None:
    source_positions = _AlignmentTokenPositions.from_tokens(
        [units[0][0] for _, units in source_groups]
    )
    target_positions = _AlignmentTokenPositions.from_tokens(
        [unit[0] for unit in target_units]
    )
    source_index = 0
    target_index = 0
    while source_index < len(source_groups) and target_index < len(target_units):
        candidate_group, candidate_units = source_groups[source_index]
        candidate_token = candidate_units[0][0]
        target_token = target_units[target_index][0]
        if _alignment_tokens_match(candidate_token, target_token):
            if (
                target_index + len(candidate_units) <= len(target_units)
                and all(
                    _alignment_tokens_match(
                        candidate_units[unit_index][0],
                        target_units[target_index + unit_index][0],
                    )
                    for unit_index in range(1, len(candidate_units))
                )
            ):
                target_start = target_units[target_index][1]
                target_end = target_units[target_index + len(candidate_units) - 1][2]
                aligned_character = _aligned_table_character(
                    text=text[target_start:target_end],
                    source_start=target_start,
                    source_end=target_end,
                    source_group=candidate_group,
                )
                if aligned_character is not None:
                    mapped[target_start] = aligned_character
                target_index += len(candidate_units)
            source_index += 1
            continue

        next_source = source_positions.next_after(target_token, source_index + 1)
        next_target = target_positions.next_after(candidate_token, target_index + 1)
        if next_source is not None and (
            next_target is None
            or next_source - source_index < next_target - target_index
        ):
            source_index = next_source
        elif next_target is not None:
            target_index = next_target
        else:
            source_index += 1


def _alignment_pattern_start(
    pattern: list[str],
    target: list[str],
) -> int | None:
    if not pattern:
        return None
    prefix = [0] * len(pattern)
    for index in range(1, len(pattern)):
        matched = prefix[index - 1]
        while True:
            if _alignment_tokens_match(pattern[index], pattern[matched]):
                matched += 1
                break
            if matched == 0:
                break
            matched = prefix[matched - 1]
        prefix[index] = matched
    matched = 0
    for index, token in enumerate(target):
        while True:
            if _alignment_tokens_match(token, pattern[matched]):
                matched += 1
                break
            if matched == 0:
                break
            matched = prefix[matched - 1]
        if matched == len(pattern):
            return index - len(pattern) + 1
    return None


def _normalized_alignment_units(text: str) -> list[tuple[str, int, int]]:
    units: list[tuple[str, int, int]] = []
    cursor = 0
    while cursor < len(text):
        start = cursor
        character = text[cursor]
        if character.isspace():
            cursor += 1
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            units.append((" ", start, cursor))
            continue
        units.append((character, start, start + 1))
        cursor += 1
    return units


@dataclass
class _AlignmentTokenPositions:
    positions: dict[str, list[int]]
    cursors: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_tokens(cls, tokens: list[str]) -> _AlignmentTokenPositions:
        positions: dict[str, list[int]] = {}
        for index, token in enumerate(tokens):
            positions.setdefault(token, []).append(index)
        return cls(positions)

    def next_after(self, token: str, index: int) -> int | None:
        positions = self.positions.get(token)
        if positions is None:
            return None
        cursor = self.cursors.get(token, 0)
        while cursor < len(positions) and positions[cursor] < index:
            cursor += 1
        self.cursors[token] = cursor
        return positions[cursor] if cursor < len(positions) else None


def _alignment_tokens_match(source: str, target: str) -> bool:
    return source == target


def _aligned_table_character(
    *,
    text: str,
    source_start: int,
    source_end: int,
    source_group: dict[str, object],
) -> PdfTextCharacter | None:
    mapping_state_value = source_group.get("mapping_state")
    group_id = source_group.get("group_id")
    direction = _source_group_direction(source_group.get("line_direction"))
    writing_mode = source_group.get("writing_mode")
    raw_line_index = source_group.get("raw_line_index")
    span_order = source_group.get("span_order")
    if (
        not isinstance(mapping_state_value, str)
        or not isinstance(group_id, str)
        or not group_id
        or direction is None
        or isinstance(writing_mode, bool)
        or not isinstance(writing_mode, int)
        or writing_mode not in {mode.value for mode in PdfWritingMode}
        or isinstance(raw_line_index, bool)
        or not isinstance(raw_line_index, int)
        or raw_line_index < 0
        or (
            span_order is not None
            and (
                isinstance(span_order, bool)
                or not isinstance(span_order, int)
                or span_order < 0
            )
        )
    ):
        return None
    try:
        mapping_state = PdfCharacterMappingState(mapping_state_value)
    except ValueError:
        return None
    bbox = _source_group_bbox(source_group.get("bbox"))
    if mapping_state is PdfCharacterMappingState.GLYPH and (
        bbox is None or text.isspace() or span_order is None
    ):
        return None
    if (
        mapping_state is PdfCharacterMappingState.GLYPHLESS
        and (bbox is not None or text.isspace())
    ):
        return None
    if mapping_state is PdfCharacterMappingState.SYNTHETIC_SPACE and (
        bbox is not None or not text.isspace()
    ):
        return None
    if mapping_state is PdfCharacterMappingState.UNMAPPED:
        return None
    return PdfTextCharacter(
        text=text,
        bbox=bbox,
        source_start=source_start,
        source_end=source_end,
        mapping_state=mapping_state,
        group_id=group_id,
        line_direction=direction,
        writing_mode=PdfWritingMode(writing_mode),
        raw_line_index=raw_line_index,
        span_order=span_order,
    )


def _source_group_direction(
    value: object,
) -> tuple[float, float] | None:
    if not isinstance(value, tuple | list) or len(value) != 2:
        return None
    x, y = value
    if (
        isinstance(x, bool)
        or not isinstance(x, int | float)
        or not isfinite(float(x))
        or isinstance(y, bool)
        or not isinstance(y, int | float)
        or not isfinite(float(y))
        or (float(x) == 0.0 and float(y) == 0.0)
    ):
        return None
    return float(x), float(y)


def _source_group_bbox(
    value: object,
) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    if not isinstance(value, tuple | list) or len(value) != 4:
        return None
    coordinates: list[float] = []
    for coordinate in value:
        if (
            isinstance(coordinate, bool)
            or not isinstance(coordinate, int | float)
            or not isfinite(float(coordinate))
        ):
            return None
        coordinates.append(float(coordinate))
    x0, y0, x1, y1 = coordinates
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _unmapped_character_models(text: str) -> tuple[PdfTextCharacter, ...]:
    return tuple(
        PdfTextCharacter(
            text=character,
            bbox=None,
            source_start=source_start,
            source_end=source_start + 1,
            mapping_state=(
                PdfCharacterMappingState.SYNTHETIC_SPACE
                if character.isspace()
                else PdfCharacterMappingState.UNMAPPED
            ),
            group_id=f"cell-unaligned-{source_start}",
        )
        for source_start, character in enumerate(text)
    )


def _line_direction(value: object) -> tuple[float, float]:
    if not isinstance(value, tuple | list) or len(value) != 2:
        raise TypeError("PDF line direction must contain two finite coordinates")
    x, y = value
    if (
        isinstance(x, bool)
        or not isinstance(x, int | float)
        or isinstance(y, bool)
        or not isinstance(y, int | float)
    ):
        raise TypeError("PDF line direction must contain two finite coordinates")
    normalized = float(x), float(y)
    if not all(isfinite(coordinate) for coordinate in normalized):
        raise ValueError("PDF line direction must contain two finite coordinates")
    if normalized == (0.0, 0.0):
        raise ValueError("PDF line direction must not be the zero vector")
    return normalized


def _writing_mode(value: object) -> PdfWritingMode:
    return (
        PdfWritingMode.VERTICAL
        if value == PdfWritingMode.VERTICAL.value
        else PdfWritingMode.HORIZONTAL
    )


def _raw_span_bbox(
    raw_span: dict[str, object],
    characters: tuple[PdfTextCharacter, ...],
    geometry: _PageGeometry,
) -> tuple[float, float, float, float]:
    raw_bbox = raw_span.get("bbox")
    if raw_bbox is not None:
        normalized = _normalized_bbox(raw_bbox, geometry)
        if normalized is not None:
            return normalized
    mapped_bboxes = [
        character.bbox
        for character in characters
        if character.bbox is not None
    ]
    if mapped_bboxes:
        return _combined_bbox(mapped_bboxes)
    return geometry.page_bbox


def _raw_span_characters(
    raw_span: dict[str, object],
    geometry: _PageGeometry,
    *,
    line_direction: tuple[float, float],
    writing_mode: PdfWritingMode,
    line_index: int,
    span_order: int,
) -> tuple[PdfTextCharacter, ...]:
    normalized: list[
        tuple[
            str,
            tuple[float, float, float, float] | None,
            PdfCharacterMappingState,
            str,
        ]
    ] = []
    whitespace_pending = False
    raw_characters = raw_span.get("chars", [])
    if not isinstance(raw_characters, list):
        return ()
    for glyph_index, raw_character in enumerate(raw_characters):
        if not isinstance(raw_character, dict):
            continue
        raw_text = str(raw_character.get("c", ""))
        if not raw_text:
            continue
        group_id = f"line-{line_index}-span-{span_order}-glyph-{glyph_index}"
        if raw_text.isspace():
            if not whitespace_pending:
                normalized.append(
                    (
                        " ",
                        None,
                        PdfCharacterMappingState.SYNTHETIC_SPACE,
                        group_id,
                    )
                )
            whitespace_pending = True
            continue
        bbox_value = raw_character.get("bbox")
        bbox = (
            _normalized_bbox(bbox_value, geometry)
            if bbox_value is not None
            else None
        )
        mapping_state = (
            PdfCharacterMappingState.GLYPH
            if bbox is not None
            else PdfCharacterMappingState.GLYPHLESS
        )
        normalized.append((raw_text, bbox, mapping_state, group_id))
        whitespace_pending = False
    return _characters_with_offsets(
        normalized,
        line_direction=line_direction,
        writing_mode=writing_mode,
        raw_line_index=line_index,
        span_order=span_order,
    )


def _normalize_span_boundaries(spans: list[PdfTextSpan]) -> list[PdfTextSpan]:
    normalized: list[PdfTextSpan] = []
    for line in _visual_lines(tuple(spans)):
        normalized.extend(_normalize_line_span_boundaries(line.spans))
    return [
        span.model_copy(update={"span_index": span_index})
        for span_index, span in enumerate(normalized)
    ]


def _normalize_line_span_boundaries(
    spans: tuple[PdfTextSpan, ...],
) -> list[PdfTextSpan]:
    normalized: list[tuple[PdfTextSpan, list[PdfTextCharacter]]] = []
    pending_whitespace = False
    for span in spans:
        leading_whitespace, content, trailing_whitespace = _boundary_characters(
            span.characters
        )
        if not content:
            pending_whitespace = (
                pending_whitespace or leading_whitespace or trailing_whitespace
            )
            continue
        if not normalized:
            if pending_whitespace or leading_whitespace:
                content.insert(
                    0,
                    _synthetic_character(
                        f"line-{span.line_index}-span-{span.span_order}-leading-space"
                    ),
                )
        else:
            previous_span, previous_characters = normalized[-1]
            if (
                pending_whitespace
                or leading_whitespace
                or _has_visual_word_gap(
                    previous_span,
                    previous_characters,
                    span,
                    content,
                )
            ):
                previous_characters.append(
                    _synthetic_character(
                        f"line-{previous_span.line_index}-span-"
                        f"{previous_span.span_order}-boundary-{span.span_order}"
                    )
                )
        normalized.append((span, content))
        pending_whitespace = trailing_whitespace

    if normalized and pending_whitespace:
        final_span = normalized[-1][0]
        normalized[-1][1].append(
            _synthetic_character(
                f"line-{final_span.line_index}-span-"
                f"{final_span.span_order}-trailing-space"
            )
        )

    return [
        _span_with_characters(span, characters)
        for span, characters in normalized
    ]


def _boundary_characters(
    characters: tuple[PdfTextCharacter, ...],
) -> tuple[bool, list[PdfTextCharacter], bool]:
    first = 0
    while first < len(characters) and characters[first].text.isspace():
        first += 1
    last = len(characters)
    while last > first and characters[last - 1].text.isspace():
        last -= 1
    return first > 0, list(characters[first:last]), last < len(characters)


def _has_visual_word_gap(
    previous_span: PdfTextSpan,
    previous_characters: list[PdfTextCharacter],
    next_span: PdfTextSpan,
    next_characters: list[PdfTextCharacter],
) -> bool:
    previous = next(
        (
            character
            for character in reversed(previous_characters)
            if character.bbox is not None
        ),
        None,
    )
    following = next(
        (character for character in next_characters if character.bbox is not None),
        None,
    )
    if previous is None or following is None:
        return False
    previous_bbox = previous.bbox
    following_bbox = following.bbox
    assert previous_bbox is not None
    assert following_bbox is not None
    direction = previous_span.line_direction
    if (
        next_span.line_direction != direction
        or next_span.writing_mode is not previous_span.writing_mode
    ):
        return False
    previous_interval = _projected_bbox_interval(previous_bbox, direction)
    following_interval = _projected_bbox_interval(following_bbox, direction)
    gap = following_interval[0] - previous_interval[1]
    if gap <= 0:
        return False
    glyph_width = min(
        previous_interval[1] - previous_interval[0],
        following_interval[1] - following_interval[0],
    )
    threshold = max(
        _MIN_VISUAL_GAP,
        min(previous_span.font_size, next_span.font_size) * _FONT_GAP_RATIO,
        glyph_width * _GLYPH_GAP_RATIO,
    )
    return gap >= threshold


def _projected_bbox_interval(
    bbox: tuple[float, float, float, float],
    direction: tuple[float, float],
) -> tuple[float, float]:
    x0, y0, x1, y1 = bbox
    dx, dy = direction
    magnitude = (dx * dx + dy * dy) ** 0.5
    normalized_x = dx / magnitude
    normalized_y = dy / magnitude
    projections = (
        x0 * normalized_x + y0 * normalized_y,
        x0 * normalized_x + y1 * normalized_y,
        x1 * normalized_x + y0 * normalized_y,
        x1 * normalized_x + y1 * normalized_y,
    )
    return min(projections), max(projections)


def _span_with_characters(
    span: PdfTextSpan,
    characters: list[PdfTextCharacter],
) -> PdfTextSpan:
    values = [
        (
            character.text,
            character.bbox,
            character.mapping_state,
            character.group_id or f"span-{span.span_index}-group-{index}",
        )
        for index, character in enumerate(characters)
    ]
    normalized_characters = _characters_with_offsets(
        values,
        line_direction=span.line_direction,
        writing_mode=span.writing_mode,
        raw_line_index=span.line_index,
        span_order=span.span_order,
    )
    return span.model_copy(
        update={
            "text": "".join(character.text for character in normalized_characters),
            "characters": normalized_characters,
        }
    )


def _synthetic_character(group_id: str = "synthetic-space") -> PdfTextCharacter:
    return PdfTextCharacter(
        text=" ",
        bbox=None,
        source_start=0,
        source_end=1,
        mapping_state=PdfCharacterMappingState.SYNTHETIC_SPACE,
        group_id=group_id,
    )


def _characters_with_offsets(
    values: list[
        tuple[
            str,
            tuple[float, float, float, float] | None,
            PdfCharacterMappingState,
            str,
        ]
    ],
    *,
    line_direction: tuple[float, float] = (1.0, 0.0),
    writing_mode: PdfWritingMode = PdfWritingMode.HORIZONTAL,
    raw_line_index: int = 0,
    span_order: int | None = None,
) -> tuple[PdfTextCharacter, ...]:
    characters: list[PdfTextCharacter] = []
    cursor = 0
    for text, bbox, mapping_state, group_id in values:
        characters.append(
            PdfTextCharacter(
                text=text,
                bbox=bbox,
                source_start=cursor,
                source_end=cursor + len(text),
                mapping_state=mapping_state,
                group_id=group_id,
                line_direction=line_direction,
                writing_mode=writing_mode,
                raw_line_index=raw_line_index,
                span_order=span_order,
            )
        )
        cursor += len(text)
    return tuple(characters)


def _canonical_blocks(
    pages: tuple[PdfPageMetadata, ...],
    *,
    ocr_elements_by_page: dict[int, tuple[OcrLayoutElement, ...]] | None = None,
) -> tuple[list[TextBlock], str]:
    ocr_by_page = ocr_elements_by_page or {}
    ordered: list[_ExtractedBlock] = []
    for page in pages:
        visual_lines = _visual_lines(page.spans)
        extracted: list[_ExtractedBlock] = []
        if visual_lines and not page.tables and not page.images:
            extracted.append(_page_block(page.page, visual_lines))
        else:
            extracted.extend(_line_blocks(page.page, visual_lines))
        extracted.extend(_table_blocks(page.page, page.tables))
        extracted.extend(_image_blocks(page.page, page.images))
        extracted.extend(
            _ocr_blocks(
                _offset_ocr_element_indices(
                    ocr_by_page.get(page.page, ()),
                    native_blocks=tuple(extracted),
                    native_tables=page.tables,
                )
            )
        )
        ordered.extend(_order_page_blocks(extracted))
    text_parts: list[str] = []
    blocks: list[TextBlock] = []
    cursor = 0
    for item in ordered:
        start = cursor
        if item.text:
            if text_parts:
                text_parts.append("\n")
                cursor += 1
                start = cursor
            text_parts.append(item.text)
            cursor += len(item.text)
        blocks.append(
            TextBlock(
                block_id=item.block_id,
                kind=item.kind,
                text=item.text,
                global_start=start,
                global_end=cursor,
                block_start=0,
                block_end=len(item.text),
                page=item.page,
                paragraph_index=item.paragraph_index,
                table_index=item.table_index,
                row_index=item.row_index,
                cell_index=item.cell_index,
                bbox=item.bbox,
                parent_id=None,
                style=item.style,
                source_locator=item.source_locator,
            )
        )
    return blocks, "".join(text_parts)


@dataclass(frozen=True)
class _VisualLine:
    spans: tuple[PdfTextSpan, ...]
    bbox: tuple[float, float, float, float]
    line_index: int
    line_direction: tuple[float, float]
    writing_mode: PdfWritingMode

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans)


@dataclass(frozen=True)
class _RawSpan:
    bbox: tuple[float, float, float, float]
    raw: dict[str, object]
    characters: tuple[PdfTextCharacter, ...]
    line_direction: tuple[float, float]
    writing_mode: PdfWritingMode
    line_index: int
    span_order: int

    @property
    def text(self) -> str:
        return "".join(character.text for character in self.characters)


@dataclass(frozen=True)
class _ExtractedPage:
    metadata: PdfPageMetadata
    warnings: tuple[PdfExtractionWarning, ...]
    ocr_elements: tuple[OcrLayoutElement, ...] = ()


@dataclass(frozen=True)
class _PageGeometry:
    page_bbox: tuple[float, float, float, float]
    rotation_matrix: Any


def _visual_lines(spans: tuple[PdfTextSpan, ...]) -> list[_VisualLine]:
    grouped: dict[int, list[PdfTextSpan]] = {}
    for span in spans:
        grouped.setdefault(span.line_index, []).append(span)
    lines = [
        _VisualLine(
            spans=tuple(line),
            bbox=_combined_bbox(span.bbox for span in line),
            line_index=line[0].line_index,
            line_direction=line[0].line_direction,
            writing_mode=line[0].writing_mode,
        )
        for line in grouped.values()
    ]
    visual_order = sorted(
        lines,
        key=lambda line: (
            line.bbox[1],
            line.bbox[0],
            line.line_index,
        ),
    )
    run_start = 0
    while run_start < len(visual_order):
        if not _line_preserves_raw_flow(visual_order[run_start]):
            run_start += 1
            continue
        run_end = run_start + 1
        while (
            run_end < len(visual_order)
            and _line_preserves_raw_flow(visual_order[run_end])
        ):
            run_end += 1
        visual_order[run_start:run_end] = sorted(
            visual_order[run_start:run_end],
            key=lambda line: line.line_index,
        )
        run_start = run_end
    return visual_order


def _line_preserves_raw_flow(line: _VisualLine) -> bool:
    return (
        line.writing_mode is PdfWritingMode.VERTICAL
        or line.line_direction[0] <= 0.0
        or line.line_direction[1] != 0.0
    )


@dataclass(frozen=True)
class _ExtractedBlock:
    block_id: str
    kind: Literal["paragraph", "heading", "table_cell", "image"]
    text: str
    page: int
    bbox: tuple[float, float, float, float]
    ordinal: int
    paragraph_index: int | None
    table_index: int | None
    row_index: int | None
    cell_index: int | None
    style: dict[str, object]
    source_locator: dict[str, object]
    preserve_raw_flow: bool


def _order_page_blocks(items: list[_ExtractedBlock]) -> list[_ExtractedBlock]:
    source_order = {id(item): index for index, item in enumerate(items)}
    visual_order = sorted(items, key=_visual_block_order)
    run_start = 0
    while run_start < len(visual_order):
        if not visual_order[run_start].preserve_raw_flow:
            run_start += 1
            continue
        run_end = run_start + 1
        while (
            run_end < len(visual_order)
            and visual_order[run_end].preserve_raw_flow
        ):
            run_end += 1
        visual_order[run_start:run_end] = sorted(
            visual_order[run_start:run_end],
            key=lambda item: (item.ordinal, source_order[id(item)]),
        )
        run_start = run_end
    return visual_order


def _visual_block_order(item: _ExtractedBlock) -> tuple[float, float, int, int]:
    return (
        item.bbox[1],
        item.bbox[0],
        _kind_order(item.kind),
        item.ordinal,
    )


def _page_block(page: int, lines: list[_VisualLine]) -> _ExtractedBlock:
    text, segments, characters = _lines_text_and_source_metadata(lines)
    first = lines[0].spans[0]
    return _ExtractedBlock(
        block_id=f"page-{page}",
        kind="paragraph",
        text=text,
        page=page,
        bbox=_combined_bbox(line.bbox for line in lines),
        ordinal=0,
        paragraph_index=0,
        table_index=None,
        row_index=None,
        cell_index=None,
        style={
            "font": _font_style(first),
            "spans": [
                span.model_dump(mode="json")
                for line in lines
                for span in line.spans
            ],
        },
        source_locator={
            "locator_kind": "page",
            "page": page,
            "segments": segments,
            "characters": characters,
        },
        preserve_raw_flow=False,
    )


def _line_blocks(page: int, lines: list[_VisualLine]) -> list[_ExtractedBlock]:
    blocks: list[_ExtractedBlock] = []
    for line_index, line in enumerate(lines):
        segments, characters, _ = _line_source_metadata(
            line.spans,
            start=0,
            line_index=line_index,
        )
        blocks.append(
            _ExtractedBlock(
                block_id=f"pdf-page-{page}-line-{line_index}",
                kind="paragraph",
                text=line.text,
                page=page,
                bbox=line.bbox,
                ordinal=line.line_index,
                paragraph_index=line_index,
                table_index=None,
                row_index=None,
                cell_index=None,
                style={
                    "font": _font_style(line.spans[0]),
                    "spans": [span.model_dump(mode="json") for span in line.spans],
                },
                source_locator={
                    "locator_kind": "pdf_line",
                    "page": page,
                    "line_index": line_index,
                    "segments": segments,
                    "characters": characters,
                },
                preserve_raw_flow=_line_preserves_raw_flow(line),
            )
        )
    return blocks


def _table_blocks(page: int, tables: tuple[PdfTable, ...]) -> list[_ExtractedBlock]:
    return [
        _ExtractedBlock(
            block_id=f"pdf-page-{page}-table-{cell.table_index}-row-{cell.row_index}-cell-{cell.cell_index}",
            kind="table_cell",
            text=cell.text,
            page=page,
            bbox=cell.bbox,
            ordinal=cell.row_index * 10_000 + cell.cell_index,
            paragraph_index=None,
            table_index=cell.table_index,
            row_index=cell.row_index,
            cell_index=cell.cell_index,
            style={},
            source_locator={
                "locator_kind": "table_cell",
                "page": page,
                "table_index": cell.table_index,
                "row_index": cell.row_index,
                "cell_index": cell.cell_index,
                "bbox": list(cell.bbox),
                "segments": _line_segments_from_text(cell.text, cell.bbox),
                "characters": _table_cell_source_characters(cell),
            },
            preserve_raw_flow=False,
        )
        for table in tables
        for row in table.rows
        for cell in row
        if cell.text and cell.bbox is not None
    ]


def _image_blocks(page: int, images: tuple[PdfImage, ...]) -> list[_ExtractedBlock]:
    return [
        _ExtractedBlock(
            block_id=f"pdf-page-{page}-image-{image.image_index}",
            kind="image",
            text="",
            page=page,
            bbox=image.bbox,
            ordinal=image.image_index,
            paragraph_index=None,
            table_index=None,
            row_index=None,
            cell_index=None,
            style={},
            source_locator={
                "locator_kind": "image",
                "page": page,
                "image_index": image.image_index,
                "xref": image.xref,
                "bbox": list(image.bbox),
            },
            preserve_raw_flow=False,
        )
        for image in images
    ]


def _ocr_blocks(elements: tuple[OcrLayoutElement, ...]) -> list[_ExtractedBlock]:
    blocks: list[_ExtractedBlock] = []
    for ordinal, element in enumerate(elements):
        if element.kind == "table_cell":
            block_id = (
                f"ocr-page-{element.page}-table-{element.table_index}"
                f"-row-{element.row_index}-cell-{element.cell_index}"
            )
        else:
            block_id = (
                f"ocr-page-{element.page}-{element.kind}-{element.paragraph_index}"
            )
        boxes = [
            {
                "box_index": box.box_index,
                "text": box.text,
                "confidence": box.confidence,
                "bbox": list(box.bbox),
                "quad": [list(point) for point in box.quad],
            }
            for box in element.boxes
        ]
        source_locator: dict[str, object] = {
            "locator_kind": "ocr",
            "source": "ocr",
            "page": element.page,
            "language": element.language,
            "confidence": element.confidence,
            "bbox": list(element.bbox),
            "boxes": boxes,
        }
        if len(element.boxes) == 1:
            source_locator["quad"] = [list(point) for point in element.boxes[0].quad]
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
        blocks.append(
            _ExtractedBlock(
                block_id=block_id,
                kind=element.kind,
                text=element.text,
                page=element.page,
                bbox=element.bbox,
                ordinal=ordinal,
                paragraph_index=element.paragraph_index,
                table_index=element.table_index,
                row_index=element.row_index,
                cell_index=element.cell_index,
                style={
                    "source": "ocr",
                    "language": element.language,
                    "confidence": element.confidence,
                },
                source_locator=source_locator,
                preserve_raw_flow=False,
            )
        )
    return blocks


def _offset_ocr_element_indices(
    elements: tuple[OcrLayoutElement, ...],
    *,
    native_blocks: tuple[_ExtractedBlock, ...],
    native_tables: tuple[PdfTable, ...],
) -> tuple[OcrLayoutElement, ...]:
    paragraph_offset = 1 + max(
        (
            block.paragraph_index
            for block in native_blocks
            if block.paragraph_index is not None
        ),
        default=-1,
    )
    native_table_indices = tuple(
        block.table_index
        for block in native_blocks
        if block.table_index is not None
    ) + tuple(table.table_index for table in native_tables)
    table_offset = 1 + max(
        native_table_indices,
        default=-1,
    )
    return tuple(
        element.model_copy(
            update=(
                {"table_index": element.table_index + table_offset}
                if element.table_index is not None
                else {"paragraph_index": element.paragraph_index + paragraph_offset}
                if element.paragraph_index is not None
                else {}
            )
        )
        for element in elements
    )


def _lines_text_and_source_metadata(
    lines: list[_VisualLine],
) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
    text_parts: list[str] = []
    segments: list[dict[str, object]] = []
    characters: list[dict[str, object]] = []
    cursor = 0
    for line_index, line in enumerate(lines):
        if line_index:
            text_parts.append("\n")
            characters.append(
                _source_character(
                    text="\n",
                    bbox=None,
                    source_start=cursor,
                    mapping_state=PdfCharacterMappingState.SYNTHETIC_SPACE,
                    line_index=line_index - 1,
                    span_index=None,
                    group_id=f"line-{line.line_index}-separator-before",
                    line_direction=line.line_direction,
                    writing_mode=line.writing_mode,
                    raw_line_index=line.line_index,
                    span_order=None,
                )
            )
            cursor += 1
        line_text = line.text
        text_parts.append(line_text)
        line_segments, line_characters, cursor = _line_source_metadata(
            line.spans,
            start=cursor,
            line_index=line_index,
        )
        segments.extend(line_segments)
        characters.extend(line_characters)
    return "".join(text_parts), segments, characters


def _line_source_metadata(
    spans: tuple[PdfTextSpan, ...],
    *,
    start: int,
    line_index: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]], int]:
    cursor = start
    segments: list[dict[str, object]] = []
    characters: list[dict[str, object]] = []
    for span in spans:
        end = cursor + len(span.text)
        segments.append(
            {
                "start": cursor,
                "end": end,
                "text": span.text,
                "bbox": list(span.bbox),
            }
        )
        characters.extend(
            _source_character(
                text=character.text,
                bbox=character.bbox,
                source_start=cursor + character.source_start,
                mapping_state=character.mapping_state,
                line_index=line_index,
                span_index=span.span_index,
                group_id=character.group_id,
                line_direction=span.line_direction,
                writing_mode=span.writing_mode,
                raw_line_index=span.line_index,
                span_order=span.span_order,
            )
            for character in span.characters
        )
        cursor = end
    return segments, characters, cursor


def _line_segments_from_text(
    text: str,
    bbox: tuple[float, float, float, float],
) -> list[dict[str, object]]:
    return [{"start": 0, "end": len(text), "text": text, "bbox": list(bbox)}]


def _table_cell_source_characters(
    cell: PdfTableCell,
) -> list[dict[str, object]]:
    characters: list[dict[str, object]] = []
    for character in cell.characters:
        characters.append(
            _source_character(
                text=character.text,
                bbox=character.bbox,
                source_start=character.source_start,
                mapping_state=character.mapping_state,
                line_index=character.raw_line_index,
                span_index=None,
                group_id=character.group_id,
                line_direction=character.line_direction,
                writing_mode=character.writing_mode,
                raw_line_index=character.raw_line_index,
                span_order=character.span_order,
            )
        )
    return characters


def _source_character(
    *,
    text: str,
    bbox: tuple[float, float, float, float] | None,
    source_start: int,
    mapping_state: PdfCharacterMappingState,
    line_index: int,
    span_index: int | None,
    group_id: str | None,
    line_direction: tuple[float, float],
    writing_mode: PdfWritingMode,
    raw_line_index: int,
    span_order: int | None,
) -> dict[str, object]:
    return {
        "text": text,
        "bbox": list(bbox) if bbox is not None else None,
        "source_start": source_start,
        "source_end": source_start + len(text),
        "mapping_state": mapping_state.value,
        "line_index": line_index,
        "span_index": span_index,
        "group_id": group_id,
        "line_direction": list(line_direction),
        "writing_mode": writing_mode.value,
        "raw_line_index": raw_line_index,
        "span_order": span_order,
    }


def _font_style(span: PdfTextSpan) -> dict[str, object]:
    return {
        "name": span.font_name,
        "size": span.font_size,
        "flags": span.font_flags,
        "color": span.color,
    }


def _ocr_requirement(pages: tuple[PdfPageMetadata, ...]) -> OcrRequirement | None:
    required_pages = tuple(page.page for page in pages if page.ocr_required)
    if not required_pages:
        return None
    has_native_text = any(page.text_length > 0 for page in pages)
    return OcrRequirement(
        mode="partial" if has_native_text else "required",
        pages=required_pages,
    )


def _warning(page: int, stage: Literal["table", "image"]) -> PdfExtractionWarning:
    if stage == "table":
        return PdfExtractionWarning(
            page=page,
            stage="table",
            code="pdf_table_extraction_failed",
            message="PyMuPDF table extraction failed.",
        )
    return PdfExtractionWarning(
        page=page,
        stage="image",
        code="pdf_image_extraction_failed",
        message="PyMuPDF image extraction failed.",
    )


def _ocr_warning(page: int) -> PdfExtractionWarning:
    return PdfExtractionWarning(
        page=page,
        stage="ocr",
        code="pdf_ocr_no_text",
        message="OCR returned no usable text for the required PDF page.",
    )


def _normalized_bbox(
    rectangle: Any,
    geometry: _PageGeometry,
) -> tuple[float, float, float, float] | None:
    normalized = _bbox(_PYMUPDF.Rect(rectangle) * geometry.rotation_matrix)
    x0 = max(normalized[0], geometry.page_bbox[0])
    y0 = max(normalized[1], geometry.page_bbox[1])
    x1 = min(normalized[2], geometry.page_bbox[2])
    y1 = min(normalized[3], geometry.page_bbox[3])
    return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None


def _bbox(rectangle: Any) -> tuple[float, float, float, float]:
    return (
        float(rectangle.x0),
        float(rectangle.y0),
        float(rectangle.x1),
        float(rectangle.y1),
    )


def _has_area(bbox: tuple[float, float, float, float]) -> bool:
    return bbox[2] > bbox[0] and bbox[3] > bbox[1]


def _combined_bbox(
    bboxes: Any,
) -> tuple[float, float, float, float]:
    values = tuple(bboxes)
    return (
        min(bbox[0] for bbox in values),
        min(bbox[1] for bbox in values),
        max(bbox[2] for bbox in values),
        max(bbox[3] for bbox in values),
    )


def _intersects(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    return (
        first[0] < second[2]
        and first[2] > second[0]
        and first[1] < second[3]
        and first[3] > second[1]
    )


def _normalize_block_text(text: str) -> str:
    return "\n".join(
        " ".join(line.split())
        for line in text.replace("\r", "").splitlines()
        if line.split()
    )


def _comparison_text(text: str) -> str:
    return "".join(text.split())


def _as_any(value: object) -> Any:
    return value


def _kind_order(kind: Literal["paragraph", "heading", "table_cell", "image"]) -> int:
    return {"heading": 0, "paragraph": 1, "table_cell": 2, "image": 3}[kind]
