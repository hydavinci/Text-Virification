from text_verification.parsers.docx import DocxParser
from text_verification.parsers.pdf import PdfParser
from text_verification.parsers.registry import ParserRegistry
from text_verification.parsers.txt import TxtParser

__all__ = ["DocxParser", "ParserRegistry", "PdfParser", "TxtParser"]
