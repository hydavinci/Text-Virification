from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest

from text_verification.checkers.compatibility_checker import CompatibilityChecker
from text_verification.checkers.registry import CheckerRegistry
from text_verification.compatibility.analyzer import Issue as LegacyIssue
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.ports import CheckContext
from text_verification.domain.verification import GlossaryTerm, Scenario, VerificationOptions
from text_verification.exporters.compatibility_exporter import CompatibilityExporter
from text_verification.exporters.registry import ExporterRegistry
from text_verification.parsers.compatibility_parser import CompatibilityParser
from text_verification.parsers.registry import ParserRegistry
from text_verification.registry_errors import DuplicateCapabilityError, MissingCapabilityError


@dataclass(frozen=True)
class FakeParser:
    supported_type: FileType

    def parse(self, source_path: Path) -> DocumentModel:
        del source_path
        return _document()


@dataclass(frozen=True)
class FakeExporter:
    file_type: FileType

    def export(self, document: DocumentModel, issues: list[Issue], target: Path) -> Path:
        del document, issues
        return target


@dataclass(frozen=True)
class FakeChecker:
    name: str
    layer: str
    issues: tuple[Issue, ...]
    version: str = "1"
    supported_languages: set[str] = field(default_factory=lambda: {"zh"})

    def check(self, document: DocumentModel, context: CheckContext) -> list[Issue]:
        del document, context
        return list(self.issues)


def test_parser_registry_returns_registered_parser_for_file_type() -> None:
    parser = FakeParser(FileType.TXT)
    registry = ParserRegistry([parser])

    assert registry.get(FileType.TXT) is parser


def test_parser_registry_rejects_duplicate_file_type() -> None:
    registry = ParserRegistry()
    registry.register(FakeParser(FileType.TXT))

    with pytest.raises(DuplicateCapabilityError, match="txt"):
        registry.register(FakeParser(FileType.TXT))


def test_parser_registry_rejects_missing_file_type() -> None:
    registry = ParserRegistry()

    with pytest.raises(MissingCapabilityError, match="pdf"):
        registry.get(FileType.PDF)


def test_exporter_registry_returns_registered_exporter_for_file_type() -> None:
    exporter = FakeExporter(FileType.TXT)
    registry = ExporterRegistry([exporter])

    assert registry.get(FileType.TXT) is exporter


def test_exporter_registry_rejects_duplicate_file_type() -> None:
    registry = ExporterRegistry()
    registry.register(FakeExporter(FileType.TXT))

    with pytest.raises(DuplicateCapabilityError, match="txt"):
        registry.register(FakeExporter(FileType.TXT))


def test_exporter_registry_rejects_missing_file_type() -> None:
    registry = ExporterRegistry()

    with pytest.raises(MissingCapabilityError, match="pdf"):
        registry.get(FileType.PDF)


def test_checker_registry_rejects_duplicate_name() -> None:
    checker = FakeChecker(
        name="character-checker",
        layer="character",
        issues=(_issue(layer="character"),),
    )
    registry = CheckerRegistry([checker])

    with pytest.raises(DuplicateCapabilityError, match="character-checker"):
        registry.register(
            FakeChecker(
                name="character-checker",
                layer="character",
                issues=(_issue(layer="character"),),
            )
        )


def test_checker_registry_rejects_missing_checkers() -> None:
    registry = CheckerRegistry()

    with pytest.raises(MissingCapabilityError, match="checker"):
        registry.run(_document(), CheckContext.from_options(VerificationOptions()))


def test_checker_registry_runs_in_layer_then_registration_order() -> None:
    registry = CheckerRegistry(
        [
            FakeChecker(
                name="sentence-checker",
                layer="sentence",
                issues=(_issue(layer="sentence", start=2, end=4, rule_id="sentence-checker"),),
            ),
            FakeChecker(
                name="character-first",
                layer="character",
                issues=(
                    _issue(
                        layer="character",
                        start=0,
                        end=1,
                        original="帐",
                        rule_id="character-first",
                    ),
                ),
            ),
            FakeChecker(
                name="character-second",
                layer="character",
                issues=(
                    _issue(
                        layer="character",
                        start=1,
                        end=2,
                        original="号",
                        rule_id="character-second",
                    ),
                ),
            ),
        ]
    )

    issues = registry.run(
        _document(text="帐号测试"),
        CheckContext.from_options(VerificationOptions()),
    )

    assert [item.layer for item in issues] == ["character", "character", "sentence"]
    assert [item.rule_id for item in issues] == [
        "character-first",
        "character-second",
        "sentence-checker",
    ]


def test_check_context_from_options_normalizes_checker_inputs() -> None:
    options = VerificationOptions(
        scenario=Scenario.LEGAL,
        enable_security=False,
        enable_sensitive=False,
        enable_ad_extreme=True,
        custom_glossary=(
            GlossaryTerm(original="帐号", standard="账号"),
            GlossaryTerm(original="术语", standard="术语"),
        ),
        banned_words=(" 违禁词 ", "", "违禁词"),
    )

    context = CheckContext.from_options(options)

    assert context.scenario is Scenario.LEGAL
    assert context.enable_security is False
    assert context.enable_sensitive is False
    assert context.enable_ad_extreme is True
    assert context.custom_glossary == ({"original": "帐号", "standard": "账号"},)
    assert context.banned_words == ("违禁词",)


def test_compatibility_parser_uses_existing_page_map_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "sample.docx"
    source_path.write_bytes(b"docx")

    def fake_parse_file(file_path: str, file_extension: str | None, work_directory: str | None):
        assert file_path == str(source_path)
        assert file_extension == FileType.DOCX.value
        assert work_directory == str(source_path.parent)
        return "Alpha\nBeta", "docx", [(0, 5, "第1段"), (6, 10, "第2段")]

    monkeypatch.setattr(
        "text_verification.parsers.compatibility_parser.parse_file",
        fake_parse_file,
    )
    monkeypatch.setattr(
        "text_verification.parsers.compatibility_parser.source_version_for_file",
        lambda path: f"sha256:{path.name}",
    )

    parser = CompatibilityParser(FileType.DOCX)
    document = parser.parse(source_path)

    assert document.file_type is FileType.DOCX
    assert document.parser_name == "compatibility-docx"
    assert [block.block_id for block in document.blocks] == ["paragraph-0", "paragraph-1"]
    assert [block.text for block in document.blocks] == ["Alpha", "Beta"]


def test_compatibility_checker_uses_text_analyzer_and_domain_issue_adapter() -> None:
    analyzer = RecordingAnalyzer(
        issues=[
            LegacyIssue(
                type="typo",
                severity="warning",
                original="帐号",
                suggestion="账号",
                position=0,
                end_position=2,
                context="帐号测试",
                description="疑似错别字",
                rule_id="cn_typo",
                alternatives=["账号"],
                layer="character",
            )
        ],
        dictionary_versions={"sensitive_rules": "sha256:rules"},
    )
    checker = CompatibilityChecker(analyzer=analyzer)
    document = _document(text="帐号测试")
    context = CheckContext.from_options(
        VerificationOptions(
            scenario=Scenario.BUSINESS,
            enable_security=False,
            enable_sensitive=False,
            banned_words=("禁词",),
        )
    )

    issues = checker.check(document, context)

    assert analyzer.calls == [
        {
            "text": document.text,
            "scenario": "business",
            "custom_glossary": [],
            "banned_words": ["禁词"],
            "enable_security": False,
            "enable_sensitive": False,
            "enable_ad_extreme": False,
        }
    ]
    assert len(issues) == 1
    assert issues[0].document_id == document.document_id
    assert issues[0].verification_run_id == context.verification_run_id
    assert checker.dictionary_versions == {"sensitive_rules": "sha256:rules"}


def test_compatibility_exporter_exposes_registered_file_type() -> None:
    assert CompatibilityExporter(FileType.PDF).file_type is FileType.PDF


@dataclass
class RecordingAnalyzer:
    issues: list[LegacyIssue]
    dictionary_versions: dict[str, str]
    calls: list[dict[str, object]] = field(default_factory=list)

    def analyze(self, text: str, **kwargs: object) -> list[LegacyIssue]:
        self.calls.append({"text": text, **kwargs})
        return list(self.issues)


def _document(text: str = "帐号") -> DocumentModel:
    return DocumentModel(
        document_id=uuid4(),
        source_version="sha256:sample",
        file_type=FileType.TXT,
        source_name="sample.txt",
        text=text,
        blocks=[
            TextBlock(
                block_id="paragraph-0",
                kind="paragraph",
                text=text,
                global_start=0,
                global_end=len(text),
                block_start=0,
                block_end=len(text),
                page=None,
                paragraph_index=0,
                table_index=None,
                row_index=None,
                cell_index=None,
                bbox=None,
                parent_id=None,
                style={},
                source_locator={"paragraph_index": 0},
            )
        ],
        parser_name="compatibility-flat-text",
        parser_version="1",
    )


def _issue(
    *,
    layer: str,
    start: int = 0,
    end: int = 2,
    original: str = "帐号",
    rule_id: str | None = None,
) -> Issue:
    resolved_rule_id = rule_id or f"{layer}-rule"
    return Issue(
        issue_id=uuid4(),
        document_id=_document(text="帐号测试").document_id,
        verification_run_id=uuid4(),
        block_id="paragraph-0",
        page=None,
        start=start,
        end=end,
        block_start=start,
        block_end=end,
        original=original,
        suggestion="账号",
        alternatives=[],
        type="typo",
        severity=IssueSeverity.WARNING,
        layer=layer,
        message=f"{layer} issue",
        description=f"{layer} issue",
        rule_id=resolved_rule_id,
        rule_version="1",
        source="test",
        source_version="1",
        confidence=0.8,
        auto_fixable=True,
        context="帐号测试",
    )
