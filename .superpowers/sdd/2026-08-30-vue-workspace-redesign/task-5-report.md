# Task 5 report — unified verification execution

## Status

Completed on 2026-09-03 from base
`cd61497e860a528f70bd4fd0f4cd23552ceb0907`.

## Files

- Added `apps/web/src/composables/useVerificationExecution.ts`.
- Added focused execution-state tests.
- Added shared analyzed-options snapshot and API-error helpers.
- Updated the jobs API, job types, verification API, progress component, and
  `WorkspaceView`.
- Extended jobs, verification, and workspace integration regressions.

## Delivered behavior

- `useVerificationExecution` is the single execution state machine for direct
  text, direct synchronous files, and asynchronous file jobs. Its states are
  `idle`, `submitting`, `processing`, `completed`, `failed`, and `expired`.
- The composable owns the canonical execution result, job metadata, coarse job
  status, derived stage, progress, message, typed error, transient connection
  notice, request generation, submission lock, result-fetch idempotence, and
  subscription lifecycle.
- Direct text and direct file requests publish through the same completed
  result state without SSE. Asynchronous files submit the same frozen cloned
  `AnalyzeOptions` snapshot, subscribe to progress, and fetch
  `/jobs/{id}/result` exactly once after `completed` or `partial`.
- `completed` is published only after the retained canonical result has loaded.
  HTTP 410 and expired events map to `expired`; failed events and ordinary
  result-loading failures map to `failed`.
- Partial-success jobs load their retained result, remain execution-completed,
  preserve `jobStatus: "partial"` plus stage/progress/message metadata, and
  display the backend warning in the review workspace.
- Duplicate terminal events, late connection errors, stale create/result/direct
  promises, reset, scope disposal, and rapid duplicate text/file submissions
  are handled without duplicate API calls or stale publication.
- Job types now match all seven backend formats. Durable `JobStatus` remains
  coarse, while `JobProgressStage` separately includes OCR, finalizing, and
  exporting stages emitted by the backend.
- `JobsApi.createJob(file, options)` serializes the exact multipart option
  contract, preserving empty arrays and string values. Invalid snapshots fail
  before fetch; caller-owned objects cannot mutate the submitted snapshot.
- `JobsApi.getResult` returns `VerificationResult`.
  `JobResultExpiredError` distinguishes HTTP 410 from ordinary typed
  `ApiRequestError` failures. Direct verification and download methods use the
  same shaped error parser while retaining their existing method signatures.
- `WorkspaceView` no longer owns parallel request generations, subscriptions,
  job progress mutation, `runAnalysis`, or a mutable duplicate lock. A newly
  completed execution result is loaded once through
  `useVerificationWorkspace`, navigation/edit surfaces are reset, and the
  validated session is saved.
- Manual revision recheck remains text-sourced: the execution result is adapted
  before publication to preserve the display filename while clearing old
  `file_id` and `file_ext`.
- Existing strict atomic session restore, review/revision behavior, settings
  confirmation, progress UI, export gates, theme, privacy, and accessibility
  behavior remain covered.

## TDD and validation evidence

- Fresh baseline:
  `npm test -- --run --reporter=dot` passed 294 tests across 14 files.
- Initial execution/jobs RED:
  `npm test -- useVerificationExecution.spec.ts jobsApi.spec.ts --reporter=dot`
  failed both suites because the composable did not exist and the new backend
  file-format constants were absent.
- Jobs contract RED:
  `npm test -- jobsApi.spec.ts --reporter=dot` failed 16 tests with 12 passing.
  Failures covered omitted multipart options, missing `getResult`, missing
  typed 410 handling, absent stage parsing, and three-format-only job types.
- Verification error RED:
  `npm test -- verificationApi.spec.ts --reporter=dot` failed 1 test with 4
  passing because direct analysis still returned an untyped `Error`.
- Workspace integration RED:
  `npm test -- WorkspaceView.spec.ts --reporter=dot` failed 1 test with 37
  passing because asynchronous uploads omitted options and never loaded the
  canonical result.
- Additional focused RED runs reproduced missing partial-warning display,
  missing progress-stage display, null options raising `TypeError`, and a stale
  direct-result transform running after reset.
- Final focused GREEN:
  `npm test -- useVerificationExecution.spec.ts jobsApi.spec.ts verificationApi.spec.ts WorkspaceView.spec.ts --reporter=dot`
  passed 92 tests across 4 files.
- Full frontend GREEN:
  `npm test -- --run --reporter=dot` passed 330 tests across 15 files. Node
  emitted the existing experimental `localStorage` warning.
- Production build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3
  with 56 modules transformed.
- `git diff --check` passed with no output.

## Scope

No Task 6 revision persistence or asynchronous export backend API was added.
