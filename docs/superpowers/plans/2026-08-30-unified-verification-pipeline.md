# Unified Verification Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make synchronous FastAPI analysis and asynchronous Celery jobs execute one secure, persisted verification pipeline for all seven formats.

**Architecture:** Introduce registries and an application service around the canonical models from the baseline plan. Consolidate upload storage, persist verification results, route the current synchronous endpoint through the service, and replace the Celery stub with the same service.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL 16, Alembic, Celery 5, Redis 7, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-translation-pre-checker-integration-design.md`

## Global Constraints

- Complete `2026-08-30-canonical-models-and-compatibility-baseline.md` first.
- Preserve existing API fields, Job/Event behavior, retries, SSE replay, and cleanup.
- Support DOCX, DOC, PDF, TXT, RTF, Markdown, and CSV through one capability manifest.
- Synchronous and asynchronous executions must return equivalent canonical results.
- Keep the application usable after every task.
- Use real PostgreSQL integration tests for persistence behavior.

---

### Task 1: Consolidate seven-format upload storage

**Files:**
- Create: `apps/api/src/text_verification/infrastructure/document_storage.py`
- Modify: `apps/api/src/text_verification/infrastructure/storage.py`
- Modify: `apps/api/src/text_verification/compatibility/storage.py`
- Modify: `apps/api/src/text_verification/api/routes/jobs.py`
- Test: `apps/api/tests/unit/infrastructure/test_document_storage.py`
- Modify: `apps/api/tests/unit/infrastructure/test_storage.py`

**Interfaces:**
- Produces: `DocumentStorage.save_stream(document_id, original_name, source) -> StoredDocument`.
- Produces: `DocumentStorage.source_path(document_id, file_type) -> Path`.
- Produces: `DocumentStorage.delete(document_id)`.
- Produces: `DocumentStorage.delete_orphaned_directories(persisted_ids, older_than)`.

- [ ] **Step 1: Write failing storage tests for all formats**

```python
@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("sample.txt", b"hello", FileType.TXT),
        ("sample.md", b"# title", FileType.MARKDOWN),
        ("sample.csv", b"a,b\n1,2\n", FileType.CSV),
        ("sample.rtf", br"{\rtf1 hello}", FileType.RTF),
        ("sample.pdf", b"%PDF-1.7\n", FileType.PDF),
    ],
)
def test_save_stream_detects_supported_type(name, content, expected, tmp_path):
    stored = DocumentStorage(tmp_path, 1024).save_bytes(uuid4(), name, content)
    assert stored.file_type is expected
```

Retain existing DOCX archive safety, path escape, reparse-point, size, and
cleanup tests.

- [ ] **Step 2: Run storage tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/infrastructure/test_document_storage.py tests/unit/infrastructure/test_storage.py -v
```

Expected: FAIL because one seven-format storage service does not exist.

- [ ] **Step 3: Extract shared validation and lifecycle behavior**

Implement `DocumentStorage` using the existing `JobStorage` safety checks.
Make `JobStorage` and `CompatibilityStorage` thin temporary adapters that
delegate to it, preserving their current directory contracts until callers are
migrated.

- [ ] **Step 4: Run storage and upload integration tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/infrastructure tests/integration/test_create_job.py tests/integration/test_compatibility_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/infrastructure apps/api/src/text_verification/compatibility/storage.py apps/api/src/text_verification/api/routes/jobs.py apps/api/tests
git commit -m "refactor: unify document upload storage"
```

### Task 2: Add parser, checker, and exporter registries

**Files:**
- Create: `apps/api/src/text_verification/parsers/registry.py`
- Create: `apps/api/src/text_verification/parsers/compatibility_parser.py`
- Create: `apps/api/src/text_verification/checkers/registry.py`
- Create: `apps/api/src/text_verification/checkers/compatibility_checker.py`
- Create: `apps/api/src/text_verification/exporters/registry.py`
- Create: `apps/api/src/text_verification/exporters/compatibility_exporter.py`
- Test: `apps/api/tests/unit/application/test_registries.py`

**Interfaces:**
- Produces: `ParserRegistry.get(file_type: FileType) -> Parser`.
- Produces: `CheckerRegistry.run(document, context) -> list[Issue]`.
- Produces: `ExporterRegistry.get(file_type: FileType) -> Exporter`.

- [ ] **Step 1: Write failing registry tests**

```python
def test_parser_registry_rejects_duplicate_file_type() -> None:
    registry = ParserRegistry()
    registry.register(FakeParser(FileType.TXT))
    with pytest.raises(DuplicateCapabilityError):
        registry.register(FakeParser(FileType.TXT))


def test_checker_registry_runs_in_layer_then_registration_order() -> None:
    registry = CheckerRegistry([checker("sentence"), checker("character")])
    issues = registry.run(document, context)
    assert [item.layer for item in issues] == ["character", "sentence"]
```

- [ ] **Step 2: Run tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/application/test_registries.py -v
```

Expected: FAIL with missing registry modules.

- [ ] **Step 3: Implement registries and compatibility adapters**

`CompatibilityParser` wraps `compatibility.parser.parse_file()` and constructs
canonical blocks from its page/paragraph map. `CompatibilityChecker` wraps
`TextAnalyzer`. `CompatibilityExporter` wraps `export_original()`.

Reject missing and duplicate registrations with typed errors:

```python
class MissingCapabilityError(LookupError):
    def __init__(self, kind: str, key: str) -> None:
        super().__init__(f"No {kind} registered for {key}.")
```

- [ ] **Step 4: Run registry tests and static checks**

Run:

```bash
cd apps/api
python -m pytest tests/unit/application/test_registries.py -v
python -m ruff check src/text_verification/parsers src/text_verification/checkers src/text_verification/exporters
python -m mypy src/text_verification/parsers src/text_verification/checkers src/text_verification/exporters
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/parsers apps/api/src/text_verification/checkers apps/api/src/text_verification/exporters apps/api/tests/unit/application
git commit -m "feat: add verification capability registries"
```

### Task 3: Implement the application verification pipeline

**Files:**
- Create: `apps/api/src/text_verification/application/verification_pipeline.py`
- Create: `apps/api/src/text_verification/application/errors.py`
- Create: `apps/api/src/text_verification/application/factory.py`
- Test: `apps/api/tests/unit/application/test_verification_pipeline.py`

**Interfaces:**
- Produces: `VerificationCommand`.
- Produces: `VerificationPipeline.run(command) -> VerificationResult`.
- Produces: stage-specific `VerificationError(code, stage, message, retryable)`.

- [ ] **Step 1: Write a failing orchestration test**

```python
def test_pipeline_parses_checks_reviews_and_summarizes_in_order() -> None:
    pipeline = build_pipeline(
        parser=recording_parser,
        checker=recording_checker,
        reviewer=recording_reviewer,
    )
    result = pipeline.run(command)
    assert calls == ["parse", "check", "review"]
    assert result.document_id == document.document_id
    assert result.execution_mode == command.execution_mode
```

Add tests proving LLM failure records degraded mode and retains local issues.

- [ ] **Step 2: Run pipeline tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/application/test_verification_pipeline.py -v
```

Expected: FAIL because the application pipeline is missing.

- [ ] **Step 3: Implement the pipeline**

```python
@dataclass(frozen=True)
class VerificationCommand:
    document_id: UUID
    source_path: Path | None
    direct_text: str | None
    source_name: str
    file_type: FileType
    options: VerificationOptions
    execution_mode: ExecutionMode


class VerificationPipeline:
    def run(self, command: VerificationCommand) -> VerificationResult:
        document = self._load_document(command)
        issues = self._checkers.run(document, CheckContext.from_options(command.options))
        reviewed, review_metadata = self._reviewer.review(document, issues)
        return VerificationResult.from_analysis(
            document=document,
            issues=reviewed,
            options=command.options,
            review_metadata=review_metadata,
            execution_mode=command.execution_mode,
        )
```

Wrap parser, checker, and persistence failures in stage-specific application
errors. Do not catch programming errors as successful results.

- [ ] **Step 4: Run pipeline and compatibility tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/application tests/integration/test_compatibility_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/application apps/api/tests/unit/application
git commit -m "feat: add unified verification pipeline"
```

### Task 4: Persist documents, runs, issues, and artifacts

**Files:**
- Create: `apps/api/alembic/versions/0002_add_verification_results.py`
- Modify: `apps/api/src/text_verification/infrastructure/orm.py`
- Create: `apps/api/src/text_verification/infrastructure/verification_repository.py`
- Test: `apps/api/tests/integration/test_verification_repository.py`

**Interfaces:**
- Produces: `VerificationRepository.save_result(job_id, result)`.
- Produces: `VerificationRepository.get_result_for_job(job_id) -> VerificationResult | None`.
- Produces: `VerificationRepository.save_review_revision(...)`.
- Produces: `VerificationRepository.save_export_artifact(...)`.

- [ ] **Step 1: Write failing repository round-trip test**

```python
def test_save_and_load_verification_result(repository, job):
    repository.save_result(job.job_id, result)
    repository.commit()
    loaded = repository.get_result_for_job(job.job_id)
    assert loaded == result
    assert loaded.issues[0].issue_id == result.issues[0].issue_id
```

- [ ] **Step 2: Run migration and repository test**

Run:

```bash
cd apps/api
python -m pytest tests/integration/test_verification_repository.py -v
```

Expected: FAIL because the result tables and repository are missing.

- [ ] **Step 3: Add normalized result persistence**

Create tables for documents, verification runs, issues, review revisions, and
export artifacts. Use foreign keys with cascade behavior from jobs to runs and
from runs to issues. Add unique constraints for stable issue IDs per run.

Implement explicit domain-to-row and row-to-domain mapping; do not store the
entire result as an unvalidated JSON blob.

- [ ] **Step 4: Run database integration tests**

Run:

```bash
cd apps/api
python -m pytest tests/integration/test_job_repository.py tests/integration/test_verification_repository.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/alembic apps/api/src/text_verification/infrastructure apps/api/tests/integration/test_verification_repository.py
git commit -m "feat: persist verification results"
```

### Task 5: Route synchronous analysis through the pipeline

**Files:**
- Modify: `apps/api/src/text_verification/api/routes/compatibility.py`
- Modify: `apps/api/src/text_verification/compatibility/service.py`
- Modify: `apps/api/src/text_verification/main.py`
- Modify: `apps/api/tests/integration/test_compatibility_api.py`

**Interfaces:**
- Consumes: `VerificationPipeline`.
- Preserves: `/api/v1/analyze`, `/api/v1/export`, and `/api/v1/export-original`.

- [ ] **Step 1: Add an endpoint injection test**

```python
def test_analyze_route_uses_injected_pipeline(app, client):
    pipeline = RecordingPipeline(result)
    app.dependency_overrides[get_verification_pipeline] = lambda: pipeline
    response = client.post("/api/v1/analyze", data={"text": "检查文本"})
    assert response.status_code == 200
    assert len(pipeline.commands) == 1
    assert pipeline.commands[0].direct_text == "检查文本"
```

- [ ] **Step 2: Run the endpoint test**

Run:

```bash
cd apps/api
python -m pytest tests/integration/test_compatibility_api.py -v
```

Expected: FAIL because the route directly invokes compatibility services.

- [ ] **Step 3: Inject and call the pipeline**

Keep form parsing and legacy response mapping at the route boundary. Replace
direct parser and analyzer calls with a `VerificationCommand`.

- [ ] **Step 4: Run API tests**

Run:

```bash
cd apps/api
python -m pytest tests/integration/test_compatibility_api.py -v
```

Expected: PASS with unchanged existing fields and canonical IDs.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/api apps/api/src/text_verification/compatibility apps/api/src/text_verification/main.py apps/api/tests/integration/test_compatibility_api.py
git commit -m "refactor: route synchronous checks through pipeline"
```

### Task 6: Replace the Celery stub and expose persisted results

**Files:**
- Modify: `apps/api/src/text_verification/workers/pipeline.py`
- Modify: `apps/api/src/text_verification/workers/tasks.py`
- Modify: `apps/api/src/text_verification/api/routes/jobs.py`
- Modify: `apps/api/src/text_verification/domain/jobs.py`
- Modify: `apps/api/tests/integration/test_pipeline_task.py`
- Modify: `apps/api/tests/integration/test_job_progress.py`
- Create: `apps/api/tests/integration/test_sync_async_equivalence.py`

**Interfaces:**
- Produces: `GET /api/v1/jobs/{job_id}/result`.
- Uses: the same `VerificationPipeline` as synchronous analysis.

- [ ] **Step 1: Write failing worker and equivalence tests**

```python
def test_worker_persists_pipeline_result(runner, repository):
    runner.run(job_id)
    assert repository.get_result_for_job(job_id) is not None
    assert repository.get_job(job_id).status is JobStatus.COMPLETED


def test_sync_and_async_results_are_equivalent(sync_client, completed_job_result):
    sync = sync_client.post("/api/v1/analyze", data={"text": SAMPLE}).json()
    assert normalize(sync) == normalize(completed_job_result)
```

- [ ] **Step 2: Run worker tests**

Run:

```bash
cd apps/api
python -m pytest tests/integration/test_pipeline_task.py tests/integration/test_sync_async_equivalence.py -v
```

Expected: FAIL because the worker only checks file existence.

- [ ] **Step 3: Execute real stages**

Transition through parsing and rule-layer statuses while invoking the shared
pipeline. Persist the result before transitioning to `COMPLETED`. Add the result
endpoint and return `409` while a non-terminal job has no result, `404` for an
unknown job, and the canonical result for a completed job.

- [ ] **Step 4: Run backend verification**

Run:

```bash
cd apps/api
python -m pytest tests/integration/test_pipeline_task.py tests/integration/test_job_progress.py tests/integration/test_sync_async_equivalence.py -v
python -m ruff check src tests
python -m mypy src
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/workers apps/api/src/text_verification/api/routes/jobs.py apps/api/src/text_verification/domain/jobs.py apps/api/tests
git commit -m "feat: run verification in asynchronous jobs"
```

