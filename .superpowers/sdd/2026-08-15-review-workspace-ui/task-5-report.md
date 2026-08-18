# Task 5 Report

## Status

- Implemented bounded batch accept/ignore actions for the currently loaded filtered issues with a 500-item cap and high-risk security acceptance confirmation.
- Implemented local code-point-safe document find navigation and replace-all that submits custom decision commands instead of mutating raw `DocumentBlock.text`.
- Preserved `useReviewWorkspace` ownership of loaded pages, filtered loaded issues, selection, optimistic decisions, per-issue failed retry state, stale-response guards, and server-authoritative reconciliation.
- Left unrelated dirty `apps/web/src/App.vue` and `apps/web/src/components/JobProgress.vue` untouched and unstaged.

## Files

- Added `apps/web/src/components/review/BatchActions.vue`
- Added `apps/web/src/components/review/FindReplace.vue`
- Updated `apps/web/src/composables/useReviewWorkspace.ts`
- Updated `apps/web/src/components/review/ReviewToolbar.vue`
- Updated `apps/web/src/components/review/ReviewNavigation.vue`
- Updated `apps/web/src/components/review/DocumentViewer.vue`
- Updated `apps/web/src/views/ReviewWorkspaceView.vue`
- Updated `apps/web/tests/ReviewWorkspace.spec.ts`
- Added `.superpowers/sdd/2026-08-15-review-workspace-ui/task-5-report.md`

## RED

- Added focused tests before production changes for mixed batch outcomes, high-risk security confirmation, 500-item batch capping, code-point-safe find navigation, and replace-all decision submission.
- Command: `Set-Location C:\Work\text-verification\apps\web; npm test -- --run tests/ReviewWorkspace.spec.ts`
- Result: expected RED; 30 tests ran with 5 failures because the Task 5 controls and behavior were absent.
- Failure evidence:
  - `Error: Unable to get button[name="accept-visible"]`
  - `Error: Unable to get [aria-label="查找内容"]`

## GREEN

- Command: `Set-Location C:\Work\text-verification\apps\web; npm test -- --run tests/ReviewWorkspace.spec.ts`
- Result: GREEN; 1 test file passed with 30 tests passed.
- Command: `Set-Location C:\Work\text-verification\apps\web; npm run build`
- Result: GREEN; `vue-tsc -b && vite build` passed, Vite transformed 54 modules, and production assets were emitted to `dist/`.

## Commit

- Message: `feat: add batch review and document search`
- Trailer: `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`
- The final commit hash is returned in the CLI response.

## Self-review

- Confirmed batch actions submit only the currently loaded filtered issues, cap the submission at 500 commands, and announce mixed outcomes as `成功 X 项，需重新确认 Y 项`.
- Confirmed accepting visible high-risk security issues requires explicit confirmation before request dispatch.
- Confirmed issue cards now expose review state labels so applied outcomes show `已接受` and conflicted outcomes show `需重新确认`.
- Confirmed find matching walks loaded block text with `Array.from(...)` code-point boundaries, so emoji-adjacent matches count and navigate correctly.
- Confirmed replace-all is enabled only when every loaded match maps exactly to one auto-fixable issue and submits custom decision commands without mutating raw document text.
- Confirmed the focused review test file and production build both pass after the implementation and refactor loop.

## Concerns

- None.

## Fix Round 1

### Finding 1: Batch conflict/invalid outcomes now reload authoritative issue + summary state

- Root cause: `submitDecisionBatch()` handled non-applied outcomes locally, announced counts, and only refreshed the summary; the current filtered issue page stayed stale.
- RED command: `Set-Location C:\Work\text-verification\apps\web; npm test -- --run tests/ReviewWorkspace.spec.ts`
- RED output:
  - `FAIL ReviewWorkspaceView > reconciles batch conflict and invalid outcomes with authoritative issue state`
  - `expected "spy" to be called 2 times, but got 1 times`
- GREEN command: `Set-Location C:\Work\text-verification\apps\web; npm test -- --run tests/ReviewWorkspace.spec.ts`
- GREEN output:
  - `✓ tests/ReviewWorkspace.spec.ts (32 tests)`
  - `Tests 32 passed (32)`
- Files:
  - `apps/web/src/composables/useReviewWorkspace.ts`
  - `apps/web/tests/ReviewWorkspace.spec.ts`

### Finding 2: Filter/search transitions no longer leave stale visible issues batch-actionable

- Root cause: `setFilters()` cleared selection and cursors but preserved the previously loaded issue set until the replacement request resolved, so batch actions still targeted stale visible issues.
- RED command: `Set-Location C:\Work\text-verification\apps\web; npm test -- --run tests/ReviewWorkspace.spec.ts`
- RED output:
  - `FAIL ReviewWorkspaceView > does not submit stale visible issues while a filter request is in flight`
  - `expected undefined to be defined`
- GREEN command: `Set-Location C:\Work\text-verification\apps\web; npm test -- --run tests/ReviewWorkspace.spec.ts`
- GREEN output:
  - `✓ tests/ReviewWorkspace.spec.ts (32 tests)`
  - `Tests 32 passed (32)`
- Files:
  - `apps/web/src/composables/useReviewWorkspace.ts`
  - `apps/web/tests/ReviewWorkspace.spec.ts`

### Finding 3: Missing `confirm` no longer implicitly approves high-risk batch acceptance

- Root cause: `BatchActions.vue` used `globalThis.confirm?.(...) ?? true`, which treated unavailable confirmation infrastructure as approval.
- RED command: `Set-Location C:\Work\text-verification\apps\web; npm test -- --run tests/ReviewWorkspace.spec.ts`
- RED output:
  - `FAIL ReviewWorkspaceView > rejects high-risk batch acceptance when confirm is unavailable`
  - `expected "spy" to not be called at all, but actually been called 1 times`
- GREEN command: `Set-Location C:\Work\text-verification\apps\web; npm test -- --run tests/ReviewWorkspace.spec.ts`
- GREEN output:
  - `✓ tests/ReviewWorkspace.spec.ts (32 tests)`
  - `Tests 32 passed (32)`
- Files:
  - `apps/web/src/components/review/BatchActions.vue`
  - `apps/web/tests/ReviewWorkspace.spec.ts`

### Minor: Removed unused `visibleIssueOverflow` plumbing

- Safe mechanical removal completed; no deferral needed.
- Files:
  - `apps/web/src/composables/useReviewWorkspace.ts`
  - `apps/web/src/components/review/ReviewToolbar.vue`
  - `apps/web/src/views/ReviewWorkspaceView.vue`

### Validation

- Focused spec: `Set-Location C:\Work\text-verification\apps\web; npm test -- --run tests/ReviewWorkspace.spec.ts`
  - Output: `✓ tests/ReviewWorkspace.spec.ts (32 tests)` / `Tests 32 passed (32)`
- Production build: `Set-Location C:\Work\text-verification\apps\web; npm run build`
  - Output: `vue-tsc -b && vite build` / `✓ built in 964ms`

### Self-review

- Batch non-applied outcomes now reuse guarded issue reloads instead of exposing retry metadata for known-stale commands; per-issue retries remain limited to infrastructure failures.
- Filter-driven issue invalidation prevents stale batch submissions without changing the 500-item cap, loaded-page find behavior, replace-all issue mapping, or raw document text immutability.
- High-risk batch acceptance now fails closed when `confirm` is unavailable, and the focused spec plus production build both passed after the fixes.
