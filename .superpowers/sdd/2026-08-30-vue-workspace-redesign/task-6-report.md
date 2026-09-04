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

## Review fix round 2 — 2026-09-03

Implementation commit:

- `7ce7da66c9a396694180ec5207f4e812d50d8f12`
  (`fix: address task 6 review round 2`)

All eight findings were accepted after verification against the Task 6 plan,
binding design, current exporter behavior, persistence lock order, browser
state flow, and tests. No item received technical pushback. This round is
implemented and awaits independent re-review; it does not claim the review is
clean.

### Finding dispositions and contract decisions

1. **Accepted — fail-closed structural revision contract.** Revised text is no
   longer globally projected through `SequenceMatcher`. Reconstruction
   preserves the source prefix, suffix, and every non-renderable gap exactly;
   the ordered gap placement must be unique. Each changed paragraph, heading,
   or table-cell owner receives only its uniquely delimited revised segment.
   Deletion, replacement, or insertion at paragraph/table/block gaps, adjacent
   owner boundaries, and ambiguous repeated separators fail before artifact
   reservation with typed `revision_structure_conflict` HTTP 409. Repeated
   text and astral Unicode edits strictly inside uniquely delimited blocks
   remain supported. Tests inspect the downloaded DOCX and assert its exact
   paragraph content, while conflict tests prove no metadata or artifact is
   created.
2. **Accepted — bounded revision persistence and diff work.** Canonical
   revision text is capped at 5,000,000 Unicode code points and 25 MiB UTF-8,
   further capped by configured upload bytes in revision persistence and
   reconstruction export. Legacy/existing rows are revalidated before
   reconstruction. The shared bounded diff removes equal prefix/suffix text,
   rejects a middle-product work budget above 1,000,000, and rejects more than
   10,000 edit operations before compatibility or reconstruction mutation.
   Typed `revision_text_too_large` maps to 413 and
   `revision_diff_too_complex` maps to 422. Compatibility modified export also
   enforces the configured upload byte limit and returns 413.
3. **Accepted — atomic repair reservation with stale compensation.**
   `begin_export_artifact_repair()` now validates latest revision and source
   identity under the existing run → job → artifact lock order, transitions
   repair metadata, and returns the reservation used directly by publication;
   the separate second reservation transaction is skipped. If a newer
   revision commits after that transaction, finalization deletes the pending
   row and verified publication, and reconstruction export removes the repair
   quarantine before returning typed stale 409. A deterministic commit
   interleaving proves no pending metadata, quarantine, file, or incorrect
   ready artifact remains.
4. **Accepted — retained server-backed file export authority after recheck.**
   Recheck still obtains a fresh synchronous canonical result so stale issue
   offsets and result identity are replaced. Separately, the workspace retains
   the original asynchronous job/document/run/source/format authority from the
   server result. Export persists a manual revision against that authority and
   uses the job-owned export endpoint; no compatibility file ID is synthesized.
   DOCX and RTF retain original-format export, while scanned/unknown-layout PDF
   retains reconstructed-DOCX export. The authority and latest persisted
   parent are generation-guarded, backend-validated, and stored in strict
   version-4 sessions; valid version-3 sessions migrate with no retained
   authority.
5. **Accepted — concurrency tests now prove overlap.** Same-UUID retry,
   stale-parent, and UUID-collision PostgreSQL tests set second-writer started
   and finished events, assert the second writer entered, and assert it
   remained blocked before releasing the first commit. Existing
   `TEST_DATABASE_URL` gating and lock timeout remain unchanged.
6. **Accepted — bounded session preflight.** Restore bounds raw UTF-8 payloads
   before `JSON.parse`, then bounds result text, blocks, issues, issue
   alternatives/text, revision text/chain, state records, and options before
   workspace cloning or canonical validation. The raw session cap is 32 MiB;
   nested caps align with the 5,000,000-code-point revision/document limit,
   20,000 reconstruction elements, 100,000 issues, 10,000 revisions, and
   500-item/200-code-point options limits. Save applies the same preflight.
   Exact and exclusive raw, block-array, revision-text, UTF-8, code-point, and
   diff-work boundaries are covered.
7. **Accepted — export alert supersession.** Every report or modified export
   start clears the prior alert. All successful paths, including synchronous
   text download and compatibility modified export, leave the alert clear;
   new failures remain persistent and dismissible.
8. **Accepted — runtime reduced-motion scrolling.** `IssueList` and
   `DocumentViewer` now query
   `matchMedia('(prefers-reduced-motion: reduce)')` at scroll time and use
   `behavior: 'auto'` instead of smooth scrolling when requested. Existing
   default smooth behavior and global reduced-motion CSS remain covered.

### Round-2 RED/GREEN evidence

- Structural contract RED:
  `pytest -q tests/integration/test_job_reconstruction_export.py -k
  'repeated_unicode or cross_structure or structure_conflict'` — 6 failed,
  2 passed because every gap edit was accepted or failed only inside the DOCX
  exporter. GREEN with nested-parent coverage: 9 passed.
- Limits RED: the bounded-diff test module failed collection because
  `domain.text_edits` did not exist; the configured compatibility export test
  returned 200 instead of 413. Revision service and legacy reconstruction
  probes also lacked configurable limits. GREEN focused limits/revision set:
  20 passed, then the configured compatibility subset passed 7.
- Repair RED:
  `test_repair_stale_interleaving_leaves_no_pending_metadata_or_quarantine`
  returned typed stale but left a pending artifact row and quarantine. GREEN:
  the deterministic regression and repair collection passed 6.
- File recheck RED: three DOCX/PDF/RTF component cases attempted synchronous
  TXT download, made zero revision-persistence calls, and raised missing
  `URL.createObjectURL`; two session authority/version migration cases also
  failed. GREEN: all five authority cases passed, followed by 67 passing
  WorkspaceView/Task6/session tests.
- PostgreSQL barrier probe against base
  `663029e49af9bcdd0c0be2daef14701d83bb36ad` exited 1 and named the same-UUID
  and stale/collision tests as missing entered/blocked barriers. The hardened
  three cases collected and skipped honestly because `TEST_DATABASE_URL` was
  unset.
- Session bounds RED: `WorkspaceSession.spec.ts` reported 4 failures because
  raw-size and nested preflight APIs/limits were absent. GREEN: the suite
  passed 9 tests initially and 11 after export-authority/version migration
  coverage.
- Export alert RED: synchronous modified export left the old alert rendered.
  GREEN: the focused supersession case passed in the 53-test session/alert/
  navigation set.
- Reduced-motion RED: both source and issue-list scroll tests received
  `behavior: 'smooth'` instead of `auto`. GREEN: both passed, and the combined
  session/alert/navigation set passed 53.

### Final validation after round 2

- Focused backend reconstruction/revision/routes/repository/concurrency
  collection: 106 passed, 43 PostgreSQL-gated skipped.
- Broad affected backend exporter/artifact/compatibility/golden/repository
  collection: 221 passed, 52 skipped.
- Full backend: `.venv/bin/python -m pytest -q` — 942 passed, 79 skipped.
  Skips were the established `TEST_DATABASE_URL`, `LIVE_API_URL`, and optional
  OCR-runtime gates.
- Full backend Ruff: `.venv/bin/python -m ruff check src tests alembic` —
  passed.
- Full backend mypy: `.venv/bin/python -m mypy src` — 73 source files, no
  issues.
- Alembic: `alembic heads` reported
  `0010_add_review_revision_chain (head)`; offline `upgrade head --sql`
  generated the complete chain through 0010.
- Focused frontend WorkspaceView/session/navigation/accessibility/API set:
  138 passed across 8 files.
- Full frontend: `npm test -- --run --reporter=dot` — 475 passed across
  21 files. Node emitted the existing experimental `localStorage` warning.
- Production frontend: `npm run build` — `vue-tsc -b` and Vite 6.4.3 passed;
  70 modules transformed.
- Playwright: `npm run test:e2e` — 4 deterministic Chromium tests passed;
  1 live-backend test skipped because `LIVE_API_URL` was unset.
- `git diff --check` — passed before the implementation commit.

### Round-2 residual concerns

- The strengthened PostgreSQL blocking assertions remain collection-only in
  this environment because `TEST_DATABASE_URL` is unset; no SQLite substitute
  was used.
- The live API/worker/OCR browser boundary remains skipped because
  `LIVE_API_URL` is unset. Deterministic browser tests still validate the
  request and interaction contracts rather than backend internals.
- The retained recheck export authority is revalidated by revision
  persistence/export endpoints, but independent re-review should scrutinize
  multi-client parent conflicts and uncommon document gap graphs.

## Review fix round 3 — 2026-09-03

Implementation commit:

- `74a7a7247c4bb2368c67391bec1b41825c7d3626`
  (`fix: address task 6 review round 3`)

All seven findings were accepted after verification against the canonical
block offsets, DOCX renderer behavior, bounded diff implementation,
compatibility request parsing, artifact descriptor ownership, PostgreSQL lock
order, synchronous direct-text source identity, and strict session restore.
No finding received technical pushback. This round is implemented and awaits
independent re-review; it does not claim the review is clean.

### Finding dispositions and design decisions

1. **Accepted — source-range-aware structural ownership.** Reconstruction now
   builds one bounded edit script over the canonical source and revised text.
   Every non-empty edit must fit wholly inside exactly one renderable leaf
   owner; deletion/replacement of prefix, suffix, paragraph separators, table
   separators, or any range crossing owners is a typed
   `revision_structure_conflict`. Insertions inside an owner remain local.
   Boundary insertions deterministically belong to the ending owner first and
   otherwise the starting owner, so sole-block prepend/append and edits
   immediately beside preserved structure are representable. Structural source
   slices are copied by global offsets, edited owner text is rebuilt from local
   source offsets, and the complete reconstruction must equal the persisted
   revised text exactly. This removes raw substring searches, including their
   confusion between real inter-block newlines and newlines inside multiline
   blocks.
2. **Accepted — export-wide diff budget.** The source-aware design uses a
   single export-wide `SequenceMatcher`, so the existing pre-match work check
   and operation count are cumulative by construction rather than resetting
   per owner. A 101-block adversarial case exceeds the 1,000,000 work budget,
   and a separate reduced-limit case proves the fourth edit operation is
   rejected. Both fail with typed `revision_diff_too_complex` before document
   or artifact mutation.
3. **Accepted — validation before every export branch and bounded HTTP input.**
   A selected persisted revision is identity-checked and byte/code-point
   validated before choosing reconstructed or original-format export.
   `CompatibilityExporter` receives the configured maximum text bytes from the
   registry and forwards it to `export_original`. The compatibility request
   model caps `modified_text` at 5,000,000 code points. The route now reads JSON
   through a 32 MiB streaming body boundary, rejects oversized declared or
   observed bodies with 413 before JSON/model parsing, and converts bounded
   Pydantic errors back to normal FastAPI 422 responses without echoing the
   oversized input. TXT original-format tests cover exact/exclusive UTF-8 and
   code-point limits and assert no partial metadata or artifact.
4. **Accepted — request-owned stale compensation.** Finalization rejection now
   unlinks only a publication whose retained descriptor says this request
   created it. Repair preparation distinguishes already-current,
   newly-quarantined, and reused-quarantine states, including the rename race
   where another request moved the verified inode. A stale repair only removes
   quarantine it created. Deterministic interleavings prove a stale requester
   with `handle.created == false` preserves another request's READY file and
   that two stale repairs let only the quarantine owner clean up.
5. **Accepted — explicit retained-authority provenance.** Version-5 sessions
   bind the validated original job/document/run/source/format/revision
   authority to the exact fresh synchronous result document ID, verification
   run ID, SHA-256 source-version field, and deterministic UTF-8 text
   fingerprint. A binding fingerprint covers both sides. Recheck publishes the
   fresh result only when its text exactly equals the submitted recheck text;
   unrelated results fail without replacing the prior workspace. Restore
   validates the complete binding before one atomic workspace commit, and
   export revalidates it before persistence and after every await. Valid
   version-4 state migrates, but its unprovable retained authority is dropped;
   version-3 migration still restores no authority. New text/file input and
   reset continue clearing retained authority. The client binding is a
   continuity guard, not a replacement for backend job/revision authorization.
6. **Accepted — PostgreSQL lock-wait proof.** Distinct chained drafts,
   same-UUID retry, stale-parent, and UUID-collision cases record both backend
   PIDs. Before releasing the first transaction, the tests poll
   `pg_stat_activity`, ungranted `pg_locks`, and `pg_blocking_pids()` until the
   second backend is waiting on a lock held by the expected first backend.
   Polling is bounded and timeout failures include the last wait event,
   ungranted locks, blocking PIDs, and expected blocker. Fixed sleeps are no
   longer used as concurrency proof.
7. **Accepted — all retained-authority formats covered.** The component
   contract now parameterizes DOCX, DOC, PDF, TXT, RTF, Markdown, and CSV.
   PDF continues to choose reconstructed DOCX only for scanned/unknown layout;
   all ordinary formats select job-owned original-format export. The base
   coverage probe found only DOCX/PDF/RTF and named DOC/TXT/MD/CSV as missing;
   the current probe finds all seven.

### Round-3 RED/GREEN evidence

- Structural ownership RED:
  `pytest -q --tb=short tests/integration/test_job_reconstruction_export.py -k
  'source_anchored_paragraph or boundary_edits_around_table'` — 6 failed
  because multiline, sole-block boundary, repeated Unicode, and
  paragraph/table-boundary insertions raised `revision_structure_conflict`.
  GREEN with genuine structural conflicts and nested cases: 18 passed.
  Full reconstruction/diff GREEN: 56 passed.
- Export-wide budget RED:
  `pytest -q --tb=short tests/integration/test_job_reconstruction_export.py -k
  'many_small_block_diffs or cumulative_edit_operations'` — 2 failed because
  neither adversarial export raised. GREEN is included in the 18 structural
  cases.
- Original/compatibility limit RED:
  the job-owned TXT subset reported 3 failures and 1 pass because
  `max_revision_codepoints` and original-branch validation were absent; the
  exporter propagation test failed because `CompatibilityExporter` rejected
  `max_text_bytes`; the compatibility model case returned 413 instead of
  model-level 422; and the declared 32 MiB+1 body returned 422 instead of
  pre-parse 413. GREEN exporter/reconstruction/compatibility collection:
  139 passed. The compatibility model test also passes an exact 5,000,000
  code-point TXT request and rejects 5,000,001.
- Artifact ownership RED:
  the READY-reuse interleaving ended with `FileNotFoundError` because the stale
  request unlinked the existing file; the two-repair probe observed one
  non-owner quarantine deletion; and the descriptor rename race returned
  `QUARANTINED` instead of `REUSED_QUARANTINE`. GREEN artifact repair,
  storage, and compensation regressions passed.
- Provenance RED:
  `WorkspaceSession.spec.ts` reported 4 failures with 10 passing because the
  binding API was absent. `WorkspaceTask6.spec.ts` reported 1 failure with 20
  passing because an unrelated synchronous result replaced the asynchronous
  job result and retained its export authority. GREEN focused Task 6/session/
  workspace/API set: 84 passed; broader focused Task 6 set: 263 passed.
- PostgreSQL lock proof RED:
  an AST structural probe exited 1 and named the distinct-draft, same-UUID,
  and stale/collision `persist_review_revision` tests as missing backend PID
  and lock-wait proof. The updated four parameterized cases collect
  successfully. Runtime execution remains honestly gated because
  `TEST_DATABASE_URL` was unset.
- Seven-format coverage RED:
  a base-commit probe found retained-authority coverage for DOCX/PDF/RTF only
  and reported DOC/TXT/MD/CSV missing. The current probe reports all seven and
  no missing format.

### Final validation after round 3

- Focused backend reconstruction/export/compatibility/artifact/storage:
  180 passed.
- Broader focused backend Task 6 collection: 255 passed.
- Focused repository collection: 6 passed, 15 PostgreSQL-gated skipped;
  the four strengthened concurrency cases collected successfully.
- Full backend: `.venv/bin/python -m pytest -q` — 959 passed, 79 skipped.
  Skips were the established `TEST_DATABASE_URL`, `LIVE_API_URL`, and optional
  OCR-runtime gates.
- Full backend Ruff: `.venv/bin/python -m ruff check src tests alembic` —
  passed.
- Full backend mypy: `.venv/bin/python -m mypy src` — 73 source files, no
  issues.
- Alembic: `alembic heads` reported
  `0010_add_review_revision_chain (head)`; offline `upgrade head --sql`
  generated the complete chain through 0010. A live `alembic check` was not
  run because no PostgreSQL URL was configured.
- Focused frontend Task 6 authority/session/workspace set: 263 passed across
  7 files.
- Full frontend: `npm test -- --run --reporter=dot` — 483 passed across
  21 files. Node emitted the existing experimental `localStorage` warning.
- Production frontend: `npm run build` — `vue-tsc -b` and Vite 6.4.3 passed;
  70 modules transformed.
- Playwright: `npm run test:e2e` — 4 deterministic Chromium tests passed;
  1 live-backend test skipped because `LIVE_API_URL` was unset.
- `git diff --check` passed before the implementation commit.

### Round-3 residual concerns

- The PID/`pg_stat_activity`/`pg_locks`/`pg_blocking_pids()` assertions are
  structurally verified and collected but were not executed because
  `TEST_DATABASE_URL` was unset. No SQLite substitute was used.
- The live API/worker/OCR browser boundary remains skipped because
  `LIVE_API_URL` was unset; deterministic browser fixtures prove browser state
  and request contracts, not live backend internals.
- Retained-authority provenance is deliberately a deterministic client
  continuity binding. The backend remains the security boundary and still
  validates job, run, document, source version, latest parent, revision, and
  artifact identity.
- The export-wide diff budget intentionally fails closed for sufficiently
  complex edit scripts even when individual visual edits are small.
- Independent re-review is still required. Review cleanliness is not claimed.

## Review fix round 5 — 2026-09-03

### Finding decisions and implementation

1. **Accepted — mandatory server-enforced revision provenance.** Revision
   submissions now identify an explicit base verification result. The server
   loads the original persisted job result, proves whether the submitted text
   is a bounded derivation of that original result, and requires a valid
   recheck grant whenever the base identity differs or the text cannot be
   derived from the original issues. Verified provenance is persisted in the
   new `review_revisions.verified_provenance` JSONB column. Reconstruction
   export authorizes from that stored provenance, so omitting a request grant
   cannot downgrade a rechecked revision to an original-result revision.
2. **Accepted — complete structural alignment.** Projection aligns complete
   constrained owner sequences instead of trimming raw prefixes/suffixes
   before ownership. Multiline repeated owners may become empty or absorb
   representable text while structural separators remain exact; artifact-level
   regressions cover the reviewed multiline empty-block case.
3. **Accepted — raw preflight before canonical model construction.** Raw
   verification result block and aggregate-size limits are checked before
   constructing `DocumentModel`. Backend block graph overlap validation now
   uses an ordered ancestry-aware sweep with the established zero-length,
   ancestor, sibling, and cross-branch semantics rather than pairwise scans.
4. **Accepted — bounded and sanitized HTTP parsing.** Job recheck form data
   uses an explicit bounded streaming parser. Revision/export JSON uses bounded
   incremental parsing with duplicate-field, nesting, decoded-string, raw,
   and materialized-size limits, including requests without Content-Length.
   Validation responses are sanitized and do not echo submitted text or opaque
   grants.
5. **Accepted — deployed secret requirement.** `Settings` stores the HMAC
   secret as `SecretStr`; deployed/staging environments fail startup unless it
   contains at least 32 UTF-8 bytes. Development and tests remain explicit
   non-deployed modes. `.env.example`, README, and Compose configuration
   document and pass the secret without exposing it in representations or
   validation errors.

Alembic revision `0012_add_revision_provenance` adds the nullable JSONB
provenance column and object-shape constraint. The downgrade removes both.

### Round-5 TDD evidence

- Authorization exploit regressions cover omitted grants with arbitrary text,
  spoofed original identities, valid original issue-derived drafts, valid
  recheck grants, export without a request grant, and stored provenance
  cross-job/tamper rejection.
- Structural RED cases covered complete multiline repeated owner sequences;
  GREEN artifact checks confirm exact exported paragraph text.
- Raw-model preflight and ordered-overlap regressions cover oversized block
  payloads before element construction plus zero-length and hierarchy parity.
- HTTP boundary regressions cover inclusive/exclusive limits, chunked requests,
  escaped text, oversized grants, malformed bodies, and non-reflection in
  response/log output.
- Configuration regressions cover empty/short deployed secrets, valid 32-byte
  secrets, explicit test mode, startup validation, and secret-safe repr/errors.

### Final validation after round 5

- Focused backend authorization/structure/body/config collection:
  214 passed.
- Focused frontend revision/export API collection: 32 passed.
- Full backend: `.venv/bin/python -m pytest -q` — 1050 passed, 81 skipped.
  Skips were the established PostgreSQL, live API, and optional OCR-runtime
  gates.
- Full backend Ruff passed.
- Full backend mypy passed on 77 source files.
- Full frontend: `npm test -- --run --reporter=dot` — 487 passed across 21
  files.
- Production frontend build passed with 70 modules transformed.
- Playwright Chromium: 4 deterministic tests passed; 1 live-backend test
  skipped because `LIVE_API_URL` was unset.
- Alembic head is `0012_add_revision_provenance`; offline upgrade and
  `0012:0011` downgrade SQL generation passed.
- Compose configuration passed with an explicit 32-byte recheck secret.
- `git diff --check` passed.

### Round-5 residual concerns

- PostgreSQL locking/migration execution remains gated by
  `TEST_DATABASE_URL`; SQLite was not substituted.
- The live API/worker/OCR browser boundary remains gated by `LIVE_API_URL`.
- Independent final scoped review is still required. Review cleanliness is not
  claimed.

## Breaker adjudication and controlled fix wave — 2026-09-04

Ruling: After the five-round breaker, the materialization accounting bypass,
streamed-key identity bug, and post-recheck export dead end are load-bearing
and receive one controlled breaker fix wave — parking them would leave
exploitable memory exhaustion or a broken core workflow; cost if wrong is one
extra review cycle beyond the nominal cap.

### Breaker fixes

- Incremental JSON materialization now charges a fixed allocation overhead for
  every scalar, key, and container event, in addition to encoded value bytes.
  Explicit event and container-entry ceilings are enforced before value
  builders append entries. Callers that specify a materialized budget receive
  this stronger bound; raw-only small request limits retain exact inclusive
  byte semantics.
- The streamed compatibility report reader applies the same retained/event/
  entry accounting. It tracks the exact root `map_key` rather than deriving
  identity from dotted ijson prefixes, rejects unknown root fields, and keeps a
  unique-key set for every object, including skipped block metadata subtrees.
- Rechecked file authority remains available as the source for another
  job-bound recheck, but modified export is blocked whenever the current review
  revision text differs from the exact text covered by the grant. Accepting an
  issue therefore requires another recheck; rejection/no-op review that leaves
  text unchanged does not. Returning exactly to the grant-bound result text is
  safe because the result identity and opaque grant remain unchanged.

### Breaker TDD evidence

- RED: 9 backend failures reproduced 10,000 empty array entries passing a
  16-byte materialized budget, wide/nested empty structures passing retained
  limits, dotted root-key filename spoofing, and duplicate nested block keys.
- GREEN: body-reader regressions passed 6/6; focused report-reader regressions
  passed 7/7.
- RED: the recheck → accept issue → export regression called
  `persistRevision` with the old exact-text grant.
- GREEN: the workspace blocks that export with an explicit recheck message,
  performs a second job-bound recheck, then persists/exports once with the new
  grant.
- A full run exposed one inclusive raw-byte regression for the small job export
  body. Materialized accounting is now enabled only when the caller explicitly
  supplies that separate budget; the focused inclusive/chunked regression
  passed.

### Final breaker validation

- Focused backend parser/compatibility/revision collection: 80 passed.
- Focused frontend Task 6/workspace/session collection: 78 passed.
- Full backend: 1063 passed, 81 established environment/optional-runtime
  skips.
- Full frontend: 488 passed across 21 files.
- Production build passed with 70 modules transformed.
- Playwright Chromium: 4 deterministic tests passed; 1 live-backend test
  skipped because `LIVE_API_URL` was unset.
- Full Ruff passed; full mypy passed on 77 source files.
- Alembic head/offline upgrade SQL and Compose configuration passed.
- `git diff --check` passed.

Independent breaker scoped review is still required. Review cleanliness is not
claimed.

## Review fix round 4 — 2026-09-03

Implementation commit:

- `4cc9b7522664126a48f212cee4d1b34416299614`
  (`fix: address task 6 review round 4`)

All five findings were accepted after verification against the canonical block
model, reconstruction renderer, existing size and diff limits, artifact
repository lock order, filesystem descriptor rules, revision persistence,
frontend recheck flow, strict session restore, and settings infrastructure. No
finding received technical pushback. This round is implemented and awaits
independent re-review; it does not claim the review is clean.

### Finding dispositions and design/security decisions

1. **Accepted — immutable structural alignment for repeated adjacent blocks.**
   Reconstruction no longer derives block ownership from a global
   `SequenceMatcher` edit script. It trims unchanged prefix/suffix text, then
   runs a bounded structural alignment whose state permits edits only while a
   canonical renderable owner is active. Structural code points may only match
   exactly and in order; insertions at a boundary belong deterministically to
   the ending owner before the starting owner. The resulting target characters
   are assigned directly to owner ranges, structural slices are copied from
   canonical offsets, and the complete rebuilt text must equal the persisted
   revision. Artifact-level regressions cover repeated equal paragraphs in
   both directions, empty first/second paragraph results, repeated strings,
   astral Unicode, multiline blocks, tables, and the prior true-gap conflicts.
2. **Accepted — preflight plus one cumulative checked work budget.** Projection
   checks the canonical block count and source/revision/aggregate block text
   bounds before alignment. Owner lookup uses sorted interval starts with
   binary search; structural-range mapping uses indexed anchors; hierarchy
   depth is memoized rather than rescanned per block. Prefix/suffix scans,
   owner lookups, structural rebuilding, dynamic alignment work, hierarchy
   projection, and generated edit regions all debit one
   `CheckedTextWorkBudget`. `build_bounded_text_edits()` now rejects a known
   zero-operation budget before constructing a matcher and reserves bounded
   matching/edit-generation work before starting it. Counter-based and
   adversarial tests avoid timing assertions.
3. **Accepted — version-owned publication and compensation.** Alembic revision
   `0011_add_artifact_reservation_version` adds a monotonically refreshed
   artifact reservation version. Publication authorization now occurs under
   the canonical run → job → artifact lock sequence and requires the exact
   pending reservation version. Compensation reacquires the same locks,
   verifies the row is still this request's matching `PENDING` reservation,
   verifies the retained filesystem handle still names the created inode, and
   only then removes the file and metadata. A creator that loses ownership to
   an adopter/finalizer cannot unlink the adopted `READY` inode. Creator-first
   and adopter-first finalization interleavings are covered.
4. **Accepted — tokenized inode-bound repair quarantines.** Repair quarantines
   now use a unique UUID token in the path and return an immutable descriptor
   containing canonical job/artifact/storage identity, token, path, device,
   and inode. A retry adopts an older or legacy quarantine by renaming it to a
   fresh token path while the artifact row is locked. Cleanup accepts only the
   descriptor and unlinks only if the token-derived path still names its exact
   inode; an old owner cannot delete a replacement or a newer repair's
   quarantine. Orphan discovery validates both legacy fixed names and the new
   canonical tokenized form. Concurrent repair callers converge on one ready
   artifact; a caller whose reservation was superseded may receive the existing
   retryable repair-pending response without publishing under stale ownership.
5. **Accepted — server-signed expiring recheck provenance.** Added
   `POST /api/v1/jobs/{job_id}/recheck`, which runs the verification pipeline
   against the submitted text for the persisted job result and returns the
   fresh result plus a server-issued HMAC-SHA-256 grant. The signed version-1
   claims bind audience, issuance/expiry, original job/document/run/source,
   submitted recheck text SHA-256, and fresh result document/run/source. The
   secret and TTL come from `Settings` (`recheck_grant_secret` and
   `recheck_grant_ttl_seconds`); no fallback secret exists. Verification uses
   strict bounded base64/JSON parsing and constant-time signature and claim
   comparisons. Revision persistence and job export accept the opaque grant
   plus the current fresh result identity and recheck text, verify it before
   using the original job authority, and retain existing latest-revision and
   artifact authorization checks. Stateless replay is limited by expiry and
   remains idempotent through existing revision UUID and deterministic artifact
   semantics. Ordinary original-result revision/export flows remain grant-free.
   Version-6 sessions persist only the bounded opaque grant; valid version-5
   client-hash sessions migrate while dropping untrusted retained authority.
   New input and reset continue clearing authority.

### Round-4 RED/GREEN evidence

- Repeated-block projection RED:
  `pytest -q --tb=short tests/integration/test_job_reconstruction_export.py
  -k 'repeated_adjacent_blocks_without_crossing_separator'` — 4 failed and 2
  passed because the global edit script crossed or ambiguously owned the
  separator. GREEN with surrounding structural regressions: 21 passed; the
  final complete projection/artifact focused collection is included below.
- Work-bound RED: the zero-operation test entered the matcher and failed with
  the structural probe assertion. Projection preflight/budget tests reported 3
  failed and 1 passed because block/source preflight and cumulative linear
  charging were absent. GREEN: 6 bounded-text-edit tests and 25 selected
  projection/budget cases passed.
- Compensation RED: the creator/adopter interleaving reported 1 failed and 1
  passed; the stale creator removed the inode already finalized by the
  adopter. GREEN: both interleavings plus the owned-pending failure case passed.
- Quarantine RED: the focused storage module failed collection because the
  inode/token-bound `ArtifactRepairState` and descriptor contract did not
  exist. GREEN: 6 quarantine/repair storage cases passed, followed by the
  reconstruction repair collection.
- Provenance RED: backend grant/recheck tests failed collection because the
  grant and job-recheck modules did not exist. Frontend recheck/session/API
  regressions reported 11 failed and 37 passed because the client-generated
  hash remained, `recheckJob()` was absent, and provenance was not forwarded.
  GREEN: backend provenance route/service/revision/export selection passed 21
  tests; frontend API/session/Task-6 selection passed 48.
- A full verification run exposed a nondeterministic concurrent-repair test
  assertion: both safe callers sometimes returned the same ready reference,
  while the test required exactly one retryable loser. The invariant was
  corrected to permit one or two identical ready references and at most one
  retryable superseded caller. The regression then passed 10/10 repeated runs
  without timing-based assertions.

### Final validation after round 4

- Complete focused backend projection/budget/artifact/quarantine/provenance/
  route/service/revision/export/repository collection:
  235 passed, 43 PostgreSQL-gated skipped.
- Complete focused frontend recheck/session/export/workspace/API collection:
  118 passed across 6 files. Node emitted the existing experimental
  `localStorage` warning.
- Full backend: `.venv/bin/python -m pytest -q` — 996 passed, 79 skipped.
  Skips were the established `TEST_DATABASE_URL`, `LIVE_API_URL`, and optional
  OCR-runtime gates.
- Full backend Ruff: `.venv/bin/python -m ruff check src tests alembic` —
  passed.
- Full backend mypy: `.venv/bin/python -m mypy src` — 75 source files, no
  issues.
- Full frontend: `npm test -- --run --reporter=dot` — 487 passed across 21
  files. The existing Node experimental `localStorage` warning remains.
- Production frontend: `npm run build` — `vue-tsc -b` and Vite 6.4.3 passed;
  70 modules transformed.
- Playwright: `npm run test:e2e` — 4 deterministic Chromium tests passed; 1
  live-backend test skipped because `LIVE_API_URL` was unset.
- Alembic: `alembic heads` reported
  `0011_add_artifact_reservation_version (head)`; offline `upgrade head --sql`
  generated the complete chain through 0011. Live `alembic check` was skipped
  because `TEST_DATABASE_URL` was unset.
- Concurrent repair stress: the focused convergence regression passed 10/10
  repeated invocations.
- `git diff --check` passed before the implementation commit and before the
  documentation update.

### Round-4 residual concerns

- Reservation-version migration, PostgreSQL row locking, and live concurrency
  execution remain environment-gated because `TEST_DATABASE_URL` was unset.
  No SQLite substitute was used.
- The live API/worker/OCR browser boundary remains skipped because
  `LIVE_API_URL` was unset; deterministic browser fixtures validate frontend
  behavior and request contracts rather than live backend internals.
- Deployments must configure a secret of at least 32 UTF-8 bytes through
  `recheck_grant_secret` before job-bound recheck can issue grants. Missing or
  short configuration fails the recheck flow closed while ordinary
  original-result persistence/export remains available.
- Structural alignment intentionally fails with
  `revision_diff_too_complex` when the cumulative checked budget is exhausted,
  even if an unbounded algorithm could eventually find a representation.
- Independent re-review is still required. Review cleanliness is not claimed.
