# Translation Pre-Checker Capability Integration Design

**Date:** 2026-08-30  
**Status:** Approved for implementation planning

## 1. Purpose

Optimize `Text-Virification` by integrating every meaningful capability from
the `translation-pre-checker-all` source snapshot while preserving all current
`Text-Virification` capabilities.

The completed product remains the `Text-Virification` Vue/FastAPI monorepo.
The legacy Flask application, port 5088, legacy API paths, and legacy deployment
method are not compatibility requirements.

## 2. Approved Scope

### 2.1 Capabilities to preserve from `translation-pre-checker-all`

The migration includes both user-facing capabilities already connected to the
legacy application and advanced capabilities that are implemented but not
connected to its main workflow.

User-facing capabilities include:

- Direct text input and file upload.
- TXT, DOCX, DOC, PDF, RTF, Markdown, and CSV input.
- Drag-and-drop and file-picker upload.
- Chinese- and English-aware text counts.
- General, academic, business, legal, news, and technical scenarios.
- Independent PII, sensitive-language, and advertising-extreme-word switches.
- Custom terminology and banned-word editing.
- CSV, TXT, and TSV terminology and banned-word import.
- Terminology and banned-word example export.
- Six-layer rule analysis:
  - character;
  - vocabulary;
  - sentence;
  - punctuation and formatting;
  - discourse and register;
  - compliance and security.
- Optional OpenAI-compatible LLM review with local-rule fallback.
- Highlighted source text and sentence-oriented and continuous document views.
- Bidirectional navigation between source text and issue details.
- Alternative suggestions.
- Individual accept, reject, and undo actions.
- Batch accept, reject, and undo actions.
- Search, case-sensitive search, navigation, replace-current, and replace-all.
- Free editing and modified-text preview.
- Browser session recovery.
- Theme switching and privacy information.
- HTML report export.
- Original-format export and tracked-change or annotation modes where supported.

Advanced capabilities to make first-class include:

- Text, scanned, and mixed PDF classification.
- OCR of scanned PDF pages and images.
- PDF layout, table, and image-region extraction.
- Structured Word reconstruction from extracted document elements.

### 2.2 Capabilities to preserve from `Text-Virification`

- Vue 3 and TypeScript frontend.
- FastAPI application and versioned API.
- PostgreSQL job and event persistence.
- Redis and Celery background processing.
- SSE progress, replay, keepalive, completion, and expiration behavior.
- Celery retry, terminal-state protection, and failure persistence.
- Scheduled cleanup of expired database records and stored files.
- Strict upload-size, signature, archive, path, and filename validation.
- UUID-isolated storage.
- Existing seven-format parsing and original-format export.
- Existing six-layer rule behavior, scenario behavior, statistics, and LLM
  fallback.
- Docker Compose deployment with separate API, worker, beat, database, Redis,
  and web services.

### 2.3 Behavior not preserved

The integration preserves capabilities, not defects or obsolete implementation
details. It will not preserve:

- Flask-specific routes or deployment.
- Port 5088.
- Legacy dead code or inaccessible controls.
- Batch-review runtime failures.
- Deletion suggestions that fail to modify text.
- Free edits that cannot be exported.
- Shared report temporary filenames.
- Successful uploads that are never cleaned up.
- Silent PDF insertion failures.
- Silent dictionary-load failures.
- Known PII pattern omissions such as uppercase or lowercase `X` in valid
  Chinese identity numbers.
- UI behavior that relies on unstable issue-array indexes.

## 3. Architecture

The system will use one verification core, two execution modes, and one result
contract.

```text
Vue workspace
  |-- fast text checks ------------> FastAPI synchronous endpoint
  `-- files and expensive checks --> Job + Celery + SSE
                                            |
                                  VerificationPipeline
                                            |
                 +--------------------------+--------------------------+
                 |                          |                          |
          Parser Registry            Checker Registry          Exporter Registry
                 |                          |                          |
       Seven base formats          Six rule layers and LLM      Seven source formats
       PDF/OCR/layout parsing      Rule and dictionary versions HTML/tracked changes
                 |                          |                  Word reconstruction
                 +--------------------------+--------------------------+
                                            |
                                  DocumentModel + Issue
```

`Text-Virification` is the only product and repository. Existing compatibility
code is retained temporarily as a regression baseline and migrated
incrementally rather than deleted before equivalent behavior is proven.

The synchronous FastAPI route and asynchronous Celery worker call the same
application service. Transport and progress behavior differ, but parsing,
checking, LLM review, statistics, and result semantics do not.

## 4. Backend Components

### 4.1 Verification pipeline

Add an application-level `VerificationPipeline` responsible for:

1. Validating the request and resolving enabled capabilities.
2. Loading the source document or direct text.
3. Selecting a parser through the parser registry.
4. Creating the canonical `DocumentModel`.
5. Recording the verification run, configuration, rule version, and dictionary
   version.
6. Running enabled checkers in deterministic layer order.
7. Applying scenario filtering, severity adjustment, and deduplication.
8. Performing optional LLM review.
9. Calculating statistics and summaries.
10. Persisting results when the request belongs to a job.
11. Returning one canonical result contract.

The synchronous API and Celery pipeline must not duplicate these steps.

### 4.2 Parser registry

Each parser declares:

- supported file types;
- required external dependencies;
- whether it preserves blocks, pages, tables, images, and styles;
- whether OCR is supported or required;
- the parser implementation version.

The registry includes TXT, DOCX, DOC, PDF, RTF, Markdown, and CSV parsers.

The PDF parser classifies each page as text, scanned, or mixed. Text extraction
is preferred when a usable text layer exists. OCR is applied only to pages that
need it. Extracted text, tables, images, bounding boxes, and page order are
represented in `DocumentModel`.

If OCR dependencies are unavailable, text-based files and text-based PDF pages
continue to work. A scanned document that requires OCR fails with an explicit
capability error instead of returning an empty successful result.

### 4.3 Checker registry

The checker registry replaces the monolithic execution switch while preserving
the current deterministic ordering:

1. character;
2. vocabulary;
3. sentence;
4. punctuation and formatting;
5. discourse and register;
6. compliance and security.

Each checker declares:

- rule ID and version;
- layer;
- supported languages and document features;
- default severity;
- whether it is auto-fixable;
- configuration dependencies;
- scenario applicability.

Existing algorithms remain the initial behavior baseline. Previously
implemented but disconnected spacing and long-sentence checks become explicit
registered rules and are enabled only after their expected behavior is covered
by tests and documented in the capability manifest.

### 4.4 LLM review

LLM configuration moves into the central application settings model.

LLM review:

- receives only bounded issue context;
- skips deterministic rules that should not be overruled;
- records review outcome and reason;
- preserves local issues when the provider is unavailable, times out, or
  returns invalid output;
- never changes a failed call into a failed verification run;
- exposes whether a run used local-only or local-plus-LLM analysis.

### 4.5 Exporter registry

Exporters are registered by source file type and declared capability. They
support:

- HTML reports;
- DOCX ordinary edits and tracked changes;
- DOC conversion and restoration through supported conversion tools;
- PDF redaction/replacement and annotation mode;
- TXT, Markdown, and CSV replacement and textual change markers;
- RTF replacement and tracked-change representation;
- structured DOCX reconstruction from OCR and PDF elements.

Every export validates the source version, issue positions, original text
slices, review revision, and target format before writing output.

### 4.6 Unified storage

The existing asynchronous `JobStorage` and synchronous
`CompatibilityStorage` security behavior is consolidated behind one storage
interface and one shared validation core.

The unified implementation preserves:

- chunked writes and size limits;
- server-generated names;
- UUID directory isolation;
- archive expansion limits;
- DOCX required-entry and encryption checks;
- PDF, DOC, RTF, and text signature checks;
- canonical-path enforcement;
- safe deletion;
- expiration and orphan cleanup.

Supported formats are declared by the capability registry instead of being
hard-coded independently by storage, domain models, frontend components, and
API routes.

## 5. Canonical Data Model

### 5.1 Document model

Extend the existing domain `DocumentModel` and `TextBlock` rather than retaining
the compatibility tuple of flattened text, format name, and page map.

The canonical document representation includes:

- document and source version IDs;
- source filename and file type;
- normalized full text;
- ordered blocks;
- block type;
- global and block-local character offsets;
- page and paragraph identity;
- parent-child relationships;
- table, row, and cell identity;
- image and bounding-box metadata;
- style and source-location metadata;
- parser name and version.

Flattened text remains available as a derived view for rules that do not need
document structure.

### 5.2 Issue model

Replace the compatibility and domain issue split with one canonical Issue
model containing:

- stable `issue_id`;
- `document_id` and source version;
- `verification_run_id`;
- `block_id` where applicable;
- global start and end offsets;
- block-local start and end offsets where applicable;
- page or structural location;
- rule ID and rule version;
- layer, type, severity, and confidence;
- original text, recommended replacement, and alternatives;
- message, context, and explanation;
- auto-fixability;
- LLM review outcome and reason.

Legacy response fields can be generated by a temporary response mapper while
the frontend transitions. Array position is never an issue identity.

### 5.3 Persistence

Keep the existing `jobs` and `job_events` model and add persistence boundaries
for:

- documents and source versions;
- verification runs and their configuration;
- issues;
- review decisions;
- edited document revisions;
- export requests and artifacts;
- dictionary and rule-set versions where required for reproducibility.

The exact relational schema will be specified in the implementation plan.

## 6. Frontend Design

The Vue frontend is redesigned around focused components and composables while
preserving all approved interactions.

Proposed responsibilities:

- workspace shell and navigation;
- text and file input;
- upload and task progress;
- scenario and rule configuration;
- terminology and banned-word management;
- document view with sentence and continuous modes;
- issue list, details, filters, and navigation;
- review actions and batch operations;
- search and replace;
- free editing and modified-text preview;
- export configuration and download;
- session restoration, theme, help, and privacy content.

Workspace state is keyed by stable IDs:

- document ID;
- verification run ID;
- issue ID;
- document revision ID;
- export request ID.

The frontend consumes one result contract. For synchronous requests it receives
the result immediately. For asynchronous jobs it receives the same result after
SSE reports completion.

The redesigned UI must retain:

- text and file modes;
- drag-and-drop;
- keyboard submission;
- six-layer explanations;
- issue and compliance statistics;
- sentence and continuous views;
- source-to-issue and issue-to-source navigation;
- issue alternatives;
- individual and batch review;
- undo;
- severity and layer filtering;
- search and replace;
- free editing and preview;
- session restoration;
- terminology workflows;
- tracked-change selection;
- theme and privacy information.

Accessibility improvements include keyboard-operable upload, explicit labels,
focus-managed dialogs, visible focus states, live regions for progress and
notifications, and keyboard-operable application branding.

## 7. Execution Modes and Data Flow

### 7.1 Synchronous mode

Synchronous execution is reserved for direct text and requests below configured
complexity limits.

```text
request
  -> validation
  -> VerificationPipeline
  -> canonical verification result
  -> response
```

### 7.2 Asynchronous mode

File uploads, OCR, and expensive document processing use the job system.

```text
upload
  -> secure storage
  -> job and initial event
  -> Celery VerificationPipeline
  -> staged events
  -> persisted canonical result
  -> SSE completion
  -> frontend loads result
```

Job progress corresponds to real pipeline stages rather than placeholder state
changes. Retried work remains idempotent and terminal states cannot regress.

### 7.3 Review and export

```text
verification result
  -> issue decisions and free edits
  -> document revision
  -> validated export plan
  -> source-format mutation or structured reconstruction
  -> stored artifact
  -> download
```

Review decisions and edits reference a document revision. Exports against stale
source or review revisions fail explicitly.

## 8. Error Handling

Errors are stage-specific and safe to expose:

- upload validation;
- parser selection;
- document conversion;
- OCR capability;
- extraction;
- checker execution;
- dictionary loading;
- LLM provider;
- persistence;
- export validation;
- format mutation;
- artifact storage.

The application does not silently return empty success for unavailable
capabilities or invalid files. It does not swallow dictionary, OCR, or export
failures. Client-safe errors include a stable code, stage, message, retryability
indicator, and correlation ID.

LLM failure is the intentional exception: it degrades to local-rule results and
records the degraded mode because LLM review is optional.

Temporary and successful source files, generated reports, and export artifacts
follow explicit retention policies and are cleaned by the existing scheduled
cleanup mechanism.

## 9. Migration Strategy

Implementation is divided into four independently shippable stages.

### Stage 1: Compatibility baseline and canonical models

- Convert the source capability inventory into automated behavior contracts.
- Add regression tests for known defects before fixing them.
- Define the canonical document, issue, configuration, result, and capability
  models.
- Add response adapters so existing endpoints and UI continue to work.
- Centralize LLM configuration and file-type capability declarations.

### Stage 2: Unified backend pipeline

- Introduce `VerificationPipeline`.
- Add parser, checker, and exporter registries.
- Consolidate storage validation and lifecycle behavior.
- Route synchronous analysis through the pipeline.
- Replace the Celery stub with the same pipeline.
- Persist verification results and expose them through the job API.
- Prove synchronous and asynchronous result equivalence.

### Stage 3: Advanced document processing

- Port and harden PDF classification and OCR.
- Preserve page order, tables, images, and layout metadata.
- Connect structured Word reconstruction.
- Add text, scanned, and mixed PDF golden fixtures.
- Complete original-format and reconstructed-document export coverage.

### Stage 4: Vue workspace redesign

- Split the page controller into focused components and composables.
- Move review state to stable issue IDs and persisted revisions.
- Implement complete individual and batch workflows.
- Preserve all source and target interactions.
- Add accessibility and responsive behavior.
- Remove temporary compatibility response adapters after all consumers migrate.

At the end of every stage, the application remains deployable and usable.

## 10. Testing Strategy

### 10.1 Source capability contracts

Create parameterized tests for:

- every current rule family and issue type;
- scenario filtering and severity behavior;
- PII, sensitive-language, and advertising switches;
- custom terminology and banned words;
- statistics;
- issue offsets, sorting, and deduplication;
- LLM false-positive, uncertain, real, timeout, and invalid-response behavior.

### 10.2 Document golden fixtures

Maintain representative fixtures for all seven formats. Each fixture validates:

- extracted text;
- document structure and offsets;
- issue location;
- ordinary replacement;
- deletion and insertion;
- tracked changes or annotation mode;
- output format validity.

PDF fixtures cover:

- text-only pages;
- scanned pages;
- mixed pages;
- tables;
- embedded images;
- multilingual text;
- reconstruction to DOCX.

### 10.3 Pipeline and infrastructure tests

- Synchronous and asynchronous execution produce equivalent canonical results.
- Celery retries are idempotent.
- Terminal state cannot regress.
- SSE replay and `Last-Event-ID` remain correct.
- Upload validation covers signatures, archives, paths, names, and size.
- Cleanup covers database rows, source files, intermediate files, reports, and
  export artifacts.
- PostgreSQL migrations and repository contracts use a real test database.

### 10.4 Frontend tests

Vitest and Vue Test Utils cover:

- upload and text input;
- scenario and rule configuration;
- terminology import, editing, deletion, and example export;
- synchronous and asynchronous result loading;
- document view modes;
- bidirectional navigation;
- filtering;
- individual and batch review;
- undo;
- search and replace;
- free edit and preview;
- session restoration;
- all export requests;
- progress, expiration, and recoverable errors.

Browser-level end-to-end tests cover the critical complete workflows for direct
text, ordinary document upload, scanned PDF OCR, review, and export.

### 10.5 Defect regression tests

Tests are written before fixes for:

- batch operation scope errors;
- deletion suggestions;
- free-edit export;
- report filename isolation;
- file retention cleanup;
- PDF insertion failure reporting;
- Chinese identity numbers ending in `X` or `x`;
- stale issue offsets and stale export revisions;
- dictionary load failures.

## 11. Acceptance Criteria

The integration is complete only when:

1. Every capability classified as implemented, limited, or implemented but
   disconnected in the source inventory has an accessible implementation and
   automated coverage.
2. All existing `Text-Virification` synchronous analysis, asynchronous jobs,
   SSE behavior, upload security, cleanup, and seven-format exports remain
   available.
3. Synchronous and asynchronous verification use one application pipeline and
   produce the same canonical result for the same input and configuration.
4. All seven document-format golden suites pass.
5. Text, scanned, and mixed PDF OCR and reconstruction suites pass.
6. Frontend production build, TypeScript checks, frontend tests, backend tests,
   Ruff, and mypy pass under the repository's supported environments.
7. There is one canonical Issue model.
8. There is one upload security and lifecycle implementation.
9. OCR, PDF layout processing, and Word reconstruction are connected to normal
   user workflows rather than left as isolated modules.
10. No known legacy defect listed in this design is intentionally retained.

## 12. Explicit Non-Goals

- Preserving the Flask server.
- Preserving port 5088.
- Preserving legacy API paths.
- Reproducing legacy runtime defects.
- Introducing authentication, multi-tenancy, billing, or collaborative editing
  unless separately designed.
- Replacing PostgreSQL, Redis, Celery, FastAPI, Vue, Vite, or the Compose
  deployment without a separate approved design.
