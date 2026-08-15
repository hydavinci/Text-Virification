# Document Exports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate modified TXT/DOCX files and consistent HTML/PDF issue reports from accepted review decisions.

**Architecture:** Export requests are persisted and dispatched as Celery tasks. A replacement planner validates accepted changes against normalized blocks; format-specific exporters apply safe changes, while one report model feeds both HTML and PDF renderers.

**Tech Stack:** Python 3.12, Celery 5, SQLAlchemy 2, PostgreSQL 16, python-docx, Jinja2, WeasyPrint, pytest.

**Spec:** `docs/superpowers/specs/2026-08-15-document-review-workspace-design.md`

## Global Constraints

- Requires the core analysis and issue review plans.
- Modified files are supported only for TXT and DOCX.
- PDF uploads support HTML/PDF reports only.
- Unsafe DOCX replacements remain unapplied and appear in export warnings.
- Export files remain inside the job UUID directory and expire with the job.
- HTML and PDF reports use the same report model and template content.

---

### Task 1: Export model, storage, and lifecycle

**Files:**
- Modify: `apps/api/pyproject.toml`
- Create: `apps/api/src/text_verification/domain/exports.py`
- Create: `apps/api/alembic/versions/0005_create_exports.py`
- Modify: `apps/api/src/text_verification/infrastructure/orm.py`
- Create: `apps/api/src/text_verification/infrastructure/export_repository.py`
- Modify: `apps/api/src/text_verification/infrastructure/storage.py`
- Create: `apps/api/tests/integration/test_export_repository.py`
- Modify: `apps/api/tests/unit/infrastructure/test_storage.py`

**Interfaces:**
- Produces: `ExportType(modified_document, html_report, pdf_report)`.
- Produces: `ExportStatus(queued, processing, completed, failed)`.
- Produces: `ExportRepository`.
- Produces: `JobStorage.export_path(job_id, export_id, extension) -> Path`.

- [ ] **Step 1: Add failing repository and path-containment tests**

```python
def test_export_lifecycle_round_trip(postgres_session: Session) -> None:
    job_id = seed_job(postgres_session)
    repository = ExportRepository(postgres_session)
    export = repository.create(job_id, ExportType.HTML_REPORT, "report.html")
    repository.mark_processing(export.export_id)
    repository.mark_completed(export.export_id, warnings=["1 项修改未自动应用"])
    postgres_session.commit()
    assert repository.get(export.export_id).status == ExportStatus.COMPLETED


def test_export_path_stays_inside_job_directory(storage: JobStorage) -> None:
    with pytest.raises(ValueError):
        storage.export_path(uuid4(), uuid4(), "../report.html")
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_export_repository.py apps\api\tests\unit\infrastructure\test_storage.py -v
```

Expected: FAIL because export models and methods are absent.

- [ ] **Step 3: Add dependencies and migration**

Add:

```toml
"jinja2>=3.1,<4",
"weasyprint>=63,<64",
```

Create `exports` with UUID primary key, job foreign key, type, status, file name, storage key, warnings JSON, error code/message, timestamps, and expiry. Index `(job_id, created_at)`.

- [ ] **Step 4: Implement repository and storage boundaries**

Allow only extension values `txt`, `docx`, `html`, `pdf`; generate server-side names; never use a user path. State transitions must reject changes after `completed` or `failed`.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
docker compose -f infra\compose.yaml run --rm migrate alembic upgrade head
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_export_repository.py apps\api\tests\unit\infrastructure\test_storage.py -v
```

Expected: PASS.

```powershell
git add apps\api\pyproject.toml apps\api\src\text_verification\domain\exports.py apps\api\src\text_verification\infrastructure apps\api\alembic\versions\0005_create_exports.py apps\api\tests
git commit -m "feat: add export lifecycle and storage" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Replacement planner and modified TXT export

**Files:**
- Create: `apps/api/src/text_verification/exporters/__init__.py`
- Create: `apps/api/src/text_verification/exporters/replacements.py`
- Create: `apps/api/src/text_verification/exporters/txt.py`
- Create: `apps/api/tests/unit/exporters/test_replacements.py`
- Create: `apps/api/tests/unit/exporters/test_txt_exporter.py`

**Interfaces:**
- Produces: `Replacement(block_id, start, end, original, value, issue_id)`.
- Produces: `ReplacementPlan(applicable, warnings)`.
- Produces: `ReplacementPlanner.build(document, issues_with_decisions)`.

- [ ] **Step 1: Write failing overlap and Unicode tests**

```python
def test_planner_rejects_overlapping_replacements() -> None:
    plan = ReplacementPlanner().build(
        build_document("甲乙丙丁"),
        [
            accepted_issue(start=0, end=3, replacement="A"),
            accepted_issue(start=2, end=4, replacement="B"),
        ],
    )
    assert plan.applicable == []
    assert [warning.code for warning in plan.warnings] == [
        "overlapping_replacements",
        "overlapping_replacements",
    ]


def test_txt_export_applies_code_point_offsets_from_end(tmp_path: Path) -> None:
    target = tmp_path / "modified.txt"
    TxtExporter().export_text(
        "A😀绝对领先B",
        [Replacement("p-1", 2, 6, "绝对领先", "领先", uuid4())],
        target,
    )
    assert target.read_text(encoding="utf-8") == "A😀领先B"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\exporters\test_replacements.py apps\api\tests\unit\exporters\test_txt_exporter.py -v
```

Expected: FAIL because exporter modules do not exist.

- [ ] **Step 3: Implement planner validation**

Validate block existence, bounds, exact original text match, non-overlap, and accepted/custom action. Accepted uses the issue suggestion; custom uses the decision replacement. Ignored and unreviewed issues do not enter the plan.

- [ ] **Step 4: Implement TXT export**

Reconstruct TXT blocks with a single blank line between paragraphs. Apply replacements per block in descending `start` order. Write UTF-8 without BOM and terminate with one newline.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\exporters\test_replacements.py apps\api\tests\unit\exporters\test_txt_exporter.py -v
```

Expected: PASS.

```powershell
git add apps\api\src\text_verification\exporters apps\api\tests\unit\exporters
git commit -m "feat: plan replacements and export txt" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Format-preserving DOCX export

**Files:**
- Create: `apps/api/src/text_verification/exporters/docx.py`
- Create: `apps/api/tests/unit/exporters/test_docx_exporter.py`
- Reuse: `apps/api/tests/fixtures/documents/sample.docx`

**Interfaces:**
- Produces: `DocxExporter.export(source, document, plan, target) -> ExportResult`.
- Produces warnings with code `unsafe_docx_run_boundary`.

- [ ] **Step 1: Write failing safe and unsafe replacement tests**

```python
def test_docx_export_preserves_style_for_single_run_replacement(tmp_path: Path) -> None:
    result = export_fixture_replacement(
        fixture="sample.docx",
        block_id="p-000002",
        start=2,
        end=6,
        replacement="专业",
        target=tmp_path / "modified.docx",
    )
    reparsed = DocxParser().parse(result.path, document_id=uuid4(), source_name="modified.docx")
    assert reparsed.blocks[1].text == "核验专业"
    assert read_run_bold(result.path, paragraph=1, run=1) is True
    assert result.warnings == []


def test_docx_export_warns_and_skips_cross_run_replacement(tmp_path: Path) -> None:
    result = export_fixture_replacement(
        fixture="sample.docx",
        block_id="p-000002",
        start=1,
        end=4,
        replacement="替换",
        target=tmp_path / "modified.docx",
    )
    assert result.warnings[0].code == "unsafe_docx_run_boundary"
    assert read_paragraph_text(result.path, paragraph=1) == "核验示例文本"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\exporters\test_docx_exporter.py -v
```

Expected: FAIL because `DocxExporter` is absent.

- [ ] **Step 3: Implement locator resolution**

Resolve paragraph and table-cell locators generated by `DocxParser`. A replacement is safe only when its full range lies inside one recorded run. Apply multiple replacements within that run from highest offset to lowest.

- [ ] **Step 4: Save to a temporary sibling and atomically replace target**

Write `<target>.tmp`, reopen it with `python-docx` to verify it is readable, then `Path.replace(target)`. Remove the temporary file on any error and surface `docx_export_failed`.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\exporters\test_docx_exporter.py -v
```

Expected: PASS.

```powershell
git add apps\api\src\text_verification\exporters\docx.py apps\api\tests\unit\exporters\test_docx_exporter.py
git commit -m "feat: export safe docx replacements" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Shared HTML and PDF issue reports

**Files:**
- Create: `apps/api/src/text_verification/exporters/report.py`
- Create: `apps/api/src/text_verification/templates/issue_report.html`
- Create: `apps/api/tests/unit/exporters/test_report_exporter.py`
- Modify: `apps/api/Dockerfile`

**Interfaces:**
- Produces: `ReportModel`.
- Produces: `ReportExporter.render_html(model, target)`.
- Produces: `ReportExporter.render_pdf(model, target)`.

- [ ] **Step 1: Write failing shared-content test**

```python
def test_html_and_pdf_reports_share_title_counts_and_issues(tmp_path: Path) -> None:
    model = build_report_model(source_name="sample.docx", total=2)
    html_path = ReportExporter().render_html(model, tmp_path / "report.html")
    pdf_path = ReportExporter().render_pdf(model, tmp_path / "report.pdf")

    assert "sample.docx" in html_path.read_text(encoding="utf-8")
    assert "发现问题：2" in html_path.read_text(encoding="utf-8")
    pdf_text = PdfReader(pdf_path).pages[0].extract_text()
    assert "sample.docx" in pdf_text
    assert "发现问题：2" in pdf_text
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\exporters\test_report_exporter.py -v
```

Expected: FAIL because report exporter and template are absent.

- [ ] **Step 3: Implement one report model and template**

The model contains source name, generated time, scenario, enabled/completed/failed categories, summary counts, every issue with decision, and export warnings. Escape all source and issue text through Jinja autoescape.

- [ ] **Step 4: Render HTML and PDF from the same HTML**

Write the rendered HTML directly for HTML export. Pass the identical string to `weasyprint.HTML(string=html, base_url=template_dir).write_pdf(target)`. Add required Debian Pango/Cairo packages to the runtime image.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\unit\exporters\test_report_exporter.py -v
```

Expected: PASS.

```powershell
git add apps\api\src\text_verification\exporters\report.py apps\api\src\text_verification\templates apps\api\tests\unit\exporters\test_report_exporter.py apps\api\Dockerfile
git commit -m "feat: export html and pdf issue reports" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Export task and API

**Files:**
- Create: `apps/api/src/text_verification/workers/export_tasks.py`
- Create: `apps/api/src/text_verification/api/routes/exports.py`
- Modify: `apps/api/src/text_verification/api/router.py`
- Modify: `apps/api/src/text_verification/workers/celery_app.py`
- Create: `apps/api/tests/integration/test_export_task.py`
- Create: `apps/api/tests/integration/test_export_api.py`
- Modify: `apps/api/tests/integration/test_cleanup.py`

**Interfaces:**
- Produces `POST /api/v1/jobs/{job_id}/exports`.
- Produces `GET /api/v1/jobs/{job_id}/exports/{export_id}`.
- Produces `GET /api/v1/jobs/{job_id}/exports/{export_id}/download`.

- [ ] **Step 1: Write failing API restrictions test**

```python
def test_pdf_job_rejects_modified_document_export(client: TestClient) -> None:
    job_id = seed_completed_pdf_job()
    response = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "modified_document"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_export_type"
```

- [ ] **Step 2: Write failing end-to-end export task test**

```python
def test_txt_export_task_completes_and_downloads(client: TestClient, celery_eager) -> None:
    job_id = seed_reviewed_txt_job()
    created = client.post(
        f"/api/v1/jobs/{job_id}/exports",
        json={"type": "modified_document"},
    )
    export_id = created.json()["export_id"]
    status = client.get(f"/api/v1/jobs/{job_id}/exports/{export_id}")
    download = client.get(f"/api/v1/jobs/{job_id}/exports/{export_id}/download")
    assert status.json()["status"] == "completed"
    assert download.status_code == 200
    assert download.content.decode("utf-8") == "修改后的正文\n"
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_export_task.py apps\api\tests\integration\test_export_api.py -v
```

Expected: FAIL because task and routes are absent.

- [ ] **Step 4: Implement asynchronous lifecycle**

POST validates terminal analysis, supported type, and decision availability; creates a queued export and dispatches `text_verification.process_export`. The task marks processing, builds replacements/report, writes to storage, and marks completed or failed with a safe structured message.

- [ ] **Step 5: Implement safe download and cleanup**

Download returns 409 until completed, 410 after expiry, and sets `Content-Disposition` with an RFC 5987 encoded filename. Cleanup removes export rows through job cascade and files through the existing job directory deletion.

- [ ] **Step 6: Run full backend and Docker build**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -v
& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api
& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src
docker compose -f infra\compose.yaml build api worker
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add apps\api\src apps\api\tests
git commit -m "feat: expose asynchronous document exports" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Phase Acceptance

Run the export API tests plus round-trip parser/export tests. Expected: TXT/DOCX modified files reopen with accepted safe replacements, PDF jobs produce reports only, and warnings describe every skipped change.
