# Advanced Document Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect scanned and mixed PDF OCR, layout/table/image extraction, and structured DOCX reconstruction to the unified verification workflow.

**Architecture:** Port the source snapshot algorithms behind typed parser and exporter interfaces, replace broad exception swallowing with capability errors, and represent extracted layout in canonical document blocks. OCR remains lazy-loaded so non-OCR workflows do not initialize models.

**Tech Stack:** Python 3.12, PyMuPDF, pdfplumber, python-docx, RapidOCR 3, NumPy 2, OpenCV headless 4, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-translation-pre-checker-integration-design.md`

## Global Constraints

- Complete the canonical-model and unified-pipeline plans first.
- Preserve usable PDF text layers and OCR only pages that require OCR.
- Keep OCR imports lazy.
- Return explicit OCR capability errors for scanned documents when dependencies
  or models are unavailable.
- Preserve page order and structural source locators.
- Never silently discard failed PDF text insertion or reconstruction errors.

---

### Task 1: Add optional OCR dependencies and capability errors

**Files:**
- Modify: `apps/api/pyproject.toml`
- Create: `apps/api/src/text_verification/document_processing/errors.py`
- Create: `apps/api/src/text_verification/document_processing/ocr_provider.py`
- Test: `apps/api/tests/unit/document_processing/test_ocr_provider.py`
- Modify: `apps/api/Dockerfile`

**Interfaces:**
- Produces: optional dependency group `ocr`.
- Produces: `OcrProvider.recognize(image, language) -> list[OcrTextBox]`.
- Produces: `OcrUnavailableError`.

- [ ] **Step 1: Write a failing lazy-load test**

```python
def test_provider_does_not_import_rapidocr_until_recognition(monkeypatch):
    imported = []
    monkeypatch.setattr(importlib, "import_module", lambda name: imported.append(name))
    OcrProvider()
    assert imported == []
```

Add a test that converts an import failure into `OcrUnavailableError` with
stage `ocr` and `retryable=False`.

- [ ] **Step 2: Run the provider tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/document_processing/test_ocr_provider.py -v
```

Expected: FAIL because the provider does not exist.

- [ ] **Step 3: Add dependency group and provider**

Add:

```toml
ocr = [
  "numpy>=2,<3",
  "opencv-python-headless>=4.10,<5",
  "rapidocr>=3,<4",
]
```

Use `importlib.import_module("rapidocr")` inside engine creation. Cache one
engine per supported language and normalize provider output into typed
`OcrTextBox(text, confidence, bbox)`.

Install `apps/api[ocr]` in the API/worker Docker image.

- [ ] **Step 4: Run unit tests and package checks**

Run:

```bash
cd apps/api
python -m pytest tests/unit/document_processing/test_ocr_provider.py -v
python -m ruff check src/text_verification/document_processing
python -m mypy src/text_verification/document_processing
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/pyproject.toml apps/api/Dockerfile apps/api/src/text_verification/document_processing apps/api/tests/unit/document_processing
git commit -m "feat: add lazy OCR provider"
```

### Task 2: Implement typed PDF page classification and extraction

**Files:**
- Create: `apps/api/src/text_verification/document_processing/pdf_models.py`
- Create: `apps/api/src/text_verification/document_processing/pdf_classifier.py`
- Create: `apps/api/src/text_verification/parsers/pdf_parser.py`
- Test: `apps/api/tests/unit/document_processing/test_pdf_classifier.py`
- Test: `apps/api/tests/integration/test_pdf_parser.py`
- Create: `apps/api/tests/fixtures/pdf/text-page.pdf`
- Create: `apps/api/tests/fixtures/pdf/scanned-page.pdf`
- Create: `apps/api/tests/fixtures/pdf/mixed-pages.pdf`

**Interfaces:**
- Produces: `PdfPageKind.TEXT`, `SCANNED`, and `MIXED`.
- Produces: `PdfParser.parse(path) -> DocumentModel`.

- [ ] **Step 1: Write page-classification tests**

```python
@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("text-page.pdf", [PdfPageKind.TEXT]),
        ("scanned-page.pdf", [PdfPageKind.SCANNED]),
        ("mixed-pages.pdf", [PdfPageKind.TEXT, PdfPageKind.SCANNED]),
    ],
)
def test_classifies_each_page(pdf_fixture, fixture, expected):
    assert classify_pages(pdf_fixture(fixture)) == expected
```

- [ ] **Step 2: Run classifier tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/document_processing/test_pdf_classifier.py -v
```

Expected: FAIL with missing classifier.

- [ ] **Step 3: Implement classification and text extraction**

Classify per page using extracted text length and image coverage rather than one
document-wide sample. Extract spans, font metadata, tables, image blocks, and
bounding boxes with PyMuPDF. Preserve page number and vertical ordering in
`source_locator`.

Do not catch all exceptions. Catch only the documented PyMuPDF table/image
exceptions and convert them to extraction warnings attached to result metadata.

- [ ] **Step 4: Run PDF tests**

Run:

```bash
cd apps/api
python -m pytest tests/unit/document_processing/test_pdf_classifier.py tests/integration/test_pdf_parser.py -v
```

Expected: PASS for text pages; scanned pages report that OCR is required.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/document_processing apps/api/src/text_verification/parsers/pdf_parser.py apps/api/tests
git commit -m "feat: classify and extract structured PDF pages"
```

### Task 3: OCR scanned and mixed pages into canonical blocks

**Files:**
- Create: `apps/api/src/text_verification/document_processing/layout.py`
- Modify: `apps/api/src/text_verification/parsers/pdf_parser.py`
- Test: `apps/api/tests/integration/test_pdf_ocr.py`
- Create: `apps/api/tests/fixtures/pdf/scanned-table.pdf`

**Interfaces:**
- Consumes: `OcrProvider`.
- Produces: ordered paragraph, heading, table-cell, and image blocks.

- [ ] **Step 1: Write failing OCR integration tests with a deterministic fake**

```python
def test_mixed_pdf_uses_text_layer_and_ocr_in_page_order(fake_ocr, mixed_pdf):
    document = PdfParser(ocr=fake_ocr).parse(mixed_pdf)
    assert [block.page for block in document.blocks] == [1, 2]
    assert document.text == "text layer\nocr text"
    assert fake_ocr.pages == [2]
```

Add a scanned-table case that asserts row and cell indices on table-cell blocks.

- [ ] **Step 2: Run OCR integration tests**

Run:

```bash
cd apps/api
python -m pytest tests/integration/test_pdf_ocr.py -v
```

Expected: FAIL because scanned pages are not OCR processed.

- [ ] **Step 3: Port and type the layout algorithm**

Port the source `TextBox` and `DocElement` concepts into Pydantic/dataclass
models under `document_processing`. Normalize OCR boxes, group lines by
vertical overlap, classify headings by relative size, and identify table cells
using aligned row/column geometry.

Build canonical blocks in page and vertical order. Store bbox, confidence, page,
table, row, and cell metadata.

- [ ] **Step 4: Run OCR and parser tests**

Run:

```bash
cd apps/api
python -m pytest tests/integration/test_pdf_parser.py tests/integration/test_pdf_ocr.py -v
python -m ruff check src/text_verification/document_processing src/text_verification/parsers/pdf_parser.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/document_processing apps/api/src/text_verification/parsers/pdf_parser.py apps/api/tests
git commit -m "feat: OCR scanned PDF pages"
```

### Task 4: Add structured DOCX reconstruction

**Files:**
- Create: `apps/api/src/text_verification/exporters/docx_reconstruction.py`
- Modify: `apps/api/src/text_verification/exporters/registry.py`
- Test: `apps/api/tests/integration/test_docx_reconstruction.py`

**Interfaces:**
- Produces: `DocxReconstructionExporter.export(document, target) -> Path`.
- Consumes: heading, paragraph, table-cell, and image blocks.

- [ ] **Step 1: Write a failing reconstruction test**

```python
def test_reconstructs_heading_table_and_image(document_with_layout, tmp_path):
    target = DocxReconstructionExporter().export(
        document_with_layout,
        tmp_path / "rebuilt.docx",
    )
    doc = Document(target)
    assert doc.paragraphs[0].style.name.startswith("Heading")
    assert doc.tables[0].cell(0, 0).text == "名称"
    assert len(doc.inline_shapes) == 1
```

- [ ] **Step 2: Run the reconstruction test**

Run:

```bash
cd apps/api
python -m pytest tests/integration/test_docx_reconstruction.py -v
```

Expected: FAIL because the exporter is missing.

- [ ] **Step 3: Implement reconstruction**

Port the source Word builder behind the exporter interface. Preserve heading
levels, paragraph line breaks, estimated font sizes, table dimensions, image
bytes, East Asian fonts, page margins, and source title metadata.

Raise `ExportError` for invalid image data or inconsistent table shapes instead
of skipping them.

- [ ] **Step 4: Run reconstruction and export tests**

Run:

```bash
cd apps/api
python -m pytest tests/integration/test_docx_reconstruction.py tests/integration/test_compatibility_api.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src/text_verification/exporters apps/api/tests/integration/test_docx_reconstruction.py
git commit -m "feat: reconstruct structured documents as DOCX"
```

### Task 5: Connect advanced PDF processing to jobs and golden tests

**Files:**
- Modify: `apps/api/src/text_verification/application/factory.py`
- Modify: `apps/api/src/text_verification/domain/jobs.py`
- Modify: `apps/api/src/text_verification/workers/pipeline.py`
- Modify: `apps/api/src/text_verification/api/routes/jobs.py`
- Create: `apps/api/tests/e2e/test_scanned_pdf_lifecycle.py`
- Create: `apps/api/tests/golden/test_document_formats.py`

**Interfaces:**
- Produces: real OCR progress events.
- Produces: reconstructed DOCX export for OCR-derived documents.

- [ ] **Step 1: Write failing golden and lifecycle tests**

```python
def test_scanned_pdf_job_reports_ocr_and_returns_issues(live_client, scanned_pdf):
    job = upload(live_client, scanned_pdf)
    events = collect_events(live_client, job["job_id"])
    assert "ocr" in [event["stage"] for event in events]
    result = live_client.get(f"/api/v1/jobs/{job['job_id']}/result").json()
    assert result["text"]
    assert result["issues"]
```

- [ ] **Step 2: Run targeted tests**

Run:

```bash
cd apps/api
python -m pytest tests/golden/test_document_formats.py tests/e2e/test_scanned_pdf_lifecycle.py -v
```

Expected: FAIL because the default factory does not register the advanced PDF
parser and OCR job stages.

- [ ] **Step 3: Register advanced capabilities**

Register `PdfParser(OcrProvider())`, add an OCR job status/event, and expose
reconstruction as an export option for documents whose structure came from OCR.

- [ ] **Step 4: Run advanced-document verification**

Run:

```bash
cd apps/api
python -m pytest tests/unit/document_processing tests/integration/test_pdf_parser.py tests/integration/test_pdf_ocr.py tests/integration/test_docx_reconstruction.py tests/golden -v
python -m ruff check src tests
python -m mypy src
```

Expected: PASS. Run the live E2E test when the Compose stack is available.

- [ ] **Step 5: Commit**

```bash
git add apps/api/src apps/api/tests apps/api/pyproject.toml apps/api/Dockerfile
git commit -m "feat: connect OCR document processing workflow"
```

