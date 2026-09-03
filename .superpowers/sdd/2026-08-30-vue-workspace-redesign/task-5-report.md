# Task 5 report — unified verification execution

## Status

Completed on 2026-09-03 from base
`cd61497e860a528f70bd4fd0f4cd23552ceb0907`.

Review fix round 1 was implemented on 2026-09-03 in
`9c82c32c2b2e9c7eb2bb9ae11765f3b1b0eba0e2`. It remains pending
independent review; this report does not claim the review is clean.

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

## Review fix round 1 — 2026-09-03

### Reviewer finding decisions

1. **Accepted — AnalyzeOptions limits and canonicalization.** Backend
   `VerificationOptions` permits at most 500 retained glossary terms and 500
   retained banned words, bounds each retained string to 200 Unicode code
   points, and rejects compact UTF-8 canonical JSON above 64 KiB. The shared
   snapshot boundary now mirrors backend ordering and normalization: glossary
   identity mappings are removed, banned words are trimmed/deduplicated, and
   limits are checked after canonicalization. Exact 64 KiB is accepted and
   64 KiB plus one byte is rejected.
2. **Accepted — successful response validation.** `JobRead` responses now
   validate UUID/path identity, seven-format type, status/stage/progress
   coherence, nullable errors, and timestamps before a subscription can be
   created. The authoritative `/jobs/{id}/result` response is the canonical
   backend model, not the legacy direct-analysis payload: it omits
   `success`/`filename`/`file_id`/`file_ext` and legacy issue offset aliases,
   and carries `metadata.pdf`. The existing strict workspace result validator
   is now reused at both API boundaries and canonically adapts those transport
   differences. Malformed direct or async success bodies reject before
   execution/session publication.
3. **Accepted — fatal SSE protocol failure.** Subscription errors now carry
   `transient` or `fatal` kind. Browser reconnect errors retain processing and
   show a connection notice; malformed JSON or unknown/invalid progress fields
   close the source, fail execution, clear active state, and surface the
   protocol error.
4. **Accepted — replay sequence semantics.** Progress IDs must match a strict
   nonnegative decimal integer and fit `Number.isSafeInteger`; signs,
   fractions, suffixes, empty IDs, and oversized integers are fatal. Duplicate
   and decreasing sequences are ignored before payload/state mutation, so
   progress and terminal effects cannot regress. Native EventSource continues
   to own `Last-Event-ID` reconnect transmission, matching the backend replay
   contract.
5. **Accepted — terminal/result-expiry race.** A 410 result response after
   either `completed` or `partial` SSE replaces the prior presentation with
   `expired` status/stage/message and coherent `JobRead` error metadata while
   retaining the last terminal progress value. No result is published.
6. **Accepted — review-branch errors.** Recheck/request/transform failures
   preserve the existing workspace result and now render an assertive,
   accessible review error alert instead of being hidden by the landing-only
   source input.
7. **Pushback — partial warning session persistence.** Version-2 session state
   intentionally persists the canonical result/revision/review state, not
   ephemeral SSE transport status/message. Canonical degradation reasons and
   OCR metadata already survive in the result. Persisting `JobStatus.partial`
   plus an event message would expand the session schema with noncanonical
   execution state and belongs to later persistence work, not Task 5. The
   current backend also defines `partial` but has no production transition to
   it. No Task 6/session schema change was made.

### Round 1 RED/GREEN evidence

- AnalyzeOptions RED:
  `npm test -- --run tests/analyzeOptions.spec.ts --reporter=dot` failed 7
  limit/normalization assertions with 2 passing.
- AnalyzeOptions GREEN: the same command passed 9 tests.
- Response-validation RED:
  `npm test -- --run tests/jobsApi.spec.ts tests/verificationApi.spec.ts --reporter=dot`
  failed 4 assertions because malformed success bodies resolved and the
  canonical async response was not adapted.
- Response-validation GREEN:
  `npm test -- --run tests/jobsApi.spec.ts tests/verificationApi.spec.ts tests/useVerificationWorkspace.spec.ts --reporter=dot`
  passed 166 tests across 3 files.
- Canonical issue-alias RED/GREEN: the focused jobs API regression first
  rejected the authoritative issue shape, then passed after `start`/`end`
  were adapted to `position`/`end_position`.
- SSE RED: jobs API regressions exposed string-only error classification,
  permissive IDs, and four delivered duplicate/decreasing events instead of
  two. The integrated execution regression was also reconfirmed with the fatal
  branch removed: it failed with `processing` instead of `failed`.
- SSE GREEN:
  `npm test -- --run tests/jobsApi.spec.ts tests/useVerificationExecution.spec.ts --reporter=dot`
  passed 57 tests. The focused integrated fatal regression passed after
  restoration.
- Expiry-race RED:
  `npm test -- --run tests/useVerificationExecution.spec.ts --reporter=dot`
  failed 2 cases because completed/partial job status remained terminal
  success after a deferred 410.
- Expiry-race GREEN: the same command passed 19 tests.
- Review-alert RED: the focused WorkspaceView test could not find
  `[data-review-execution-error]`.
- Review-alert GREEN: the focused WorkspaceView test passed while retaining
  the existing `DocumentViewer` result.

### Round 1 validation

- Focused Task 5 and shared-boundary GREEN:
  `npm test -- --run tests/analyzeOptions.spec.ts tests/jobsApi.spec.ts tests/verificationApi.spec.ts tests/useVerificationExecution.spec.ts tests/useVerificationWorkspace.spec.ts tests/WorkspaceView.spec.ts --reporter=dot`
  passed 241 tests across 6 files.
- Full frontend GREEN: `npm test -- --run --reporter=dot` passed 353 tests
  across 16 files. Node emitted the existing experimental `localStorage`
  warning.
- Production build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3
  with 56 modules transformed.
- `git diff --check` passed with no output.

### Round 1 implementation commit

`9c82c32c2b2e9c7eb2bb9ae11765f3b1b0eba0e2`
(`fix: address task 5 review findings`).
