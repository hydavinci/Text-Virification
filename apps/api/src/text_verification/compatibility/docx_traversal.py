from collections.abc import Iterator

from docx.document import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph


def iter_docx_paragraphs(document: Document) -> Iterator[Paragraph]:
    """Body XML order, then unique headers/footers in section-reference order.

    Visit physical cells, not the repeated cell proxies of merged table grids.
    Only existing part references are read, so traversal never creates stories.
    """
    roots = [(document.element.body, document.part)]
    seen_parts = set()
    for section in document.sections:
        for reference in (
            *section._sectPr.headerReference_lst,
            *section._sectPr.footerReference_lst,
        ):
            part = document.part.related_parts[reference.rId]
            if part.partname not in seen_parts:
                roots.append((part.element, part))
                seen_parts.add(part.partname)
    containers = {qn("w:tbl"), qn("w:tr"), qn("w:tc")}
    for root, part in roots:
        stack = [iter(root)]
        while stack:
            element = next(stack[-1], None)
            if element is None:
                stack.pop()
            elif element.tag == qn("w:p"):
                yield Paragraph(element, part)
            elif element.tag in containers:
                stack.append(iter(element))
