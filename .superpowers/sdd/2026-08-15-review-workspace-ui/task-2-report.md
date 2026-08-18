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
