# Task 2 Report

## Status

- Implemented pre-upload scenario and checker-category configuration on top of the accepted upload/progress baseline.
- Preserved unrelated dirty `apps/web/src/App.vue` and `apps/web/src/components/JobProgress.vue` by leaving them untouched and unstaged.

## Files

- Added `apps/web/src/components/CheckOptions.vue`
- Updated `apps/web/src/components/UploadWorkspace.vue`
- Updated `apps/web/src/views/WorkspaceView.vue`
- Updated `apps/web/tests/WorkspaceView.spec.ts`

## RED

- Added two focused component tests first in `apps/web/tests/WorkspaceView.spec.ts`:
  - `uploads the selected scenario and categories with the file`
  - `rejects uploads when no check categories are selected`
- Ran `npm test -- tests/WorkspaceView.spec.ts` before implementation and observed RED:
  - missing `select[name="scenario"]`
  - missing `input[name="category-character"]`
  - existing uploads still called `createJob(file)` without options

## GREEN

- Added `CheckOptions.vue` and wired `UploadWorkspace` to emit file + options snapshots.
- Updated `WorkspaceView` to call `jobsApi.createJob(file, options)` while keeping the existing request-generation and subscription flow intact.
- Verification:
  - `npm test -- tests/WorkspaceView.spec.ts` → 15 passed
  - `npm run build` → passed

## Commit

- Message: `feat: configure document checks before upload`
- Final hash is returned after commit in the CLI response because amending this report changes the commit id.

## Self-review

- Confirmed the scenario select renders exactly `general`, `academic`, `business`, `legal`, `news`, and `technical`.
- Confirmed the checkbox names are exactly `category-character`, `category-vocabulary`, `category-sentence`, `category-format`, `category-discourse`, and `category-security`.
- Confirmed defaults are `general` plus all six categories, zero-category uploads are blocked with `role="alert"` and `至少选择一类检查`, and busy state disables the relevant upload controls.
- Confirmed the Task 2 diff is whitespace-clean with `git -c core.whitespace=cr-at-eol diff --check -- ...`.
- Rewrote the fixture categories array in `WorkspaceView.spec.ts`, clearing the deferred fixture-line whitespace issue as part of the test update.

## Concerns

- None.

## Review fix round 1/5 — preserve immutable upload options

### Status

- Fixed the review finding that upload options were only shallowly immutable before `createJob`.
- Left unrelated dirty files `apps/web/src/App.vue` and `apps/web/src/components/JobProgress.vue` untouched and unstaged.

### Files

- Updated `apps/web/src/types/jobs.ts`
- Updated `apps/web/src/components/UploadWorkspace.vue`
- Updated `apps/web/src/views/WorkspaceView.vue`
- Updated `apps/web/tests/WorkspaceView.spec.ts`

### RED

- Added `forwards the same frozen upload options snapshot to createJob` in `apps/web/tests/WorkspaceView.spec.ts`.
- Command: `npm test -- tests\WorkspaceView.spec.ts`
- Result: 1 failed / 15 passed. The new test failed because `Object.isFrozen(forwardedOptions)` was `false`, confirming `WorkspaceView` recreated mutable options before `createJob`.

### GREEN

- Changed `JobCreateOptions.enabledCategories` to readonly-compatible typing.
- Froze the emitted `enabledCategories` array in `UploadWorkspace.vue`.
- Removed the `WorkspaceView` clone so `jobsApi.createJob(file, options)` receives the original immutable snapshot.
- Command: `npm test -- tests\WorkspaceView.spec.ts tests\jobsApi.spec.ts`
- Result: 33 passed.

### Build

- Command: `npm run build`
- Result: passed.

### Self-review

- Confirmed the exact upload options snapshot emitted by `UploadWorkspace` now reaches `createJob` unchanged.
- Confirmed both the outer options object and nested `enabledCategories` array are frozen at runtime, with regression coverage.
- Confirmed readonly typing keeps `jobsApi` form serialization compatible and required no backend or dependency changes.

### Concerns

- None.
