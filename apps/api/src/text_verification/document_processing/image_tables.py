from __future__ import annotations

import importlib
from bisect import bisect_right
from itertools import groupby
from typing import Any

from text_verification.document_processing.errors import OcrLayoutError, OcrUnavailableError
from text_verification.document_processing.image_validation import ValidatedImage
from text_verification.document_processing.layout import (
    OcrLayoutBox,
    OcrLineGroupingBudget,
    OcrTable,
    OcrTableCell,
    group_ocr_lines,
)


def detect_grid_tables(
    image: ValidatedImage,
    boxes: tuple[OcrLayoutBox, ...],
    *,
    language: str = "zh",
    max_cells: int = 5_000,
    max_candidate_checks: int = 250_000,
) -> tuple[OcrTable, ...]:
    """Use visible grid lines when text alignment cannot reveal empty cells."""
    if not boxes:
        return ()
    try:
        np: Any = importlib.import_module("numpy")
        cv2: Any = importlib.import_module("cv2")
    except ImportError as error:
        raise OcrUnavailableError() from error
    rows = np.frombuffer(image.samples, dtype=np.uint8).reshape(image.height, image.stride)
    pixels = rows[:, : image.width * image.channels].reshape(
        image.height, image.width, image.channels
    )
    gray = (
        cv2.cvtColor(pixels[:, :, :3], cv2.COLOR_RGB2GRAY)
        if image.channels >= 3
        else pixels[:, :, 0]
    )
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 10
    )
    horizontal = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (max(image.width // 30, 10), 1)),
    )
    vertical = cv2.morphologyEx(
        binary, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(image.height // 30, 10))),
    )
    contours, _ = cv2.findContours(
        cv2.bitwise_or(horizontal, vertical), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    tables: list[OcrTable] = []
    consumed: set[int] = set()
    cell_count = 0
    candidate_checks = 0
    grouping_budget = OcrLineGroupingBudget(max_candidate_checks)
    regions = sorted(
        (cv2.boundingRect(contour) for contour in contours),
        key=lambda region: (region[1], region[0]),
    )
    for x, y, width, height in regions:
        if width < 50 or height < 30:
            continue
        xs = _line_centers(
            np.flatnonzero(np.count_nonzero(
                vertical[y:y + height, x:x + width], axis=0
            ) >= height * 0.7).tolist(), x
        )
        ys = _line_centers(
            np.flatnonzero(np.count_nonzero(
                horizontal[y:y + height, x:x + width], axis=1
            ) >= width * 0.7).tolist(), y
        )
        if len(xs) < 3 or len(ys) < 3:
            continue
        cell_count += (len(xs) - 1) * (len(ys) - 1)
        candidate_checks += len(boxes)
        if cell_count > max_cells or candidate_checks > max_candidate_checks:
            raise OcrLayoutError("OCR grid table resource limit exceeded.")
        assigned: dict[tuple[int, int], list[OcrLayoutBox]] = {}
        for box in boxes:
            if box.box_index in consumed:
                continue
            x0, y0, x1, y1 = box.bbox
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if not (xs[0] < cx < xs[-1] and ys[0] < cy < ys[-1]):
                continue
            key = (bisect_right(ys, cy) - 1, bisect_right(xs, cx) - 1)
            assigned.setdefault(key, []).append(box)
        if sum(len(cell) for cell in assigned.values()) < 2:
            continue
        table_index = len(tables)
        cells: list[tuple[OcrTableCell, ...]] = []
        for row in range(len(ys) - 1):
            row_cells: list[OcrTableCell] = []
            for column in range(len(xs) - 1):
                lines = group_ocr_lines(
                    tuple(assigned.get((row, column), [])),
                    language=language,
                    max_candidate_checks=max_candidate_checks,
                    budget=grouping_budget,
                )
                members = tuple(box for line in lines for box in line.boxes)
                row_cells.append(OcrTableCell(
                    page=boxes[0].page,
                    text=" ".join(line.text for line in lines),
                    bbox=(xs[column], ys[row], xs[column + 1], ys[row + 1]),
                    confidence=_confidence(members),
                    table_index=table_index, row_index=row, cell_index=column,
                    boxes=members,
                ))
                consumed.update(box.box_index for box in members)
            cells.append(tuple(row_cells))
        all_members = tuple(box for members in assigned.values() for box in members)
        tables.append(OcrTable(
            page=boxes[0].page,
            table_index=table_index,
            bbox=(xs[0], ys[0], xs[-1], ys[-1]),
            confidence=_confidence(all_members),
            row_count=len(ys) - 1, column_count=len(xs) - 1,
            rows=tuple(cells),
        ))
    return tuple(tables)


def _line_centers(indices: list[int], offset: int) -> list[float]:
    centers: list[float] = []
    for _, group in groupby(enumerate(indices), key=lambda item: item[1] - item[0]):
        run = [value for _, value in group]
        centers.append(offset + (run[0] + run[-1]) / 2)
    return centers


def _confidence(boxes: tuple[OcrLayoutBox, ...]) -> float:
    return sum(box.confidence for box in boxes) / len(boxes) if boxes else 0.0
