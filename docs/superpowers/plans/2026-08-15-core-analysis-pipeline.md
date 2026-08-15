# Core Analysis Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse TXT, DOCX, and text-based PDF uploads, run six local checker categories, persist document blocks and issues, and expose read APIs.

**Architecture:** Parser and checker registries implement the existing domain protocols. The Celery pipeline persists normalized blocks and issues through dedicated repositories, records category failures, and finishes as `completed`, `partial`, or `failed`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, PostgreSQL 16, Celery 5, python-docx, pypdf, pytest.

**Spec:** `docs/superpowers/specs/2026-08-15-document-review-workspace-design.md`

## Global Constraints

- Supported uploads remain `.docx`, `.pdf`, `.txt` with an exact 25 MiB limit.
- TXT and DOCX must support later editable export; PDF is read-only.
- Shared dictionaries are loaded only from `resources/dictionaries`.
- A checker category failure produces `partial`; it must not discard successful categories.
- SSE events contain progress and counts, never document text or complete issue lists.
- PostgreSQL integration tests use real PostgreSQL; SQLite is not a substitute.
- All user-visible errors use structured codes and Chinese actionable messages.

---

### Task 1: Parser dependencies and normalized document model

**Files:**
- Modify: `apps/api/pyproject.toml`
- Modify: `apps/api/src/text_verification/domain/documents.py`
- Modify: `apps/api/src/text_verification/domain/ports.py`
- Test: `apps/api/tests/unit/domain/test_models.py`

**Interfaces:**
- Produces: `DocumentModel(version: int, metadata: dict[str, Any])`
- Produces: `ParseError(code: str, public_message: str)`
- Produces: `Parser.parse(source_path: Path, *, document_id: UUID, source_name: str) -> DocumentModel`

- [ ] **Step 1: Add failing model and protocol tests**

```python
def test_document_model_requires_positive_version() -> None:
    with pytest.raises(ValidationError):
        DocumentModel(
            document_id=uuid4(),
            file_type=FileType.TXT,
            source_name="sample.txt",
            version=0,
            blocks=[],
            metadata={},
        )


def test_text_block_rejects_empty_block_id() -> None:
    with pytest.raises(ValidationError):
        TextBlock(
            block_id="",
            kind="paragraph",
            text="正文",
            page=None,
            paragraph_index=0,
            parent_id=None,
            style={},
            source_locator={},
        )
```

- [ ] **Step 2: Run the model tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\domain\test_models.py -v
```

Expected: FAIL because `version`, `metadata`, and constrained `block_id` are absent.

- [ ] **Step 3: Add parser dependencies and update domain contracts**

Add to `[project].dependencies`:

```toml
"python-docx>=1.1,<2",
"pypdf>=5.1,<6",
```

Update models:

```python
class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str = Field(min_length=1)
    kind: Literal["paragraph", "heading", "table_cell", "header", "footer"]
    text: str
    page: int | None
    paragraph_index: int | None
    parent_id: str | None
    style: dict[str, Any]
    source_locator: dict[str, Any]


class DocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    file_type: FileType
    source_name: str
    version: int = Field(ge=1)
    blocks: list[TextBlock]
    metadata: dict[str, Any]


class ParseError(Exception):
    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
```

Update `Parser`:

```python
class Parser(Protocol):
    supported_type: FileType

    def parse(
        self,
        source_path: Path,
        *,
        document_id: UUID,
        source_name: str,
    ) -> DocumentModel: ...
```

- [ ] **Step 4: Install changed dependencies and run model tests**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pip install -e "apps\api[dev]"
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\domain\test_models.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps\api\pyproject.toml apps\api\src\text_verification\domain\documents.py apps\api\src\text_verification\domain\ports.py apps\api\tests\unit\domain\test_models.py
git commit -m "feat: define normalized document parsing contracts" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: TXT, DOCX, and PDF parsers

**Files:**
- Create: `apps/api/src/text_verification/parsers/__init__.py`
- Create: `apps/api/src/text_verification/parsers/registry.py`
- Create: `apps/api/src/text_verification/parsers/txt.py`
- Create: `apps/api/src/text_verification/parsers/docx.py`
- Create: `apps/api/src/text_verification/parsers/pdf.py`
- Create: `apps/api/tests/fixtures/documents/sample.docx`
- Create: `apps/api/tests/fixtures/documents/sample.pdf`
- Create: `apps/api/tests/unit/parsers/test_txt_parser.py`
- Create: `apps/api/tests/unit/parsers/test_docx_parser.py`
- Create: `apps/api/tests/unit/parsers/test_pdf_parser.py`

**Interfaces:**
- Consumes: `Parser.parse(source_path, document_id, source_name)`
- Produces: `ParserRegistry.get(file_type: FileType) -> Parser`
- Produces stable IDs: `p-000001`, `h-000001`, `t-000001-000001`, `pdf-000001`

- [ ] **Step 1: Write failing TXT parser tests**

```python
def test_txt_parser_normalizes_bom_and_line_endings(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_bytes(b"\xef\xbb\xbf\xe7\xac\xac\xe4\xb8\x80\xe8\xa1\x8c\r\n\r\n\xe7\xac\xac\xe4\xba\x8c\xe8\xa1\x8c")

    document = TxtParser().parse(
        source,
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        source_name="sample.txt",
    )

    assert [block.block_id for block in document.blocks] == ["p-000001", "p-000002"]
    assert [block.text for block in document.blocks] == ["第一行", "第二行"]
    assert document.metadata["encoding"] == "utf-8-sig"


def test_txt_parser_rejects_binary_content(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_bytes(b"\x00\x01\x02")

    with pytest.raises(ParseError, match="无法解析文本文件"):
        TxtParser().parse(source, document_id=uuid4(), source_name="sample.txt")
```

- [ ] **Step 2: Write failing DOCX and PDF parser tests**

```python
def test_docx_parser_preserves_paragraph_table_and_run_mapping(fixture_path: Path) -> None:
    document = DocxParser().parse(
        fixture_path / "sample.docx",
        document_id=uuid4(),
        source_name="sample.docx",
    )

    assert [block.kind for block in document.blocks] == [
        "heading",
        "paragraph",
        "table_cell",
        "table_cell",
    ]
    paragraph = document.blocks[1]
    assert paragraph.text == "核验示例文本"
    assert paragraph.source_locator["runs"] == [
        {"run_index": 0, "start": 0, "end": 2},
        {"run_index": 1, "start": 2, "end": 6},
    ]


def test_pdf_parser_rejects_pdf_without_extractable_text(fixture_path: Path) -> None:
    with pytest.raises(ParseError) as error:
        PdfParser().parse(
            fixture_path / "blank.pdf",
            document_id=uuid4(),
            source_name="blank.pdf",
        )

    assert error.value.code == "pdf_no_extractable_text"
    assert error.value.public_message == "PDF 中没有可提取的文本，请使用包含文本层的 PDF。"
```

- [ ] **Step 3: Run parser tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\parsers -v
```

Expected: FAIL because parser modules do not exist.

- [ ] **Step 4: Implement the parser registry and TXT parser**

```python
class ParserRegistry:
    def __init__(self, parsers: Iterable[Parser]) -> None:
        self._parsers = {parser.supported_type: parser for parser in parsers}

    def get(self, file_type: FileType) -> Parser:
        try:
            return self._parsers[file_type]
        except KeyError as error:
            raise ParseError("unsupported_parser", "暂不支持解析该文件类型。") from error
```

`TxtParser` must decode `utf-8-sig`, then UTF-8, then GB18030; reject NUL bytes; normalize CRLF; and create one paragraph block per non-empty paragraph.

- [ ] **Step 5: Implement DOCX and PDF parsers**

`DocxParser` must:

```python
for paragraph_index, paragraph in enumerate(document.paragraphs):
    text = "".join(run.text for run in paragraph.runs)
    runs = []
    offset = 0
    for run_index, run in enumerate(paragraph.runs):
        end = offset + len(run.text)
        runs.append({"run_index": run_index, "start": offset, "end": end})
        offset = end
```

Emit heading blocks for styles beginning with `Heading`, paragraph blocks for other non-empty paragraphs, and table-cell blocks in row-major order.

`PdfParser` must use `PdfReader`, emit one `pdf-NNNNNN` paragraph block per non-empty page, set `page` to the 1-based page number, and raise `pdf_encrypted` or `pdf_no_extractable_text` with public Chinese messages.

- [ ] **Step 6: Run parser tests and parser type checks**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\parsers -v
& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src\text_verification\parsers
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add apps\api\src\text_verification\parsers apps\api\tests\unit\parsers apps\api\tests\fixtures\documents
git commit -m "feat: parse txt docx and pdf documents" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Rule configuration and six-category checker registry

**Files:**
- Create: `resources/rules/common-rules.zh-cn.json`
- Create: `resources/rules/scenarios.zh-cn.json`
- Create: `apps/api/src/text_verification/checkers/__init__.py`
- Create: `apps/api/src/text_verification/checkers/models.py`
- Create: `apps/api/src/text_verification/checkers/rule_loader.py`
- Create: `apps/api/src/text_verification/checkers/rule_checker.py`
- Create: `apps/api/src/text_verification/checkers/registry.py`
- Modify: `apps/api/src/text_verification/domain/ports.py`
- Modify: `apps/api/src/text_verification/config.py`
- Create: `apps/api/tests/unit/checkers/test_rule_loader.py`
- Create: `apps/api/tests/unit/checkers/test_rule_checker.py`
- Create: `apps/api/tests/unit/checkers/test_registry.py`

**Interfaces:**
- Produces: `CheckCategory` enum with six values.
- Produces: `CheckOptions(scenario, enabled_categories)`.
- Produces: `CheckerRegistry.run(document, context, options) -> CheckRunResult`.
- Produces: `CheckRunResult(issues, completed_categories, failures)`.

- [ ] **Step 1: Write failing rule-loader and checker tests**

```python
def test_rule_loader_rejects_unknown_category(tmp_path: Path) -> None:
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps({"version": "1", "rules": [{"id": "x", "category": "unknown"}]}),
        encoding="utf-8",
    )

    with pytest.raises(RuleConfigurationError, match="unknown"):
        RuleLoader(path).load()


def test_rule_checker_emits_unicode_code_point_offsets() -> None:
    document = build_document("A😀绝对领先B")
    checker = RuleChecker(build_rule("ad-001", "security", "绝对领先", "领先"))

    issues = checker.check(document, CheckContext((), ()))

    assert [(issue.start, issue.end, issue.original) for issue in issues] == [
        (2, 6, "绝对领先")
    ]
```

- [ ] **Step 2: Write failing partial-category registry test**

```python
def test_registry_keeps_successful_issues_when_one_category_fails() -> None:
    registry = CheckerRegistry(
        {
            CheckCategory.CHARACTER: StaticChecker([build_issue("character")]),
            CheckCategory.SECURITY: ExplodingChecker(RuntimeError("bad dictionary")),
        }
    )

    result = registry.run(
        build_document("正文"),
        CheckContext((), ()),
        CheckOptions(
            scenario="general",
            enabled_categories={CheckCategory.CHARACTER, CheckCategory.SECURITY},
        ),
    )

    assert [issue.layer for issue in result.issues] == ["character"]
    assert result.completed_categories == {CheckCategory.CHARACTER}
    assert result.failures == {
        CheckCategory.SECURITY: CheckerFailure(
            code="checker_failed",
            message="安全检查暂时不可用。",
        )
    }
```

- [ ] **Step 3: Run checker tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\checkers -v
```

Expected: FAIL because checker modules do not exist.

- [ ] **Step 4: Define typed rule files and loader**

Each rule JSON entry must contain:

```json
{
  "id": "security-ad-001",
  "category": "security",
  "severity": "warning",
  "pattern": "绝对领先",
  "suggestion": "领先",
  "message": "避免使用绝对化表述。",
  "scenarios": ["general", "business", "news"],
  "auto_fixable": true
}
```

`RuleLoader` validates unique IDs, known categories, non-empty patterns, valid severities, and valid scenarios. Add `rules_root: Path = Path("./resources/rules")` and `dictionaries_root: Path = Path("./resources/dictionaries")` to settings.

- [ ] **Step 5: Implement rule matching and registry isolation**

`RuleChecker` uses `str.find` in a loop for literal rules and constructs deterministic UUID5 issue IDs from `document_id`, rule ID, block ID, and offsets. `CheckerRegistry.run` catches exceptions per category, logs the exception type without document content, and returns typed failures with fixed public messages.

- [ ] **Step 6: Run checker tests, lint, and type checks**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\checkers -v
& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api\src\text_verification\checkers
& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src\text_verification\checkers
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add resources\rules apps\api\src\text_verification\checkers apps\api\src\text_verification\domain\ports.py apps\api\src\text_verification\config.py apps\api\tests\unit\checkers
git commit -m "feat: add local document checking engine" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Persist document blocks, issues, and checker failures

**Files:**
- Create: `apps/api/alembic/versions/0002_create_documents_issues.py`
- Modify: `apps/api/src/text_verification/infrastructure/orm.py`
- Create: `apps/api/src/text_verification/infrastructure/analysis_repositories.py`
- Create: `apps/api/tests/integration/test_analysis_repository.py`

**Interfaces:**
- Produces: `AnalysisRepository.replace_analysis(job_id, document, issues, failures) -> None`.
- Produces: `AnalysisRepository.get_document(job_id) -> DocumentModel | None`.
- Produces: `AnalysisRepository.list_issues(job_id, query) -> IssuePage`.
- Produces: `IssueQuery(category, severity, decision, search, cursor, limit)`.

- [ ] **Step 1: Write failing repository round-trip test**

```python
def test_repository_round_trips_document_and_issue(postgres_session: Session) -> None:
    repository = AnalysisRepository(postgres_session)
    job_id = seed_job(postgres_session)
    document = build_document("绝对领先")
    issue = build_issue(document, original="绝对领先")

    repository.replace_analysis(job_id, document, [issue], {})
    postgres_session.commit()

    stored = repository.get_document(job_id)
    page = repository.list_issues(job_id, IssueQuery(limit=20))
    assert stored == document
    assert page.items == [issue]
    assert page.total == 1
```

- [ ] **Step 2: Write failing replacement atomicity test**

```python
def test_replace_analysis_is_atomic(postgres_session: Session) -> None:
    repository = AnalysisRepository(postgres_session)
    job_id = seed_job(postgres_session)
    repository.replace_analysis(job_id, build_document("旧"), [], {})
    postgres_session.commit()

    with pytest.raises(IntegrityError):
        repository.replace_analysis(job_id, build_document("新"), [invalid_issue()], {})
        postgres_session.flush()
    postgres_session.rollback()

    assert repository.get_document(job_id).blocks[0].text == "旧"
```

- [ ] **Step 3: Run the integration test and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_analysis_repository.py -v
```

Expected: FAIL because tables and repository do not exist.

- [ ] **Step 4: Add normalized analysis tables**

Migration creates:

- `documents(job_id PK/FK, document_id, version, file_type, source_name, metadata_json)`
- `document_blocks(job_id FK, block_id, block_order, kind, text, page, paragraph_index, parent_id, style_json, source_locator_json)`
- `issues(issue_id PK, job_id FK, document_version, category, severity, rule_id, block_id, start_offset, end_offset, original, suggestion, alternatives_json, message, source, source_version, confidence, auto_fixable, context)`
- `checker_failures(job_id FK, category, code, message)`

Add indexes on `(job_id, category)`, `(job_id, severity)`, `(job_id, block_id, start_offset)`, and full-text-neutral `original` search through `ILIKE` for phase one.

- [ ] **Step 5: Implement repository mapping and cursor pagination**

Cursor is `(block_order, start_offset, issue_id)` encoded as URL-safe JSON. Query order is stable by that tuple. `replace_analysis` deletes old blocks, issues, and failures only inside the caller's transaction and inserts the new version.

- [ ] **Step 6: Apply migration and run repository tests**

Run:

```powershell
docker compose -f infra\compose.yaml run --rm migrate alembic upgrade head
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_analysis_repository.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add apps\api\alembic\versions\0002_create_documents_issues.py apps\api\src\text_verification\infrastructure\orm.py apps\api\src\text_verification\infrastructure\analysis_repositories.py apps\api\tests\integration\test_analysis_repository.py
git commit -m "feat: persist analysis documents and issues" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Run parsers and checkers in the Celery pipeline

**Files:**
- Modify: `apps/api/src/text_verification/workers/pipeline.py`
- Modify: `apps/api/src/text_verification/workers/tasks.py`
- Modify: `apps/api/tests/integration/test_pipeline_task.py`

**Interfaces:**
- Consumes: `ParserRegistry`, `CheckerRegistry`, `AnalysisRepository`.
- Produces: terminal `completed`, `partial`, or `failed` job status and persisted results.

- [ ] **Step 1: Replace the stub expectation with a failing analysis test**

```python
def test_process_job_persists_analysis_and_completes(
    monkeypatch, worker_storage, celery_eager
) -> None:
    repository = InMemoryJobRepository()
    analysis_repository = InMemoryAnalysisRepository()
    job_id = _seed_txt_job(repository, worker_storage, text="这是绝对领先的方案")
    configure_real_pipeline(monkeypatch, repository, analysis_repository, worker_storage)

    result = process_job.delay(str(job_id))

    assert result.successful()
    assert repository.get_job(job_id).status == JobStatus.COMPLETED
    assert analysis_repository.get_document(job_id) is not None
    assert [issue.rule_id for issue in analysis_repository.issues] == ["security-ad-001"]
```

- [ ] **Step 2: Add a failing partial-result test**

```python
def test_process_job_marks_partial_and_keeps_available_issues(
    monkeypatch, worker_storage, celery_eager
) -> None:
    checker_registry = checker_registry_with_failure(CheckCategory.SECURITY)
    job_id, repository, analysis_repository = configured_job(
        monkeypatch, worker_storage, checker_registry
    )

    process_job.delay(str(job_id))

    assert repository.get_job(job_id).status == JobStatus.PARTIAL
    assert analysis_repository.failures[CheckCategory.SECURITY].code == "checker_failed"
    assert analysis_repository.issues
```

- [ ] **Step 3: Run pipeline tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_pipeline_task.py -v
```

Expected: FAIL because the runner does not invoke parser/checker dependencies.

- [ ] **Step 4: Inject analysis dependencies into `PipelineRunner`**

Constructor:

```python
def __init__(
    self,
    repository: JobRepository,
    analysis_repository: AnalysisRepository,
    storage: JobStorage,
    parsers: ParserRegistry,
    checkers: CheckerRegistry,
) -> None:
```

At `PARSING`, resolve the source path and parser, persist parsing progress, run enabled checkers in deterministic category order, call `replace_analysis`, and transition to `PARTIAL` when failures are non-empty.

- [ ] **Step 5: Preserve retry and transaction behavior**

Build all dependencies in `RUNNER_FACTORY`. Parser errors are expected permanent failures with their structured public message. Database and unexpected checker infrastructure errors retain existing Celery retry behavior. Successful analysis and terminal transition commit in one session transaction boundary per stage.

- [ ] **Step 6: Run pipeline and worker regression tests**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_pipeline_task.py apps\api\tests\integration\test_job_progress.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add apps\api\src\text_verification\workers\pipeline.py apps\api\src\text_verification\workers\tasks.py apps\api\tests\integration\test_pipeline_task.py
git commit -m "feat: execute document analysis pipeline" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 6: Upload options and analysis read APIs

**Files:**
- Modify: `apps/api/src/text_verification/domain/jobs.py`
- Modify: `apps/api/src/text_verification/infrastructure/orm.py`
- Create: `apps/api/alembic/versions/0003_add_job_check_options.py`
- Modify: `apps/api/src/text_verification/api/routes/jobs.py`
- Create: `apps/api/src/text_verification/api/routes/analysis.py`
- Modify: `apps/api/src/text_verification/api/router.py`
- Modify: `apps/api/tests/integration/test_create_job.py`
- Create: `apps/api/tests/integration/test_analysis_api.py`

**Interfaces:**
- Produces upload fields: `scenario` and repeated `enabled_categories`.
- Produces: `GET /api/v1/jobs/{job_id}/document`.
- Produces: `GET /api/v1/jobs/{job_id}/issues`.
- Produces: `GET /api/v1/jobs/{job_id}/summary`.

- [ ] **Step 1: Write failing upload-options tests**

```python
def test_create_job_persists_scenario_and_categories(client: TestClient) -> None:
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", "text/plain")},
        data={
            "scenario": "legal",
            "enabled_categories": ["character", "security"],
        },
    )

    assert response.status_code == 202
    stored = load_job(response.json()["job_id"])
    assert stored.scenario == "legal"
    assert stored.enabled_categories == ["character", "security"]
```

- [ ] **Step 2: Write failing document and issue API tests**

```python
def test_analysis_endpoints_return_paginated_results(client: TestClient) -> None:
    job_id = seed_completed_analysis()

    document = client.get(f"/api/v1/jobs/{job_id}/document")
    issues = client.get(
        f"/api/v1/jobs/{job_id}/issues",
        params={"category": "security", "limit": 20},
    )
    summary = client.get(f"/api/v1/jobs/{job_id}/summary")

    assert document.status_code == 200
    assert document.json()["blocks"][0]["block_id"] == "p-000001"
    assert issues.json()["total"] == 1
    assert summary.json()["by_category"]["security"] == 1
```

- [ ] **Step 3: Run API tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_create_job.py apps\api\tests\integration\test_analysis_api.py -v
```

Expected: FAIL because options and routes are absent.

- [ ] **Step 4: Persist validated upload options**

Add `scenario` and JSON `enabled_categories` to `jobs`. Accept only six defined scenarios and six categories. Omitted values default to `general` and all categories. Reject an empty category list with HTTP 422 and `invalid_check_categories`.

- [ ] **Step 5: Implement read routes and error contracts**

Return HTTP 409 `analysis_not_ready` for active jobs, HTTP 404 `job_not_found` for unknown jobs, and available data plus `checker_failures` for `partial` jobs. Document blocks use cursor pagination by block order; issues use repository cursor pagination.

- [ ] **Step 6: Apply migration and run API/full backend checks**

Run:

```powershell
docker compose -f infra\compose.yaml run --rm migrate alembic upgrade head
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -v
& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api
& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src
```

Expected: all commands PASS.

- [ ] **Step 7: Commit**

```powershell
git add apps\api\src apps\api\alembic\versions\0003_add_job_check_options.py apps\api\tests
git commit -m "feat: expose document analysis results" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Phase Acceptance

Run:

```powershell
docker compose -f infra\compose.yaml up -d postgres redis
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -v
& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api
& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src
```

Expected: TXT, DOCX, and text PDF fixtures parse; six categories run; partial failures persist; read APIs return normalized blocks, issues, summaries, and failures.
