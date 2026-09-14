import base64
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import fitz
import pytest
from docx import Document

from text_verification.application import original_preview


def sample_pdf(*, rotated: bool = False) -> bytes:
    with fitz.open() as pdf:
        for word in ("First account", "Second account"):
            page = pdf.new_page(width=300, height=400)
            page.insert_text((20, 25), "Repeated header")
            page.insert_text((30, 100), word)
            if rotated:
                page.set_rotation(90)
        return pdf.tobytes()


def test_layout_maps_repeated_words_to_their_actual_pages() -> None:
    from text_verification.application.review_layout import render_review_document

    text = "First account\nSecond account"
    layout = render_review_document(sample_pdf(), "pdf", text, text)
    assert len(layout.pages) == 2
    assert layout.revision_applied
    assert layout.pages[0].image.startswith("data:image/svg+xml;base64,")
    for page, word in zip(layout.pages, ("First account", "Second account"), strict=True):
        start = text.index(word)
        assert {g.start for g in page.glyphs} == {
            i for i in range(start, start + len(word)) if not text[i].isspace()
        }
        assert all(0 <= g.x < g.x + g.width <= page.width for g in page.glyphs)
        assert all(0 <= g.y < g.y + g.height <= page.height for g in page.glyphs)


def test_page_text_stays_vector_instead_of_a_low_resolution_page_bitmap() -> None:
    from text_verification.application.review_layout import render_review_document

    text = "First account\nSecond account"
    layout = render_review_document(sample_pdf(), "pdf", text, text)
    for page in layout.pages:
        assert page.image.startswith("data:image/svg+xml;base64,")
        svg = ElementTree.fromstring(base64.b64decode(page.image.split(",", 1)[1]))
        assert svg.tag == "{http://www.w3.org/2000/svg}svg"
        assert len(svg.findall(".//{http://www.w3.org/2000/svg}path")) >= 10
        assert svg.findall(".//{http://www.w3.org/2000/svg}use")
        assert not svg.findall(".//{http://www.w3.org/2000/svg}image")
        assert not svg.findall(".//{http://www.w3.org/2000/svg}text")


def test_rotated_page_coordinates_follow_the_rendered_page() -> None:
    from text_verification.application.review_layout import render_review_document

    layout = render_review_document(
        sample_pdf(rotated=True), "pdf", "First account", "First account",
    )
    page = layout.pages[0]
    assert page.width == 400
    assert page.height == 300
    assert page.glyphs[0].x > 250
    svg = ElementTree.fromstring(base64.b64decode(page.image.split(",", 1)[1]))
    assert list(map(float, svg.attrib["viewBox"].split())) == [0, 0, page.width, page.height]


def test_word_preview_applies_revisions_without_touching_the_source(tmp_path: Path) -> None:
    from text_verification.application.review_layout import render_review_document

    document = Document()
    document.sections[0].header.paragraphs[0].text = "Header preserved"
    document.add_paragraph("First account")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "Second account"
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
    image.clear_with(125)
    document.add_picture(BytesIO(image.tobytes("png")))
    path = tmp_path / "original.docx"
    document.save(path)
    source = path.read_bytes()
    text = "First account\nSecond account"

    def convert(content: bytes, file_type: str, target_type: str) -> bytes:
        assert (file_type, target_type) == ("docx", "pdf")
        revised = Document(BytesIO(content))
        assert revised.paragraphs[0].text == "First corrected"
        assert len(revised.inline_shapes) == 1
        assert revised.tables[0].cell(0, 0).text == "Second account"
        assert revised.sections[0].header.paragraphs[0].text == "Header preserved"
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((30, 60), "First corrected\nSecond account")
            return pdf.tobytes()

    layout = render_review_document(
        source, "docx", text, text.replace("First account", "First corrected"), convert=convert,
    )
    assert layout.revision_applied
    assert "corrected" in layout.pages[0].text
    assert path.read_bytes() == source


def test_image_revision_is_explicitly_an_annotation_not_replaced_pixels() -> None:
    from text_verification.application.review_layout import render_review_document

    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    image.clear_with(255)
    layout = render_review_document(image.tobytes("png"), "png", "wrong", "right")
    assert not layout.revision_applied
    assert layout.notice
    assert len(layout.pages) == 1


def test_mapping_does_not_guess_coordinates_for_unrelated_text() -> None:
    from text_verification.application.review_layout import render_review_document

    layout = render_review_document(sample_pdf(), "pdf", "unrelated", "unrelated")
    assert all(not page.glyphs for page in layout.pages)
    assert layout.notice


def test_mapping_does_not_choose_between_identical_header_and_body() -> None:
    from text_verification.application.review_layout import render_review_document

    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((20, 25), "Account")
        page.insert_text((20, 100), "Account")
        content = pdf.tobytes()
    layout = render_review_document(content, "pdf", "Account", "Account")
    assert not layout.pages[0].glyphs
    assert layout.notice


def test_heading_repeated_inside_body_is_not_mistaken_for_an_extra_header() -> None:
    from text_verification.application.review_layout import render_review_document

    heading = "Project delivery report"
    text = f"{heading}\nThe {heading} is ready for approval."
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((30, 100), text)
        content = pdf.tobytes()

    layout = render_review_document(content, "pdf", text, text)
    assert {glyph.start for page in layout.pages for glyph in page.glyphs} == {
        index for index, character in enumerate(text) if not character.isspace()
    }
    assert layout.notice is None


def test_extra_header_remains_ambiguous_when_heading_also_occurs_inside_body() -> None:
    from text_verification.application.review_layout import render_review_document

    heading = "Project delivery report"
    text = f"{heading}\nThe {heading} is ready for approval."
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((30, 25), heading)
        page.insert_text((30, 100), text)
        content = pdf.tobytes()

    layout = render_review_document(content, "pdf", text, text)
    assert not any(glyph.start < len(heading) for page in layout.pages for glyph in page.glyphs)
    assert any(glyph.start >= len(heading) for page in layout.pages for glyph in page.glyphs)
    assert layout.notice


def test_repeated_header_cannot_complete_a_false_body_match_across_pages() -> None:
    from text_verification.application.review_layout import render_review_document

    with fitz.open() as pdf:
        for body in ("Account summary", "Second account"):
            page = pdf.new_page()
            page.insert_text((20, 25), "Account summary")
            page.insert_text((20, 100), body)
        content = pdf.tobytes()
    text = "Account summary\nSecond account"
    layout = render_review_document(content, "pdf", text, text)
    assert not any(g.start < text.index("Second") for g in layout.pages[1].glyphs)
    assert layout.notice


def test_mapping_work_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from text_verification.application import review_layout

    monkeypatch.setattr(review_layout, "MAX_MAPPING_WORK", 0)
    text = "First account\nSecond account"
    layout = review_layout.render_review_document(sample_pdf(), "pdf", text, text)
    assert all(not page.glyphs for page in layout.pages)
    assert layout.notice


@pytest.mark.parametrize("modified", [False, True])
def test_invalid_preview_is_reported_without_a_text_fallback(modified: bool) -> None:
    from text_verification.application.review_layout import render_review_document

    with pytest.raises(original_preview.OriginalPreviewError):
        render_review_document(b"broken", "pdf", "", "revision" if modified else "")
