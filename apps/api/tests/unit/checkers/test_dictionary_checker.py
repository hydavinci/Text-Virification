from pathlib import Path
from uuid import UUID

from text_verification.checkers.dictionary_checker import DictionaryChecker
from text_verification.checkers.dictionary_loader import DictionaryLoader
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.ports import CheckContext


def test_dictionary_checker_uses_loaded_terms_and_replacement_rules() -> None:
    repository_root = Path(__file__).resolve().parents[5]
    dictionaries = DictionaryLoader(repository_root / "resources" / "dictionaries").load()
    checker = DictionaryChecker()

    issues = checker.check(
        build_document("最高级方案在香港发布，仍称最高级。"),
        CheckContext((), (), shared_dictionaries=dictionaries),
    )

    assert [(issue.original, issue.suggestion, issue.start, issue.end) for issue in issues] == [
        ("最高级", None, 0, 3),
        ("香港", "中国香港", 6, 8),
        ("最高级", None, 13, 16),
    ]
    assert all(issue.source == "shared_dictionary" for issue in issues)
    assert [issue.issue_id for issue in issues] == [
        issue.issue_id
        for issue in checker.check(
            build_document("最高级方案在香港发布，仍称最高级。"),
            CheckContext((), (), shared_dictionaries=dictionaries),
        )
    ]


def build_document(text: str) -> DocumentModel:
    return DocumentModel(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        file_type=FileType.TXT,
        source_name="dictionary.txt",
        version=1,
        blocks=[
            TextBlock(
                block_id="p-000001",
                kind="paragraph",
                text=text,
                page=None,
                paragraph_index=0,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": 0},
            )
        ],
        metadata={},
    )
