from pydantic import BaseModel, ConfigDict, Field

MAX_LAYOUT_TEXT = 200_000
MAX_LAYOUT_PAGES = 80
MAX_LAYOUT_BYTES = 25 * 1024 * 1024
MAX_RENDER_REQUEST_BYTES = 64 * 1024 * 1024


class LayoutRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_version: str = Field(min_length=1, max_length=128)
    text: str = Field(max_length=MAX_LAYOUT_TEXT)


class LayoutGlyph(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    x: float
    y: float
    width: float
    height: float


class LayoutPage(BaseModel):
    width: float
    height: float
    image: str
    text: str
    glyphs: list[LayoutGlyph] = Field(default_factory=list)


class ReviewLayout(BaseModel):
    pages: list[LayoutPage] = Field(max_length=MAX_LAYOUT_PAGES)
    revision_applied: bool
    notice: str | None = None


class LayoutRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=35 * 1024 * 1024)
    original_text: str = Field(max_length=MAX_LAYOUT_TEXT)
    text: str = Field(max_length=MAX_LAYOUT_TEXT)
