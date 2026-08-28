from __future__ import annotations

import re
import unicodedata
from typing import TypedDict

_EN_WORD_RE = re.compile(r"[a-zA-Z]+(?:['\-][a-zA-Z]+)*")
_NUM_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)*")


class TextStatistics(TypedDict):
    char_count: int
    char_count_no_space: int
    line_count: int
    paragraph_count: int
    language: str
    primary_count: int
    primary_label: str


def _is_word_cjk_char(character: str) -> bool:
    width = unicodedata.east_asian_width(character)
    return width in {"W", "F"} or (
        width == "A" and unicodedata.category(character).startswith("P")
    )


def count_word_words(text: str) -> int:
    """Approximate the word count shown by Microsoft Word for mixed CJK text."""
    cjk_characters = sum(1 for character in text if _is_word_cjk_char(character))
    return cjk_characters + len(_EN_WORD_RE.findall(text)) + len(_NUM_TOKEN_RE.findall(text))


def text_statistics(text: str) -> TextStatistics:
    cjk_characters = sum(1 for character in text if _is_word_cjk_char(character))
    english_words = len(_EN_WORD_RE.findall(text))
    language = "zh" if cjk_characters >= english_words else "en"
    return {
        "char_count": len(text),
        "char_count_no_space": len(re.sub(r"\s", "", text)),
        "line_count": text.count("\n") + 1,
        "paragraph_count": sum(bool(paragraph.strip()) for paragraph in text.split("\n")),
        "language": language,
        "primary_count": count_word_words(text),
        "primary_label": "总字数" if language == "zh" else "总单词数",
    }
