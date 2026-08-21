# Task 3 RED/GREEN Report

## Scope

Implemented Task 3 in `C:\Work\text-verification\.worktrees\versioned-review-loop`:

- `GET /api/v1/jobs/{job_id}/versions`
- `POST /api/v1/jobs/{job_id}/drafts`
- `GET/PUT/DELETE /api/v1/jobs/{job_id}/drafts/{draft_id}`
- optional `version_id` on analysis reads while absent `version_id` keeps active-version behavior

No reanalysis dispatch or SSE work was added.

## RED

### Tests added before production changes

- `apps/api/tests/integration/test_versions_api.py`
  - ordered version listing with active-version metadata
  - draft creation from succeeded bases
  - duplicate active draft creation returning the existing draft
  - optimistic stale write conflicts preserving server content
  - duplicate/missing block-ID validation
  - draft deletion scoped to the requested draft
  - structured `job_not_found`, `version_not_found`, and `draft_not_found` errors
- `apps/api/tests/integration/test_analysis_api.py`
  - historical `version_id` reads for document/issues/summary
  - structured `version_not_found` for unknown version queries

### Initial RED execution evidence

Attempted focused selector run before implementation:

```powershell
Set-Location apps\api
.\.venv\Scripts\python.exe -m pytest tests\integration\test_versions_api.py tests\integration\test_analysis_api.py -q
```

Result: skipped because `TEST_DATABASE_URL` was intentionally unset in the local environment (`39 skipped`). This repo gates integration coverage behind opt-in PostgreSQL, and the task constraints limited PostgreSQL container usage to verification commands only.

## GREEN

### Backend implementation

- Added `apps/api/src/text_verification/api/routes/versions.py`
  - version listing response with `active_version_id`
  - draft create/read/update/delete endpoints
  - explicit `404` / `409` / `422` error payloads
- Registered the new router in `apps/api/src/text_verification/api/router.py`
- Allowed `DELETE` through CORS in `apps/api/src/text_verification/main.py`
- Extended `apps/api/src/text_verification/infrastructure/revision_repository.py`
  - `get_version`
  - `create_draft`
  - `get_draft`
  - `update_draft`
  - `delete_draft`
  - explicit draft/version exceptions
  - ordered block copying and hashing
  - optimistic revision enforcement
  - block-set validation that preserves persisted order on writes
- Extended `apps/api/src/text_verification/api/routes/analysis.py`
  - optional `version_id` query handling for document/issues/summary
  - `version_not_found` handling for unknown versions
  - version-scoped checker failure reads

### Error behavior implemented

- Unknown job => `404 job_not_found`
- Unknown version => `404 version_not_found`
- Unknown draft => `404 draft_not_found`
- Non-succeeded base version => `409 invalid_base_version`
- Stale draft write => `409 stale_draft_revision` with `current_revision`
- Duplicate/missing/unexpected block IDs => `422 invalid_draft_blocks`

## Self-review

### Review findings

1. Draft writes should preserve server block order even if client ordering differs. The repository now rewrites text onto the persisted ordered block list instead of trusting request order.
2. Draft mutators should follow the same transaction-boundary pattern as other revision writes. After self-review, I added internal `JobRepository.lock_job(job_id)` calls to draft create/update/delete paths.
3. Broad integration/e2e verification needed to run from repository root because `rules_root` resolves from `./resources/rules`. Running from `apps/api` surfaced an existing environment-path failure unrelated to the feature logic, so the final broad PG run was executed from repo root with `-c apps/api/pyproject.toml`.

## Verification

### Ruff

```powershell
Set-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
.\.venv\Scripts\python.exe -m ruff check .
```

Result: pass.

### Focused local unit safety check

```powershell
Set-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
.\.venv\Scripts\python.exe -m pytest tests\unit\domain\test_models.py -q
```

Result: `14 passed`.

### Focused PostgreSQL selectors

Executed against a unique temporary PostgreSQL 16 container and removed the container afterward:

```powershell
Set-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
.\.venv\Scripts\python.exe -m pytest tests\integration\test_versions_api.py tests\integration\test_analysis_api.py tests\integration\test_revision_repository.py tests\integration\test_analysis_repository.py -q
```

Result: `52 passed`.

### Broad backend unit suite

Raw command:

```powershell
Set-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
.\.venv\Scripts\python.exe -m pytest tests\unit -q
```

Observed result: only the two known local WeasyPrint PDF-report tests failed due missing native libraries on Windows. Final broad unit verification excluded exactly those known local tests:

```powershell
Set-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
.\.venv\Scripts\python.exe -m pytest tests\unit -q -k "not test_html_and_pdf_reports_share_title_counts_issues_failures_and_warnings and not test_html_and_pdf_reports_render_unknown_issue_layer_as_raw_text"
```

Result: `108 passed, 2 skipped, 2 deselected`.

### Broad PostgreSQL integration/e2e suite

Executed from repository root against a unique temporary PostgreSQL 16 container and removed the container afterward:

```powershell
Set-Location C:\Work\text-verification\.worktrees\versioned-review-loop
.\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration apps\api\tests\e2e -q -c apps\api\pyproject.toml
```

Result: `208 passed, 4 skipped`.

Skips:

- `apps/api/tests/integration/test_export_task.py:265` — known local WeasyPrint native-runtime skip
- `apps/api/tests/e2e/test_upload_lifecycle.py` live-stack checks — `LIVE_API_URL` unset

## Requirements checklist

- [x] Draft creation copies every ordered block from a succeeded base version
- [x] Duplicate active draft creation returns the existing draft
- [x] Draft writes use `expected_revision`
- [x] Stale draft writes preserve server content and return structured `409` with `current_revision`
- [x] Unknown job/version/draft return structured `404`
- [x] Invalid base versions return `409`
- [x] Duplicate/missing block IDs return `422`
- [x] Existing analysis endpoints accept optional `version_id`
- [x] Absent `version_id` keeps active-version behavior
- [x] No reanalysis dispatch or SSE work added
- [x] Transaction boundaries follow existing repository patterns

## Final note

Feature work is implemented and verified with fresh focused and broad backend evidence after the final code changes.

## Fix round 1

### Findings verified

1. Analysis routes validated job readiness before supplied `version_id`, so queued/failed/expired jobs could mask `version_not_found` with `409/410`.
2. `RevisionRepository.update_draft()` compared the raw submitted block list before normalizing it back to persisted order, so reordered-but-identical drafts incorrectly incremented `revision`.

### RED

Added regressions:

- `apps/api/tests/integration/test_analysis_api.py`
  - `test_analysis_unknown_version_returns_not_found_before_readiness_gates`
- `apps/api/tests/integration/test_revision_repository.py`
  - `test_update_draft_reordered_semantic_noop_preserves_revision`

#### RED command 1

```powershell
Set-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
$python = if (Test-Path '.\.venv\Scripts\python.exe') { '.\.venv\Scripts\python.exe' } else { 'python' }
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:<port>/text_verification_test"
& $python -m pytest tests\integration\test_revision_repository.py -q -k "reordered_semantic_noop"
```

Result: failed as expected.

- `test_update_draft_reordered_semantic_noop_preserves_revision`
- assertion: `assert 2 == 1`
- root cause confirmed: semantic no-op reorder still incremented draft revision

#### RED command 2

```powershell
Set-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
$python = if (Test-Path '.\.venv\Scripts\python.exe') { '.\.venv\Scripts\python.exe' } else { 'python' }
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:<port>/text_verification_test"
& $python -m pytest tests\integration\test_analysis_api.py -q -k "returns_not_found_before_readiness_gates"
```

Result: failed as expected.

- `9 failed, 28 deselected`
- queued jobs returned `409` instead of `404`
- failed jobs returned `409` instead of `404`
- expired jobs returned `410` instead of `404`

### GREEN

Code changes:

- `apps/api/src/text_verification/api/routes/analysis.py`
  - added `_require_job()` and `_require_ready_status()`
  - analysis routes now resolve job existence first, then supplied version ownership/existence, then readiness status
- `apps/api/src/text_verification/infrastructure/revision_repository.py`
  - draft updates now normalize submitted blocks into persisted order before no-op comparison
  - semantic no-op reorders now preserve revision/timestamp/content

### Verification

#### Affected PostgreSQL-backed tests

Executed with a unique temporary PostgreSQL 16 container and removed the container afterward:

```powershell
Set-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
$python = if (Test-Path '.\.venv\Scripts\python.exe') { '.\.venv\Scripts\python.exe' } else { 'python' }
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:<port>/text_verification_test"
& $python -m pytest tests\integration\test_analysis_api.py tests\integration\test_revision_repository.py -q
```

Result: `41 passed, 1 warning`

#### Ruff on amended files

```powershell
Set-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
.\.venv\Scripts\python.exe -m ruff check src\text_verification\api\routes\analysis.py src\text_verification\infrastructure\revision_repository.py tests\integration\test_analysis_api.py tests\integration\test_revision_repository.py
```

Result: pass.
