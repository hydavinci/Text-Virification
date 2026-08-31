from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest

from text_verification.checkers.compatibility_checker import CompatibilityChecker
from text_verification.checkers.registry import CheckerRegistry
from text_verification.compatibility.analyzer import Issue as LegacyIssue
from text_verification.compatibility.exporters import ExportedDocument, ExportError
from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.ports import CheckContext, CheckResult
from text_verification.domain.verification import GlossaryTerm, Scenario, VerificationOptions
from text_verification.exporters.compatibility_exporter import CompatibilityExporter
from text_verification.exporters.registry import ExporterRegistry
from text_verification.parsers import compatibility_parser as compatibility_parser_module
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
    dictionary_versions: dict[str, str] = field(default_factory=dict)
    version: str = "1"
    supported_languages: set[str] = field(default_factory=lambda: {"zh"})

    def check(self, document: DocumentModel, context: CheckContext) -> CheckResult:
        del document, context
        return CheckResult(
            issues=self.issues,
            dictionary_versions=self.dictionary_versions,
        )


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

    result = registry.run(
        _document(text="帐号测试"),
        CheckContext.from_options(VerificationOptions()),
    )

    assert [item.layer for item in result.issues] == ["character", "character", "sentence"]
    assert [item.rule_id for item in result.issues] == [
        "character-first",
        "character-second",
        "sentence-checker",
    ]


def test_checker_registry_collects_immutable_dictionary_versions() -> None:
    registry = CheckerRegistry(
        [
            FakeChecker(
                name="character-checker",
                layer="character",
                issues=(_issue(layer="character", rule_id="character"),),
                dictionary_versions={"character_dict": "v1"},
            ),
            FakeChecker(
                name="security-checker",
                layer="security",
                issues=(_issue(layer="security", rule_id="security"),),
                dictionary_versions={"security_dict": "v2"},
            ),
        ]
    )

    result = registry.run(_document(), CheckContext.from_options(VerificationOptions()))

    assert dict(result.dictionary_versions) == {
        "character_dict": "v1",
        "security_dict": "v2",
    }
    with pytest.raises(TypeError):
        result.dictionary_versions["new_dict"] = "v3"  # type: ignore[index]


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


def test_compatibility_parser_normalizes_expected_legacy_parse_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_path = tmp_path / "sample.txt"
    source_path.write_text("content", encoding="utf-8")

    monkeypatch.setattr(
        compatibility_parser_module,
        "source_version_for_file",
        lambda path: f"sha256:{path.name}",
    )

    def fail_parse(*args: object) -> tuple[str, str, list[tuple[int, int, str]]]:
        del args
        raise ValueError("expected legacy parse failure")

    monkeypatch.setattr(compatibility_parser_module, "parse_file", fail_parse)

    with pytest.raises(compatibility_parser_module.ParserError) as raised:
        CompatibilityParser(FileType.TXT).parse(source_path)

    assert isinstance(raised.value.__cause__, ValueError)


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

    result = checker.check(document, context)

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
    assert len(result.issues) == 1
    assert result.issues[0].document_id == document.document_id
    assert result.issues[0].verification_run_id == context.verification_run_id
    assert dict(result.dictionary_versions) == {"sensitive_rules": "sha256:rules"}


def test_compatibility_exporter_exposes_registered_file_type() -> None:
    exporter = CompatibilityExporter(
        FileType.PDF,
        source_path_resolver=StaticSourcePathResolver(Path("source.pdf")),
    )

    assert exporter.file_type is FileType.PDF


def test_compatibility_checker_does_not_leak_dictionary_versions_between_runs() -> None:
    analyzer = SequentialAnalyzer(
        runs=[
            AnalyzerRun(
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
                dictionary_versions={"first_dict": "v1"},
            ),
            AnalyzerRun(
                issues=[
                    LegacyIssue(
                        type="typo",
                        severity="warning",
                        original="测试",
                        suggestion="校验",
                        position=2,
                        end_position=4,
                        context="帐号测试",
                        description="疑似错别字",
                        rule_id="cn_typo_2",
                        alternatives=["校验"],
                        layer="character",
                    )
                ],
                dictionary_versions={"second_dict": "v2"},
            ),
        ]
    )
    checker = CompatibilityChecker(analyzer=analyzer)

    first = checker.check(
        _document(text="帐号测试"),
        CheckContext.from_options(VerificationOptions()),
    )
    second = checker.check(
        _document(text="帐号测试"),
        CheckContext.from_options(VerificationOptions()),
    )

    assert dict(first.dictionary_versions) == {"first_dict": "v1"}
    assert dict(second.dictionary_versions) == {"second_dict": "v2"}
    assert dict(first.dictionary_versions) == {"first_dict": "v1"}


def test_default_compatibility_checker_isolates_concurrent_analyzer_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = Barrier(2)
    analyzers: list[InterleavingAnalyzer] = []

    def build_analyzer(*, dictionary_loader: object) -> InterleavingAnalyzer:
        del dictionary_loader
        analyzer = InterleavingAnalyzer(barrier)
        analyzers.append(analyzer)
        return analyzer

    monkeypatch.setattr(
        "text_verification.checkers.compatibility_checker.TextAnalyzer",
        build_analyzer,
    )
    checker = CompatibilityChecker()

    def run(text: str) -> CheckResult:
        return checker.check(
            _document(text=text),
            CheckContext.from_options(VerificationOptions()),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(run, "first")
        second_future = executor.submit(run, "second")
        first = first_future.result(timeout=2)
        second = second_future.result(timeout=2)

    assert len(analyzers) == 2
    assert dict(first.dictionary_versions) == {"first_dict": "version:first"}
    assert dict(second.dictionary_versions) == {"second_dict": "version:second"}


def test_compatibility_exporter_uses_injected_source_path_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved_source = tmp_path / "stored" / "source.pdf"
    target = tmp_path / "exported.pdf"
    calls: list[dict[str, object]] = []

    def fake_export_original(
        source_path: Path,
        extension: str,
        replacements: list[tuple[str, str, int | None, int | None]],
        track_changes: bool,
        *,
        original_text: str | None = None,
        modified_text: str | None = None,
    ) -> ExportedDocument:
        calls.append(
            {
                "source_path": source_path,
                "extension": extension,
                "replacements": replacements,
                "track_changes": track_changes,
                "original_text": original_text,
                "modified_text": modified_text,
            }
        )
        return ExportedDocument(
            content=b"%PDF-1.7",
            extension="pdf",
            media_type="application/pdf",
        )

    monkeypatch.setattr(
        "text_verification.exporters.compatibility_exporter.export_original",
        fake_export_original,
    )

    exporter = CompatibilityExporter(
        FileType.PDF,
        source_path_resolver=StaticSourcePathResolver(resolved_source),
    )
    output_path = exporter.export(
        _document(text="帐号测试", source_name="用户显示名称.pdf"),
        [_issue()],
        target,
    )

    assert output_path == target
    assert target.read_bytes() == b"%PDF-1.7"
    assert calls[0]["source_path"] == resolved_source


def test_compatibility_exporter_rejects_nullable_suggestion(
    tmp_path: Path,
) -> None:
    exporter = CompatibilityExporter(
        FileType.TXT,
        source_path_resolver=StaticSourcePathResolver(tmp_path / "source.txt"),
    )

    with pytest.raises(ExportError, match="non-null suggestion"):
        exporter.export(
            _document(text="帐号测试"),
            [_issue(suggestion=None, auto_fixable=False)],
            tmp_path / "exported.txt",
        )


def test_compatibility_exporter_rejects_non_auto_fixable_issue(
    tmp_path: Path,
) -> None:
    exporter = CompatibilityExporter(
        FileType.TXT,
        source_path_resolver=StaticSourcePathResolver(tmp_path / "source.txt"),
    )

    with pytest.raises(ExportError, match="auto-fixable"):
        exporter.export(
            _document(text="帐号测试"),
            [_issue(auto_fixable=False)],
            tmp_path / "exported.txt",
        )


def test_compatibility_exporter_allows_explicit_deletion_suggestion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_export_original(
        source_path: Path,
        extension: str,
        replacements: list[tuple[str, str, int | None, int | None]],
        track_changes: bool,
        *,
        original_text: str | None = None,
        modified_text: str | None = None,
    ) -> ExportedDocument:
        del source_path, extension, track_changes, original_text, modified_text
        assert replacements == [("帐号", "", 0, 2)]
        return ExportedDocument(
            content=b"",
            extension="txt",
            media_type="text/plain",
        )

    monkeypatch.setattr(
        "text_verification.exporters.compatibility_exporter.export_original",
        fake_export_original,
    )

    exporter = CompatibilityExporter(
        FileType.TXT,
        source_path_resolver=StaticSourcePathResolver(tmp_path / "source.txt"),
    )

    exporter.export(
        _document(text="帐号测试"),
        [_issue(suggestion="", auto_fixable=True)],
        tmp_path / "exported.txt",
    )


@dataclass
class RecordingAnalyzer:
    issues: list[LegacyIssue]
    dictionary_versions: dict[str, str]
    calls: list[dict[str, object]] = field(default_factory=list)

    def analyze(self, text: str, **kwargs: object) -> list[LegacyIssue]:
        self.calls.append({"text": text, **kwargs})
        return list(self.issues)


@dataclass(frozen=True)
class AnalyzerRun:
    issues: list[LegacyIssue]
    dictionary_versions: dict[str, str]


@dataclass
class SequentialAnalyzer:
    runs: list[AnalyzerRun]
    dictionary_versions: dict[str, str] = field(default_factory=dict)
    calls: list[dict[str, object]] = field(default_factory=list)

    def analyze(self, text: str, **kwargs: object) -> list[LegacyIssue]:
        self.calls.append({"text": text, **kwargs})
        current_run = self.runs.pop(0)
        self.dictionary_versions = dict(current_run.dictionary_versions)
        return list(current_run.issues)


@dataclass
class InterleavingAnalyzer:
    barrier: Barrier
    dictionary_versions: dict[str, str] = field(default_factory=dict)

    def analyze(self, text: str, **kwargs: object) -> list[LegacyIssue]:
        del kwargs
        self.dictionary_versions = {f"{text}_dict": f"version:{text}"}
        self.barrier.wait(timeout=2)
        return []


@dataclass(frozen=True)
class StaticSourcePathResolver:
    path: Path

    def resolve(self, document: DocumentModel, *, source_path: Path | None = None) -> Path:
        del document
        return source_path or self.path


def _document(text: str = "帐号", *, source_name: str = "sample.txt") -> DocumentModel:
    return DocumentModel(
        document_id=uuid4(),
        source_version="sha256:sample",
        file_type=FileType.TXT,
        source_name=source_name,
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
    layer: str = "character",
    start: int = 0,
    end: int = 2,
    original: str = "帐号",
    rule_id: str | None = None,
    suggestion: str | None = "账号",
    auto_fixable: bool = True,
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
        suggestion=suggestion,
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
        auto_fixable=auto_fixable,
        context="帐号测试",
    )
