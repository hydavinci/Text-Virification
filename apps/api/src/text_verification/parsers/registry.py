from __future__ import annotations

from collections.abc import Iterable

from text_verification.domain.documents import FileType
from text_verification.domain.ports import Parser
from text_verification.registry_errors import DuplicateCapabilityError, MissingCapabilityError


class ParserRegistry:
    def __init__(self, parsers: Iterable[Parser] = ()) -> None:
        self._parsers: dict[FileType, Parser] = {}
        for parser in parsers:
            self.register(parser)

    def register(self, parser: Parser) -> None:
        file_type = parser.supported_type
        if file_type in self._parsers:
            raise DuplicateCapabilityError("parser", file_type.value)
        self._parsers[file_type] = parser

    def get(self, file_type: FileType) -> Parser:
        try:
            return self._parsers[file_type]
        except KeyError as error:
            raise MissingCapabilityError("parser", file_type.value) from error
