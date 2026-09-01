from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from text_verification.document_processing.pdf_models import (
    PdfCharacterMappingState,
    PdfDocumentMetadata,
    PdfPageKind,
    PdfPageMetadata,
    PdfTextCharacter,
    PdfTextSpan,
)
from text_verification.domain.documents import DocumentMetadata


def _page_metadata(**updates: object) -> PdfPageMetadata:
    values: dict[str, object] = {
        "page": 1,
        "kind": PdfPageKind.TEXT,
        "page_bbox": (0.0, 0.0, 100.0, 200.0),
        "text_length": 3,
        "text_density": 0.00015,
        "image_coverage": 0.0,
        "ocr_required": False,
    }
    values.update(updates)
    return PdfPageMetadata(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("page", True),
        ("text_length", True),
        ("text_density", math.nan),
        ("image_coverage", math.inf),
    ],
)
def test_page_metadata_rejects_non_strict_or_non_finite_scalars(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        _page_metadata(**{field: value})


def test_page_metadata_rejects_out_of_page_span_geometry() -> None:
    with pytest.raises(ValidationError, match="page bounds"):
        _page_metadata(
            spans=(
                PdfTextSpan(
                    text="outside",
                    bbox=(0.0, 0.0, 101.0, 10.0),
                    font_name="Helvetica",
                    font_size=10.0,
                    font_flags=0,
                    color=0,
                    span_index=0,
                ),
            )
        )


def test_text_character_metadata_is_immutable_json_safe_and_offset_exact() -> None:
    character = PdfTextCharacter(
        text="W",
        bbox=(1.0, 2.0, 9.0, 12.0),
        source_start=0,
        source_end=1,
        mapping_state=PdfCharacterMappingState.GLYPH,
    )
    span = PdfTextSpan(
        text="W",
        bbox=(1.0, 2.0, 9.0, 12.0),
        font_name="Helvetica",
        font_size=10.0,
        font_flags=0,
        color=0,
        span_index=0,
        characters=(character,),
    )

    with pytest.raises(ValidationError):
        character.source_start = 1

    assert span.model_dump(mode="json")["characters"] == [
        {
            "text": "W",
            "bbox": [1.0, 2.0, 9.0, 12.0],
            "source_start": 0,
            "source_end": 1,
            "mapping_state": "glyph",
        }
    ]


@pytest.mark.parametrize(
    "bbox",
    [
        (-1.0, 0.0, 100.0, 200.0),
        (0.0, 0.0, 100.0, -1.0),
        (0.0, 0.0, 0.0, 200.0),
    ],
)
def test_page_metadata_rejects_invalid_normalized_page_bbox(
    bbox: tuple[float, float, float, float],
) -> None:
    with pytest.raises(ValidationError):
        _page_metadata(page_bbox=bbox)


def test_document_metadata_is_immutable_and_serializes_deterministically() -> None:
    metadata = PdfDocumentMetadata(pages=(_page_metadata(),))
    document_metadata = DocumentMetadata(pdf=metadata)

    with pytest.raises(ValidationError):
        metadata.pages = ()
    with pytest.raises(ValidationError):
        document_metadata.pdf = None

    assert metadata.model_dump(mode="json") == {
        "pages": [
            {
                "page": 1,
                "kind": "text",
                "page_bbox": [0.0, 0.0, 100.0, 200.0],
                "text_length": 3,
                "text_density": 0.00015,
                "image_coverage": 0.0,
                "ocr_required": False,
                "spans": [],
                "tables": [],
                "images": [],
            }
        ],
        "warnings": [],
        "ocr_requirement": None,
    }
