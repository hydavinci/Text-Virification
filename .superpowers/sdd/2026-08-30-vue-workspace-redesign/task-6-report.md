# Task 6 report — export, revision persistence, session, accessibility, and E2E

## Status

Implemented on 2026-09-03 from base
`965510c984946db6b9cfa1e78bb3619728fccbe8`.

Implementation commits:

- `4d1623f511b83a876b391cbaad0b3c3058f12592`
  (`feat: persist review revisions for reconstruction export`)
- `e5bbfa156cd0813d69ac7565bb172d687f21524e`
  (`feat: complete workspace export session and accessibility`)

Task 6 is ready for the controller's independent review. This report does not
claim an independent review is clean.

## Backend delivery

- Added `ReviewRevisionDraft`, `PersistedDocumentRevision`, and
  `DocumentRevisionKind` canonical models. Browser payloads contain the draft
  UUID, run/document/source identity, parent UUID, revision kind, and text;
  source sentinels and client-supplied revision numbers are rejected.
- Added `ReviewRevisionService` and `POST /api/v1/jobs/{job_id}/revisions`.
  Typed persistence errors map to 404, 409, or retryable 503 responses.
- Added Alembic revision `0010_add_review_revision_chain`. Review revisions now
  persist `parent_revision_id` and `kind`, with a same-run parent foreign key
  and kind constraint.
- Added repository allocation under the verification-run row lock. The
  repository validates job, run, document, source, parent ownership, latest
  parent, and retry identity, then allocates the next positive per-run number
  inside the nested uniqueness transaction.
- Identical UUID retries return the original persisted revision, including its
  original number and timestamp. Reused UUIDs with different canonical data,
  missing/foreign parents, stale parents, and cross-identity payloads fail.
- Extended asynchronous reconstruction export with optional `revision_id`.
  Revision-aware artifacts include the persisted revision identity, receive a
  revision-keyed deterministic artifact UUID, and retain the existing source
  artifact UUID when no revision is requested.
- Reconstruction loads and validates the persisted revision, maps its complete
  text across canonical block boundaries, drops stale PDF span styling only
  for changed blocks, and passes the revised canonical document to the
  existing DOCX reconstruction exporter. Unmappable or foreign revisions fail
  explicitly.
- Existing run → job → artifact lock ordering, verified artifact download,
  repair, finalization, storage-key safety, and legacy synchronous report and
  original-file routes remain intact.

## Frontend delivery

- Added `ExportPanel.vue`, `WorkspaceHeader.vue`, and `PrivacyDialog.vue` and
  integrated them into `WorkspaceView` without adding a second review or
  execution state machine.
- `useVerificationWorkspace` now retains an immutable source/authored revision
  chain, validates restored chains, and hydrates matching drafts with
  server-assigned positive revision numbers.
- Added revision persistence and reconstruction export methods to
  `VerificationApi`. Persist requests deliberately omit `revision_number`;
  responses are identity-checked, date-normalized, and required to be
  persisted with a positive number before hydration.
- Asynchronous PDF export persists every draft ancestor in order, hydrates the
  workspace after each server response, then submits reconstruction export by
  the actual persisted current revision ID. Accepted replacement conflicts and
  `requiresReverification` disable and guard report/modified export.
- File uploads now select the jobs/SSE execution path in the production
  workspace, while direct text remains synchronous. The existing execution
  composable remains the only lifecycle authority.
- Added version-3 session storage for the canonical result, stable decisions,
  explicit suggestions, complete revision chain, options and terminology,
  filters, view mode, result/settings tabs, search state, tracked-change
  preference, selected issue, and required asynchronous job identity.
- Session restore prepares and validates the complete payload before one
  workspace commit. Partial, foreign, noncanonical, or corrupt version-3
  payloads leave current in-memory state unchanged. Valid legacy synchronous
  version-2 sessions migrate with conservative UI defaults.
- Session write/quota failures retain in-memory edits and expose an assertive
  warning. Invalid stored sessions are removed without clearing a valid
  current workspace.
- Added pre-mount theme application, persisted theme switching, labelled
  controls, a permanently mounted polite status region, assertive errors,
  keyboard-operable branding, responsive header/export controls, and
  reduced-motion styling.
- `PrivacyDialog` implements `aria-modal`, initial focus, Tab/Shift+Tab
  trapping, Escape close, backdrop close, and opener focus restoration.
- Fixed the default Jobs API browser `fetch` receiver after the real Chromium
  lifecycle exposed an `Illegal invocation` error.

## Playwright delivery

- Added `@playwright/test` with Chromium, a production
  `npm run build && npm run preview -- --host 127.0.0.1` web server, one worker,
  deterministic route fixtures, and ignored generated reports/results.
- Deterministic Chromium coverage includes:
  - direct text submission;
  - issue acceptance;
  - free editing;
  - versioned reload/session restoration;
  - asynchronous file job creation;
  - terminal SSE and canonical result loading;
  - draft revision persistence without a client number;
  - revision-keyed export submission and download;
  - 360 px viewport header/privacy usability and focus restoration.
- `live-backend.spec.ts` is an explicit separate boundary. It is skipped when
  `LIVE_API_URL` is absent and does not represent deterministic route fixtures
  as validation of backend internals.

## TDD evidence

### Backend RED

- `pytest -q tests/unit/application/test_review_revision_service.py` failed at
  collection because `application.review_revision` did not exist.
- `pytest -q tests/unit/infrastructure/test_review_revision_schema.py` failed
  because `parent_revision_id` was absent from `ReviewRevisionRow`.
- `pytest -q tests/integration/test_review_revision_routes.py` failed four
  tests because `get_review_revision_service` and the route were absent.
- Revision-aware reconstruction tests failed with
  `unexpected keyword argument 'review_revision_id'`; the export-route
  regression returned HTTP 422 for the new request field.
- PostgreSQL repository allocation/identity/concurrency cases were added to
  the existing real-database suite. Their local run skipped because
  `TEST_DATABASE_URL` was unset; SQLite was not substituted.

### Frontend RED

- Revision-chain tests failed 3 with 145 passing because `revisionChain` and
  `hydratePersistedRevision` were absent.
- `WorkspaceSession.spec.ts` failed at import because
  `useWorkspaceSession.ts` did not exist.
- Revision API tests failed 2 with 6 passing because `persistRevision` and
  `exportReconstruction` were absent.
- Export/header/privacy component suites failed at import because the three
  final components did not exist.
- Workspace integration tests exposed absent version-3 restoration,
  persistence-before-export, accessible storage warnings, and status/header
  integration.
- The async-file selection regression failed because a provided direct API
  still intercepted file execution.
- Theme bootstrap tests failed at import because the theme boundary was
  absent.
- UI-state persistence failed with saved `continuous` instead of `sentence`.
- Noncanonical restored options were incorrectly normalized and accepted.
- The browser-fetch receiver regression reproduced `TypeError: Illegal
  invocation`.

### E2E RED

- Initial `npm run test:e2e` failed because the script was absent.
- The next runs exposed the missing preview script and missing Chromium
  installation; Chromium was installed with
  `npx playwright install chromium`.
- Real Chromium then exposed the unbound Jobs API `fetch` receiver. The direct
  lifecycle also corrected its test locator to the component's accessible
  editor name. Both lifecycle failures were rerun to green.

## Final validation

- Focused frontend Task 6 suite: 207 tests passed across 7 files.
- Full frontend: `npm test -- --run --reporter=dot` — 451 tests passed across
  21 files. Node emitted the pre-existing experimental `localStorage` warning.
- Production frontend: `npm run build` — `vue-tsc -b` and Vite 6.4.3 passed;
  69 modules transformed.
- Playwright: `npm run test:e2e` — 3 deterministic Chromium tests passed;
  1 live-backend test skipped because `LIVE_API_URL` was unset.
- Focused affected backend: 75 passed, 40 PostgreSQL-gated tests skipped.
- Full backend: `pytest -q` — 912 passed, 73 skipped. Skips were the established
  `TEST_DATABASE_URL`, `LIVE_API_URL`, and optional OCR-runtime gates.
- Full backend Ruff: `ruff check src tests alembic` — passed.
- Changed backend mypy: 7 source files checked, no issues.
- Alembic: `alembic heads` — `0010_add_review_revision_chain (head)`.
- `git diff --check` — passed.

## Residual concerns

- Real PostgreSQL locking, uniqueness, migration, and concurrency cases remain
  environment-gated because `TEST_DATABASE_URL` was unset. No SQLite
  substitute was used.
- The browser live-backend boundary remains skipped because `LIVE_API_URL` was
  unset. Deterministic route fixtures validate frontend lifecycle and request
  contracts only.
- Controller independent review is still required.

## Review fix round 1 — 2026-09-03

Implementation commit:

- `29b37a1c0d4dccf5029555c1db8ba42ce2853056`
  (`fix: address task 6 review round 1`)

All nine findings were accepted after verification against the design,
repository contracts, browser state flow, exporter registry, and current
tests. No item received technical pushback. This round is implemented and
awaits independent re-review; it does not claim the review is clean.

### Finding dispositions and design decisions

1. **Accepted — complete revision projection.** Reconstruction still uses
   `SequenceMatcher` only to obtain a deterministic edit script, then projects
   edited target ranges through canonical block ownership. Insertions and
   replacements in unowned gaps expand the nearest renderable block boundary;
   ancestors expand with children; changed blocks drop stale span styling.
   Projection fails with `revision_text_unmappable` when no renderable owner
   exists or nested renderable blocks would duplicate edited output. Multi-
   block insertion, deletion, whole-range replacement, boundary expansion,
   astral Unicode, blank-line gaps, table cells, and safe nested parents are
   covered.
2. **Accepted — latest-revision export authorization.** The requested revision
   is checked under the verification-run lock at initial context load,
   reservation, finalization, ready-artifact retry, and download. A source
   export is latest only while no persisted revision exists. Finalization
   returns a typed stale-revision rejection after deleting matching pending
   metadata; artifact publication then removes the verified file. The route
   maps `revision_export_stale` to HTTP 409.
3. **Accepted — job-owned ordinary-format export.** Added
   `original_format` job artifacts through `JobStorage`,
   `JobOwnedSourcePathResolver`, `CompatibilityExporter`, and the existing
   exporter implementations for DOCX, DOC, PDF, TXT, RTF, Markdown, and CSV.
   The frontend no longer synthesizes compatibility `file_id`/`file_ext`
   values. Async non-PDF files use job-owned original-format export; text PDFs
   preserve PDF, while scanned/mixed PDFs explicitly use reconstructed DOCX.
4. **Accepted — immutable export operation snapshots.** Modified export
   captures job/result/source/revision-chain/text/format/track-change identity,
   checks a generation guard after every persistence and network await, and
   invalidates on reset, new execution/result, and unmount. Stale completions
   cannot download, notify success, hydrate another workspace, or mutate the
   current session. Review, suggestion, search, edit, and track-change controls
   are disabled during persistence/export and are released on failure.
5. **Accepted — strict asynchronous session identity and revision order.**
   Async version-3 sessions require `jobId === document_id`, while the
   canonical result supplies the run/source relationship. Persisted revision
   numbers must be unique sequential positives beginning at 1; persisted
   entries must precede drafts; parents must remain a single exact chain.
   Restored job identity is held by `useVerificationExecution` without
   fabricating a completed `JobRead`; reset clears it. Restore remains
   prepare-then-commit and invalid payloads publish no partial state.
6. **Accepted — real PostgreSQL revision concurrency coverage.** Added
   `persist_review_revision()` tests for chained concurrent drafts allocating
   1/2, same-UUID retry idempotency, stale-parent rejection, and UUID identity
   collision rejection. They use the existing `TEST_DATABASE_URL` fixture and
   no SQLite substitute.
7. **Accepted — deterministic browser format/OCR coverage.** Playwright now
   covers direct text, a valid ordinary DOCX upload/result/revision/original-
   format export, a real scanned-PDF fixture with an OCR progress event,
   canonical OCR result, reconstructed-DOCX export, and reduced viewport
   privacy behavior. Acceptance asserts the changed accepted count and the
   exact export request, not an always-present label. The live backend remains
   separately and honestly gated.
8. **Accepted — persistent export alerts.** Export failures now render a
   persistent `role="alert"`/assertive region until explicitly dismissed or
   superseded by another export/reset/result.
9. **Accepted — global reduced motion.** The root application stylesheet now
   near-disables animation duration, animation iteration, transition duration,
   transition delay, and smooth scrolling for every workspace/component
   descendant.

### Round-1 RED/GREEN evidence

- Projection RED:
  `pytest -q tests/integration/test_job_reconstruction_export.py -k
  'revision_projection'` — 6 failed, 2 passed. The nested-renderable duplicate
  regression separately failed 1 test. GREEN: 9 passed.
- Export authorization RED: stale route mapping returned 500 instead of 409;
  finalization race returned `export_persistence_failed`; ready-artifact retry
  and stale download did not raise. Each focused regression was rerun GREEN.
- Job-owned export RED: the route returned 422 for `original_format`; the
  service exposed the missing job-owned source resolver before passing the TXT
  artifact/download regression. Route and service focused tests passed.
- Frontend review RED:
  `npm test -- --run tests/WorkspaceTask6.spec.ts
  tests/WorkspaceSession.spec.ts tests/WorkspaceAccessibility.spec.ts
  tests/verificationApi.spec.ts tests/useVerificationExecution.spec.ts
  --reporter=dot` initially reported 38 failed and 17 passed while the guarded
  job export, execution-owned restore identity, strict numbering, persistent
  alert, and global transition rules were absent/incomplete.
- Compatibility identity RED: canonical async results produced a synthetic
  document UUID `file_id` instead of `null`. GREEN: Task 6 workspace suite
  passed 12 tests.
- Text-PDF boundary RED: the frontend requested `docx_reconstruction` instead
  of `original_format`. GREEN: the same focused suite passed.
- E2E RED iterations exposed an invalid OCR progress threshold, ambiguous
  locators, and scanned-result format detection. Final GREEN:
  4 deterministic Chromium tests passed and 1 live-backend test skipped.
- PostgreSQL revision collection:
  `pytest -q tests/integration/test_verification_repository.py -k
  'persist_review_revision or superseded_review_revision or
  revision_became_stale'` — 12 skipped because `TEST_DATABASE_URL` was unset;
  collection succeeded and SQLite was not used.

### Final validation after round 1

- Affected backend revision/export/registry/golden suites:
  169 passed, 43 PostgreSQL-gated skipped.
- Full backend: `.venv/bin/python -m pytest -q` — 928 passed, 79 skipped.
  Skips were the existing `TEST_DATABASE_URL`, `LIVE_API_URL`, and optional OCR
  runtime gates.
- Full backend Ruff: `.venv/bin/python -m ruff check src tests alembic` —
  passed.
- Full backend mypy: `.venv/bin/python -m mypy src` — 72 source files, no
  issues.
- Alembic: `alembic heads` reported
  `0010_add_review_revision_chain (head)`; offline `upgrade head --sql`
  generated the full chain through 0010.
- Full frontend: `npm test -- --run --reporter=dot` — 463 passed across
  21 files. Node emitted the existing experimental `localStorage` warning.
- Production frontend: `npm run build` — `vue-tsc -b` and Vite 6.4.3 passed;
  70 modules transformed.
- Playwright: `npm run test:e2e` — 4 deterministic Chromium tests passed;
  1 live-backend test skipped because `LIVE_API_URL` was unset.
- `git diff --check` — passed before the implementation commit.

### Round-1 residual concerns

- The new PostgreSQL concurrency and stale reservation/finalization tests were
  collected but not executed locally because `TEST_DATABASE_URL` was unset.
- The live API/worker/OCR browser boundary remains unexecuted because
  `LIVE_API_URL` was unset; deterministic fixtures validate browser behavior
  and wire contracts rather than backend internals.
- Projection is deterministic and explicitly fail-closed for unrepresentable
  structures, but an independent re-review should still scrutinize unusual
  canonical block graphs and extreme edit scripts.
