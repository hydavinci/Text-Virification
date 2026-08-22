# Task 5 Report

## Status

Implemented suggestions plus atomic, reversible review operation batches.

Implementation commit: `5ebb9c3429ea433b426db5e3c7fa262ce808c60f`

## TDD Evidence

### Baseline

With an explicit `postgres:16` container (`text-verification-task5`), the pre-change
decision selectors passed:

```powershell
Push-Location apps\api
$env:TEST_DATABASE_URL = "******127.0.0.1:57228/text_verification_test"
& .\.venv\Scripts\python.exe -m pytest `
  tests\integration\test_decision_api.py `
  tests\integration\test_decision_repository.py -q
Pop-Location
```

Result: `27 passed, 1 warning`.

### RED

Replaced partial-success expectations and added history/undo coverage before production
changes:

```powershell
Push-Location apps\api
$env:TEST_DATABASE_URL = "******127.0.0.1:57228/text_verification_test"
& .\.venv\Scripts\python.exe -m pytest `
  tests\integration\test_decision_api.py `
  tests\integration\test_review_history_api.py -q
Pop-Location
```

Observed result: `13 failed, 8 passed, 1 warning`. Failures were for missing batch IDs,
partial stale/missing success, absent suggestions/history routes, unsupported unreviewed
deletion, overlap acceptance, and missing undo behavior.

Additional focused RED cycles proved:

- snapshots lacked complete decision values and operation batch IDs;
- unreviewed commands without a current decision were incorrectly accepted;
- nested overlapping ranges omitted one structured conflict ID;
- undo could restore an accepted decision that overlapped a newer accepted decision.

Each focused regression failed for the intended missing behavior before its fix.

## Implementation

### Ordered suggestions

- Analysis persistence now writes `issue.suggestion` followed by unique alternatives as
  ordered `IssueSuggestionRow` records.
- The first candidate is preferred, candidates use the legacy `rule` source, and legacy
  issue columns remain intact.
- Issue list and export repository reads hydrate ordered `suggestions`.
- Accepted decisions may use a candidate ID with edited replacement text; the final
  replacement is stored verbatim.
- Candidate IDs are rejected atomically unless they belong to the commanded issue.

### Atomic decision batches

- Added `ReviewOperationRepository`.
- Each batch locks the job, requested issues ordered by UUID, then current decisions
  ordered by UUID.
- All issue versions, expected decision revisions, suggestion ownership, deletion
  validity, and final accepted-range overlap are preflighted before writes.
- Existing accepted decisions participate in overlap checks.
- Any stale, missing, invalid, or overlapping item rejects the whole batch.
- Successful responses return `{batch_id, outcomes}` in request order.
- Accepted and ignored decisions increment revision; unreviewed deletes an existing
  decision through a recorded batch.
- Full before/after snapshots include decision identity, version/job IDs, revision,
  action, replacement fields, suggestion ID, operation batch ID, and timestamp.

### History and undo

- Added version-scoped, newest-first
  `GET /api/v1/jobs/{job_id}/operation-batches`.
- Added `POST /api/v1/jobs/{job_id}/operation-batches/{batch_id}/undo`.
- Undo is a new operation batch with `undoes_batch_id`.
- Undo locks the original batch, sorted affected issues, operation items, and sorted
  decisions.
- Current full snapshots must equal the original after snapshots.
- Undo restores prior values or deletes rows atomically and records actual post-undo
  snapshots with the new batch ID.
- Undo also preflights restored accepted ranges against current decisions.
- Conflicts return structured issue IDs.

## Self-review

Self-review found and fixed:

1. Snapshot payloads initially omitted decision identity, operation batch ID, and
   timestamps.
2. Unreviewed-without-current-decision produced a no-op operation instead of an atomic
   conflict.
3. Adjacent-only overlap detection missed nested ranges; the sweep now reports every
   involved issue.
4. Undo overlap needed separate preflight before restoring prior accepted decisions.
5. Undo lock acquisition was aligned to job, original batch, sorted issues/items, then
   sorted decisions.

`git diff --check` passed before commit.

## Verification

### Required decision/history/concurrency selectors

```powershell
Push-Location apps\api
$env:TEST_DATABASE_URL = "******127.0.0.1:57228/text_verification_test"
& .\.venv\Scripts\python.exe -m pytest `
  tests\integration\test_decision_api.py `
  tests\integration\test_decision_repository.py `
  tests\integration\test_review_history_api.py -q
Pop-Location
```

Result: `44 passed, 1 warning in 11.60s`.

This includes reversed concurrent batches without deadlock and batch/reanalysis
serialization.

### Ruff

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m ruff check src tests
Pop-Location
```

Result: `All checks passed!`

### Focused mypy

```powershell
Push-Location apps\api
& .\.venv\Scripts\python.exe -m mypy `
  src\text_verification\domain\issues.py `
  src\text_verification\infrastructure\analysis_repositories.py `
  src\text_verification\infrastructure\review_operation_repository.py `
  src\text_verification\infrastructure\decision_repository.py `
  src\text_verification\api\routes\decisions.py `
  src\text_verification\api\routes\review_history.py
Pop-Location
```

Result: `Success: no issues found in 6 source files`.

### Analysis/export regressions

Result: `101 passed, 1 skipped, 1 warning`.

### Broad backend

```powershell
Push-Location apps\api
$env:TEST_DATABASE_URL = "******127.0.0.1:57228/text_verification_test"
& .\.venv\Scripts\python.exe -m pytest -q `
  -k 'not test_html_and_pdf_reports_share_title_counts_issues_failures_and_warnings and not test_html_and_pdf_reports_render_unknown_issue_layer_as_raw_text'
Pop-Location
```

Result: `362 passed, 6 skipped, 2 deselected, 1 warning in 48.94s`.

The only manual exclusions were the two known local WeasyPrint native-library tests.
Skips were the existing live-Compose, Docker WeasyPrint integration, and Windows symlink
environment skips.

## Concerns

- FastAPI TestClient emits the existing Starlette/httpx deprecation warning.
- The two known Windows-local WeasyPrint tests remain excluded as instructed.
- No Task 5 functional concerns remain.
