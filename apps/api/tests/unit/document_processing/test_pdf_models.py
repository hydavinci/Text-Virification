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
        group_id="line-0-span-0-glyph-0",
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
        line_direction=(1.0, 0.0),
        writing_mode=0,
        line_index=0,
        span_order=0,
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
            "group_id": "line-0-span-0-glyph-0",
        }
    ]
    assert span.model_dump(mode="json")["line_direction"] == [1.0, 0.0]
    assert span.model_dump(mode="json")["writing_mode"] == 0


def test_multi_codepoint_glyph_group_has_one_bbox_and_stable_boundaries() -> None:
    character = PdfTextCharacter(
        text="👩‍💻",
        bbox=(1.0, 2.0, 9.0, 12.0),
        source_start=0,
        source_end=3,
        mapping_state=PdfCharacterMappingState.GLYPH,
        group_id="line-2-span-4-glyph-1",
    )

    assert character.source_end - character.source_start == len(character.text)
    assert character.model_dump(mode="json") == {
        "text": "👩‍💻",
        "bbox": [1.0, 2.0, 9.0, 12.0],
        "source_start": 0,
        "source_end": 3,
        "mapping_state": "glyph",
        "group_id": "line-2-span-4-glyph-1",
    }


def test_pdf_text_metadata_accepts_legacy_json_without_group_or_writing_fields() -> None:
    character = PdfTextCharacter.model_validate(
        {
            "text": "W",
            "bbox": [1.0, 2.0, 9.0, 12.0],
            "source_start": 0,
            "source_end": 1,
            "mapping_state": "glyph",
        }
    )
    span = PdfTextSpan.model_validate(
        {
            "text": "W",
            "bbox": [1.0, 2.0, 9.0, 12.0],
            "font_name": "Helvetica",
            "font_size": 10.0,
            "font_flags": 0,
            "color": 0,
            "span_index": 0,
            "characters": [character.model_dump(mode="json", exclude_none=True)],
        }
    )

    assert character.group_id is None
    assert span.line_direction == (1.0, 0.0)
    assert span.writing_mode.value == 0
    assert span.line_index == 0
    assert span.span_order == 0


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
