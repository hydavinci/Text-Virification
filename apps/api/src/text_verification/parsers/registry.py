from collections.abc import Iterable

from text_verification.domain.documents import FileType, ParseError
from text_verification.domain.ports import Parser


class ParserRegistry:
    def __init__(self, parsers: Iterable[Parser]) -> None:
        self._parsers = {parser.supported_type: parser for parser in parsers}

    def get(self, file_type: FileType) -> Parser:
        try:
            return self._parsers[file_type]
        except KeyError as error:
            raise ParseError("unsupported_parser", "暂不支持解析该文件类型。") from error
