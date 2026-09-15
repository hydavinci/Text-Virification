from __future__ import annotations

import re
from array import array
from dataclasses import dataclass

_TECHNICAL = re.compile(
    r"^[ \t]*```[^\n]*\n[\s\S]*?(?:^[ \t]*```[^\n]*(?:\n|$)|\Z)"
    r"|^[ \t]*~~~[^\n]*\n[\s\S]*?(?:^[ \t]*~~~[^\n]*(?:\n|$)|\Z)"
    r"|(?<!`)`+[^`\n]+`+"
    r"|(?:https?://|www\.)[^\s<>\"，。！？；「」]+"
    r"|(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
    r"|(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+",
    re.MULTILINE,
)
_TECHNICAL_LINE = re.compile(
    r"^[ \t]*(?:[A-Z]{2,}(?:/[A-Z]{2,})?[ \t]*\d+(?:[-–—]\d+)*"
    r"[ \t]*[|:][ \t]*[A-Za-z]|[A-Za-z0-9]+(?:[-_/][A-Za-z0-9]+)+[^\n]*\|)"
    r"[^\n]*",
    re.MULTILINE,
)
_FILE_EXTENSIONS = (
    r"txt|docx?|pdf|json|ya?ml|xml|csv|md|rst|ini|toml|py|js|ts|tsx|jsx|css|html?"
    r"|sql|sh|exe|dll|so|zip|tar|gz|png|jpe?g|svg|xlsx?|pptx?|log|rtf|mp[34]"
    r"|webm|mkv|pem|crt|key|env|config|lock"
)
_FILE_REFERENCE = re.compile(
    r"""(?<![\w])(?:[A-Za-z]:[\\/]|\\\\|(?:~|\.\.?)?[\\/])[^\s"'<>，。！？；]+"""
    r"|(?<![\w.-])(?:[\w.-]+[\\/])+[\w.-]+"
    r"|(?<![\w.-])\.(?:env|gitignore|dockerignore|npmrc|bashrc|zshrc)"
    r"(?:\.[\w-]+)*(?![\w-])"
    r"|(?<![\w.-])[\w.-]+\.(?:" + _FILE_EXTENSIONS + r")(?![\w])",
    re.IGNORECASE,
)
_QUOTED_FILE = re.compile(
    r"""(["'])([^"'\r\n]+\.(?:""" + _FILE_EXTENSIONS + r"))\1",
    re.IGNORECASE,
)


def term_pattern(term: str, *, ignore_case: bool = False) -> re.Pattern[str]:
    """ASCII identifiers need token boundaries even in mixed-language prose."""
    left = r"(?<![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", term) else ""
    right = r"(?![A-Za-z0-9_])" if re.search(r"[A-Za-z0-9_]$", term) else ""
    return re.compile(left + re.escape(term) + right, re.IGNORECASE if ignore_case else 0)


@dataclass
class TextContext:
    text: str
    technical: list[bool]
    _protected_count: array[int]

    @classmethod
    def build(cls, text: str) -> TextContext:
        mask = [False] * len(text)
        for pattern in (_TECHNICAL, _TECHNICAL_LINE, _FILE_REFERENCE, _QUOTED_FILE):
            for match in pattern.finditer(text):
                mask[match.start():match.end()] = [True] * (match.end() - match.start())
        counts = array("I", [0])
        total = 0
        for protected in mask:
            total += protected
            counts.append(total)
        return cls(text, mask, counts)

    def is_protected(self, start: int, end: int) -> bool:
        return self._protected_count[end] != self._protected_count[start]
