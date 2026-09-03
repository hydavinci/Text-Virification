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
