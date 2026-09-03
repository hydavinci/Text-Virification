# SDD ledger — plan: docs/superpowers/plans/2026-08-30-vue-workspace-redesign.md

## Baseline

- Branch: `task-0-unified-pipeline-prerequisites`
- Base: `0fbe3d4203e2327f3f567c4d9a9abd0de8126661`
- Frontend: 31 tests passed; production build passed.
- The current checkout is a normal repository on the existing feature branch. The previously approved in-place workflow remains in effect.

## Preflight scan

| Task(s) | Shared file or interface | Finding |
|---|---|---|
| Task 1 | `VerificationResult`, `TextBlock`, issue state | The current types omit image blocks and still expose legacy position aliases. Stable review state must use `issue_id`, while canonical `start`/`end` remain authoritative and aliases are compatibility-only. |
| Tasks 1, 3, 4, 6 | `useVerificationWorkspace`, decisions, revisions, session | Task 1 must expose serializable stable-ID decisions and immutable revision primitives so later navigation, editing, export, and session restore do not create parallel state models. |
| Tasks 1, 4 | accepted replacements and manual edits | Accepted issue replacements apply to their source revision only. Search/replace or free edit creates a new revision and invalidates stale issue offsets until re-verification. |
| Tasks 2, 5 | `AnalyzeOptions`, file submission | Task 2 owns option editing, while Task 5 owns execution. `JobsApi.createJob` must accept and serialize the same options snapshot as synchronous analysis. |
| Tasks 2, 6 | terminology parsing and session | Glossary pairs and banned-word lists have different schemas. Shared delimiter/BOM/comment handling is allowed, but they require separate typed parsers and bounded imports. |
| Tasks 3, 4 | source highlights and edited revisions | Task 3 renders only validated offsets from the currently verified source. Task 4 revisions must not reuse stale highlights after text changes. |
| Tasks 3, 6 | accessible document/issue navigation | Vue nodes, stable `data-issue-id`, focusable controls, selection focus, and `scrollIntoView` are required; raw HTML is prohibited. |
| Tasks 4, 6 | revision IDs and export | The current backend persists review revisions internally but exposes no complete edited-revision API for asynchronous exports. A UI-only request shape would be nonfunctional. |
| Tasks 5, 6 | canonical result, SSE terminal events, session | SSE completion is a control event; Task 5 must fetch `/jobs/{id}/result`, ignore late callbacks by generation, and persist only validated versioned state. |
| Tasks 5, 6 | job types and progress | Current frontend job types list only DOCX/PDF/TXT and omit derived `stage`. They must match the seven-format backend and retain coarse status plus derived stage. |
| Task 6 | Playwright and production preview | The browser suite must use deterministic route fixtures for UI behavior and keep a separate honest live backend E2E boundary; dependency installation and Chromium download are expected plan changes. |
| Task 6 | responsive/accessibility coverage | The plan names accessibility and responsive behavior globally but only sketches dialog/status tests. Add keyboard, focus restoration, reduced viewport, labels, and live-region coverage without a new state library. |

## Rulings

Ruling: Work continues in the existing feature-branch checkout rather than creating a second linked worktree — this preserves the already reviewed commit chain; cost if wrong is reduced isolation from unrelated local edits, mitigated by a clean tracked tree check before every task.

Ruling: Stable issue decisions and explicit suggestion overrides persist only for matching issue IDs within the same document/source/run identity (`document_id`, document `source_version`, and `verification_run_id`); absent IDs are pruned and any identity change resets review state — preserving IDs across unrelated runs would leak stale review intent; cost if wrong is loss of a decision when a backend legitimately starts a replacement run intended to continue the same review.

Ruling: Task 1 extends frontend canonical types to include image blocks and current backend fields required by later tasks — postponing type parity would force unsafe casts in navigation and export; cost if wrong is slightly broader Task 1 scope.

Ruling: Task 2 implements separate bounded glossary-pair and banned-word import codecs while sharing delimiter and comment handling — the two data shapes cannot be safely represented by one parser; cost if wrong is duplicated small parsing logic.

Ruling: Task 5 updates `JobsApi.createJob(file, options)`, seven-format job types, derived progress stages, and `getResult` together — the backend now persists async options and emits derived stages, so the older frontend contract is invalid; cost if wrong is a larger API migration within one task.

Ruling: Task 6 may add the minimum reviewed backend API/service wiring needed to persist a document revision and export it for asynchronous results — the binding spec requires revision-keyed real exports, and route fixtures alone would preserve a dead control; cost if wrong is backend work inside a frontend-focused plan and additional backend verification.

Ruling: The advanced and unified SDD ledgers are archived outside the repository before their temporary workspaces are removed — their Git commits remain authoritative while the archive preserves implementation rulings for the final handoff; cost if wrong is relying on a session artifact until the final response.

## Task 1 implementation — 2026-09-02

- Added `useVerificationWorkspace()` as the canonical Vue review-state boundary without an external state library.
- Decisions and explicit suggestion overrides are stored in serializable records keyed by `issue_id`. Reloading the same document/source/run identity preserves matching IDs and prunes missing IDs; changing any identity component resets review state.
- Canonical issue validation uses `start`/`end`, document/run ownership IDs, original slices, and block-local mappings. Issue `source_version` remains checker provenance and is not compared with the result's document hash. Duplicate, stale, overlapping, fractional, mismatched, and out-of-range issues are excluded deterministically.
- Accepted non-null suggestions are applied from descending source offsets. Empty strings delete source ranges, while `null` suggestions leave text unchanged.
- Batch snapshots record whether each state property previously existed, allowing undo to restore explicit values and property absence exactly.
- Added frozen source, review, and manual revision values. Manual revisions clear source-bound decisions and suggestions and set `requiresReverification`.
- Updated frontend canonical types for image blocks, JSON-valued metadata, PDF/OCR response metadata, nullable review fields, and document revisions. Legacy `position`/`end_position` remain required compatibility aliases for the existing view, but the composable never uses them.

### Task 1 TDD and validation evidence

- RED: `cd apps/web && npm test -- useVerificationWorkspace.spec.ts` failed because `../src/composables/useVerificationWorkspace` did not exist.
- Fresh pre-change baseline: `cd apps/web && npm test -- --run` passed 31 tests in 3 files.
- GREEN: `cd apps/web && npm test -- useVerificationWorkspace.spec.ts` passed 12 tests in 1 file.
- Fresh final frontend suite: `cd apps/web && npm test -- --run` passed 43 tests in 4 files.
- TypeScript/production validation: `cd apps/web && npm run build` passed `vue-tsc -b` and the Vite production build.

Ruling: Pending review state is represented by an absent stable-ID property unless an explicit `pending` value is restored — this preserves a compact serializable model while allowing exact batch undo; cost if wrong is consumers needing to use `state ?? 'pending'` instead of assuming every issue has an entry.

Ruling: Overlapping canonical issues are normalized by ascending `start`, `end`, and `issue_id`, with later overlaps ignored — this makes source mutation and later highlighting deterministic across backend reorderings; cost if wrong is hiding an overlapping issue that a future UI may instead want to display without auto-application.

Ruling: A manual text revision immediately invalidates source-bound issues, decisions, suggestions, and batch history until a result is loaded again — stale offsets must not be applied to edited text; cost if wrong is requiring re-verification even when a manual edit happens outside every issue range.

## Task 1 independent review fixes — 2026-09-02

- Removed the invalid comparison between checker/rule `VerificationIssue.source_version` and document-hash `VerificationResult.source_version`; document and run ownership checks remain mandatory.
- Added typed code-point range helpers so backend Python Unicode offsets remain canonical on the wire while JavaScript string operations use converted UTF-16 indices. Astral characters are covered in global validation, block-local validation, original matching, and accepted replacement.
- Replaced the single loose revision interface with a discriminated source-versus-persistable union. Source revisions are explicitly non-persisted; review/manual drafts use client-generated UUIDs, include `verification_run_id`, positive per-result numbering, document source version, ISO `created_at`, and frozen serializable values.
- Changed `selectedSuggestions` to contain explicit user overrides only. Effective suggestions fall back to the current issue default, same-result reloads preserve explicit string/`null`/empty overrides, untouched issues adopt updated defaults, and absent issue overrides are pruned.
- Expanded result identity to `document_id` + document `source_version` + `verification_run_id` for state retention, batch ownership, revision identity, and sequence reset.

### Independent review TDD and validation evidence

- RED: `cd apps/web && npm test -- useVerificationWorkspace.spec.ts` failed with 20 failed and 3 passed tests. The expected failures covered source-version conflation, Python-code-point offsets, stale default suggestions, missing persistable revision metadata/UUIDs, and run identity leakage.
- GREEN: `cd apps/web && npm test -- useVerificationWorkspace.spec.ts` passed 23 tests in 1 file.
- Full frontend suite: `cd apps/web && npm test -- --run` passed 54 tests in 4 files.
- Production build: `cd apps/web && npm run build` passed `vue-tsc -b` and Vite 6.4.3 (`22 modules transformed`, built in 313 ms).
- Scope check: only Task 1 composable/types/tests plus this ledger and `task-1-report.md` were changed.

Ruling: `VerificationIssue.source_version` identifies checker/rule provenance and must not be treated as the document revision hash — compatibility issues legitimately use `"1"` while the owning result uses a `sha256:` document source version; cost if wrong is accepting an issue from a different checker version, mitigated by immutable issue payloads plus document/run ownership and canonical text-range validation.

Ruling: Canonical backend offsets remain Unicode code-point offsets, with UTF-16 conversion confined to typed frontend string helpers — changing wire offsets would break Python persistence and cross-client contracts; cost if wrong is repeated linear scans for conversions, acceptable for the Task 1 review operations and replaceable later without changing the interface.

Ruling: Source revisions are non-persisted sentinels, while review/manual drafts use globally unique client UUIDs and per-result positive revision numbers — this matches backend review persistence without inventing a server source revision ID; cost if wrong is consumers needing to branch on the revision discriminant before persistence.

Ruling: `selectedSuggestions` records explicit user intent only, including explicit `null` and `""`; backend defaults are read dynamically from the current issue — this prevents stale copied defaults after a same-result refresh; cost if wrong is consumers needing an effective-suggestion fallback instead of reading the override record directly.

## Task 1 second scoped review fixes — 2026-09-02

- Canonical validation continues to reject stale, malformed, out-of-range, and duplicate-ID payloads, but no longer discards individually valid findings merely because their source intervals overlap. Canonical ordering and duplicate-ID selection remain deterministic across backend reorderings.
- `visibleIssues` and `summary` now retain every valid overlapping finding. Reversed-input tests prove the same two issue IDs remain visible in canonical order and are both counted.
- Accepted issues with effective non-null suggestions are checked for interval conflicts. The composable exposes deterministic reactive `replacementConflictIssueIds` and `hasReplacementConflicts` values without throwing from computed state.
- Conflicting accepted replacements fail closed: no draft is generated and no arbitrary partial winner is applied. The last valid source/review revision and its text remain current until rejection, undo, or suggestion changes remove the conflict; valid revision generation then resumes.
- Non-overlapping accepted replacements still apply from descending canonical code-point offsets, including multiple replacements after astral characters.
- Revisions are now a strict source/draft/persisted union. Source and draft revisions have `revision_number: null`; local review/manual drafts have a UUID, run/source identity, ISO timestamp, and `persistence_state: "draft"`. A separate persisted shape reserves positive server-assigned revision numbers for Task 6 hydration.
- Removed per-workspace revision sequencing. UUIDs provide cross-workspace draft identity, while `parent_revision_id` continues chaining to the prior valid non-source revision.

### Second scoped review TDD and validation evidence

- Pre-change focused baseline: `cd apps/web && npm test -- useVerificationWorkspace.spec.ts` passed 23 tests in 1 file.
- RED: the same focused command failed with 8 failed and 19 passed tests (27 total), covering overlap retention/counting, accepted-replacement conflicts, source/draft discrimination, nullable draft numbering, and UUID draft serialization.
- GREEN: the focused command passed 27 tests in 1 file; final effective-null conflict coverage increased the focused suite to 28 passing tests.
- Full frontend suite: `cd apps/web && npm test -- --run` passed 59 tests in 4 files. Node emitted the existing experimental `localStorage` warning; all tests passed.
- Production build: `cd apps/web && npm run build` passed `vue-tsc -b` and Vite 6.4.3 with 22 modules transformed.
- Scope check target: Task 1 composable/types/tests plus this ledger and `task-1-report.md`.

Ruling: Overlapping canonical findings remain review-visible because backend ownership and range validation make each finding independently valid; overlap is an application-time concern only for accepted effective replacements — this preserves rule-level findings while preventing ambiguous text mutation; cost if wrong is requiring the UI to present a conflict-resolution state instead of silently selecting one rule.

Ruling: Superseding the earlier client-sequence ruling, Task 6's minimal backend revision endpoint must allocate the positive per-run `revision_number` under database locking and return the persisted revision — the browser supplies the draft UUID, text, `verification_run_id`, and source metadata, but never supplies or invents a positive revision number; cost if wrong is an additional persistence round trip, required to prevent independent browser instances from colliding on the backend uniqueness constraint.

## Task 1 fourth review wave fixes — 2026-09-02

- `loadResult` now unwraps a Vue result proxy, creates an independent
  `structuredClone`, recursively freezes the complete canonical result graph,
  and validates and retains only that clone. Caller mutations after loading
  cannot alter document text, blocks, issues, offsets, or replacements.
- Canonical block validation now precedes issue validation. It enforces
  unique string IDs, integer nonnegative global/local offsets,
  code-point range lengths, zero-anchored local ranges, document slice
  equality, valid containing parents, acyclic parent chains, and
  ancestor/descendant-only range overlap.
- Any malformed or ambiguous block graph yields a frozen empty canonical issue
  array, independent of block input order. Valid nested blocks remain
  reviewable, including astral text whose JavaScript UTF-16 width differs from
  Python code-point offsets.
- Returning accepted review text to the source text retains the source sentinel
  only when the prior revision is source/null. If a different authored
  revision already exists, undo or rejection creates a fresh review UUID draft
  containing source text and parents it to that authored revision.
- The canonical issue array is frozen, and the composable returns readonly Vue
  views for the loaded result, issue-state map, suggestion overrides, current
  revision, and re-verification flag. Explicit pending state now goes through
  the public `setIssueState` method rather than mutating the exposed map.

### Fourth review wave TDD and validation evidence

- RED: `cd apps/web && npm test -- useVerificationWorkspace.spec.ts` failed
  with 15 failed and 29 passed tests (44 total). The failures covered
  duplicate block order, malformed block ranges/text/parents/cycles/overlap,
  missing `setIssueState`, authored source-text revert drafts, caller-owned
  mutation, and recursive freezing.
- GREEN: the focused command passed all 44 tests.
- Review regression RED: the focused suite failed with 1 failed and 46 passed
  tests (47 total), reproducing `DataCloneError` for a Vue reactive result
  proxy. Non-string block/parent ID cases were also added and passed after
  runtime type validation.
- Final focused GREEN: the focused command passed 47 tests in 1 file.
- Full frontend suite: `cd apps/web && npm test -- --run` passed 78 tests
  across 4 files. Node emitted the existing experimental `localStorage`
  warning; all tests passed.
- Production build: `cd apps/web && npm run build` passed `vue-tsc -b` and
  Vite 6.4.3 with 22 modules transformed.
- Scope check target: Task 1 composable/tests plus this ledger and
  `task-1-report.md`; canonical public wire types did not require mutation.

Ruling: Canonical result ownership begins with an immediate proxy unwrap,
structured clone, and recursive freeze at `loadResult`; validation and all
later review operations use only that internal value — this prevents
time-of-check/time-of-use changes from caller-owned objects; cost if wrong is
one full result clone per load, accepted for correctness at the workspace
boundary.

Ruling: A malformed block graph invalidates the issue set rather than selecting
apparently valid issues from an ambiguous map — block identity and containment
are prerequisites for trusting block-local issue offsets; cost if wrong is
hiding otherwise global issues when any block is malformed, intentionally
fail-closed until the backend returns a canonical result.

Ruling: Source text does not imply a source sentinel after authored work exists;
revision identity and ancestry must be preserved even when text content matches
the original source — this keeps persistence history append-only; cost if wrong
is an additional draft revision for an authored revert.

## Task 1 final allowed fix wave — 2026-09-02

- Replaced every returned `readonly(ref)` wrapper with a readonly computed
  accessor. `toRaw` now reaches only the computed accessor, never the internal
  writable result, revision, decision, suggestion, or re-verification refs.
- Result and revision accessors return the existing deeply frozen immutable
  values. Decision and selected-suggestion accessors return frozen record
  snapshots, and re-verification is exposed as a scalar computed value.
- Froze every publicly cached computed container: review summaries and
  replacement-conflict ID arrays. `visibleIssues` always returns a frozen array
  whose issue objects remain deeply frozen. Computed source text remains scalar
  and cannot be retargeted through `toRaw`.
- Removed the frontend-only non-empty `block_id` rule. A single empty string ID
  now follows the backend `TextBlock` contract and participates in canonical
  issue matching; duplicate empty IDs still fail closed through the unchanged
  uniqueness check in either input order.

### Final allowed fix wave TDD and validation evidence

- Focused pre-change baseline:
  `cd apps/web && npm test -- --run tests/useVerificationWorkspace.spec.ts`
  passed 47 tests in 1 file.
- RED: the same focused command failed with 3 failures and 48 passes (51
  total). Failures proved that one empty block ID was incorrectly rejected,
  `toRaw` could replace the public result source ref, and decision snapshots
  were mutable.
- GREEN: the focused command passed 51 tests in 1 file.
- Full frontend suite: `cd apps/web && npm test -- --run` passed 82 tests
  across 4 files. Node emitted the existing experimental `localStorage`
  warning; all tests passed.
- Production build: `cd apps/web && npm run build` passed `vue-tsc -b` and
  Vite 6.4.3 with 22 modules transformed.
- Scope check target: Task 1 composable/tests plus this ledger and
  `task-1-report.md`; no canonical wire type changes were required.

Ruling: Public composable state is exposed only through computed accessors, with
frozen snapshots for mutable record state and frozen values for every computed
container — Vue `readonly(ref)` is insufficient because `toRaw` reveals its
writable source ref; cost if wrong is allocating small record snapshots when
decision or suggestion state changes.

Ruling: `TextBlock.block_id` follows the backend string contract exactly,
including `""`, while uniqueness remains mandatory — adding frontend-only
non-empty validation rejects canonical backend payloads; cost if wrong is that
an empty ID is less descriptive, but it remains stable and unambiguous when
unique.

## Task 1 fifth and terminal review fix — 2026-09-02

- Confirmed the release blocker at the Vue implementation boundary:
  `toRaw(computed(...))` returns the same unfrozen `ComputedRefImpl`, which owns
  a writable private `_value`; assigning that cache retargeted subsequent
  public reads without using the readonly `.value` setter.
- Added the typed `WorkspaceReadonlyValue<T>` boundary. Every returned reactive
  value is now a frozen plain object with only a readonly getter and the minimal
  immutable `__v_isRef: true` marker. The getter closes over private internal
  refs/computeds, so Vue dependency tracking and ref unwrapping remain intact
  without exposing a Vue implementation object, writable source, cache, setter,
  or closure field.
- Wrapped `result`, `issueStates`, `selectedSuggestions`, `currentRevision`,
  `requiresReverification`, `modifiedText`, `visibleIssues`, `summary`,
  `replacementConflictIssueIds`, and `hasReplacementConflicts` consistently.
  Existing deep-frozen results/revisions/issues and frozen record/array/summary
  snapshots remain unchanged.
- Regression coverage proves each public facade is its own `toRaw` value,
  frozen, has no `_value`, rejects `_value` and `.value` replacement through
  both `Reflect.set` and assignment operations, preserves frozen containers,
  and continues updating through composable methods while facade identities
  remain stable.

### Fifth review TDD and validation evidence

- Focused pre-change baseline:
  `cd apps/web && npm test -- --run tests/useVerificationWorkspace.spec.ts`
  passed 51 tests in 1 file.
- RED: the same focused command failed with 1 failure and 51 passes (52 total)
  because the returned computed accessor was not frozen; a direct runtime
  diagnostic also showed `toRaw` identity, own `_value`, successful
  `Reflect.set`, and the public read changing from `"safe"` to `"poison"`.
- Focused GREEN: the same command passed 52 tests in 1 file.
- Full frontend suite: `cd apps/web && npm test -- --run` passed 83 tests
  across 4 files. Node emitted the existing experimental `localStorage`
  warning; all tests passed.
- Production build: `cd apps/web && npm run build` passed `vue-tsc -b` and
  Vite 6.4.3 with 22 modules transformed, built in 270 ms.
- Scope check target: Task 1 composable/tests plus this ledger and
  `task-1-report.md`; no canonical wire types or unrelated files changed.

Ruling: No Vue `Ref` or `ComputedRef` object may cross the Task 1 composable
boundary. Public reactivity is represented by a frozen getter facade over
private Vue state, and mutable container values remain frozen snapshots — this
closes both public setter and private-cache retargeting paths; cost if wrong is
one tiny facade allocation per returned value and unchanged snapshot allocation
for decision/suggestion records.

## Task 2 implementation — 2026-09-02

- Added `SourceInputPanel` as the controlled input boundary. It preserves file
  and direct-text modes, draft text across mode switches, Ctrl/Command+Enter
  submission, drag-and-drop, keyboard file-picker activation, all seven file
  extensions, and the inclusive 25 MiB maximum.
- Added `VerificationSettings` with six scenario choices and three independent
  compliance switches. Every change emits a complete cloned `AnalyzeOptions`
  snapshot instead of mutating the prop.
- Added `TerminologyEditor` for separate glossary-pair and banned-word
  workflows. Manual add, duplicate handling, deletion, clear, import, and
  example download all emit complete option snapshots suitable for the later
  execution composable.
- Added `useTerminology` with typed glossary and banned-word parsers. Imports
  accept CSV, TSV, and TXT files; recognize comma, tab, and arrow delimiters;
  handle quoted fields, UTF-8 BOMs, CRLF/LF, comments, and blank lines; retain
  first-seen order; and deduplicate without delimiter-key collisions.
- Terminology imports are transactional and bounded to the backend option
  contract: 64 KiB per import, 500 glossary pairs or banned words, and 200
  Unicode code points per value. Malformed quoting, invalid pair shape, empty
  values, identical pairs, unsupported files, and exceeded limits produce
  stable typed error codes and deterministic user messages.
- Terminology values render only through Vue text interpolation. Task 3's
  existing review highlighting remains unchanged; no new raw-HTML path was
  introduced.
- Integrated the three components into `WorkspaceView`. Synchronous text and
  file analysis still receive the current complete options, while the existing
  asynchronous `JobsApi.createJob(file)` contract is intentionally unchanged
  for Task 5. Existing analysis, progress, review, deletion-preview, export,
  and session behavior remains in place.

### Task 2 TDD and validation evidence

- Fresh pre-change baseline:
  `cd apps/web && npm test -- --run` passed 83 tests across 4 files.
- Initial RED:
  `npm test -- SourceInputPanel.spec.ts VerificationSettings.spec.ts useTerminology.spec.ts TerminologyEditor.spec.ts`
  failed all 4 suites because the planned components and composable did not
  exist.
- Component/composable GREEN: the focused component command passed 24 tests
  across 4 files before workspace integration.
- Workspace integration RED:
  `npm test -- WorkspaceView.spec.ts` failed because `WorkspaceView` did not
  render the new component contracts; the retained unsupported-format
  assertion also caught a wording regression during extraction.
- Parser review RED: focused `useTerminology` runs separately reproduced
  malformed-quote acceptance and a glossary-pair dedupe-key collision; each
  failed before its minimal parser fix.
- Final focused suite:
  `npm test -- SourceInputPanel.spec.ts VerificationSettings.spec.ts useTerminology.spec.ts TerminologyEditor.spec.ts WorkspaceView.spec.ts --reporter=dot`
  passed 38 tests across 5 files.
- Final frontend suite:
  `npm test -- --run --reporter=dot` passed 109 tests across 8 files. Node
  emitted the existing experimental `localStorage` warning; all tests passed.
- Production build: `npm run build` passed `vue-tsc -b` and Vite 6.4.3 with
  29 modules transformed.

Ruling: Task 2 mirrors the already-bound backend terminology limits
(`64 KiB`, `500`, and `200`) at the import boundary and rejects the entire
operation before mutation when any bound or row is invalid — partial imports
would make correction and later session replay nondeterministic; cost if wrong
is rejecting a mostly valid file until its invalid row is fixed.

Ruling: Glossary-pair and banned-word parsers remain separate typed APIs while
sharing only low-level delimiter and line handling — glossary rows require
exactly two nonempty different values, while banned-word rows may contain one
or more values; cost if wrong is a small amount of explicit schema-specific
code.

Ruling: `update:options` always carries a full cloned options snapshot, and
`submit-text`/`submit-file` carry only the selected source — Task 5 can consume
these contracts without moving execution or changing `JobsApi` during Task 2;
cost if wrong is cloning two small terminology arrays for each settings edit.

## Task 2 independent review fixes — 2026-09-03

- Replaced per-import-only size validation with projected complete
  `AnalyzeOptions` validation for initialization, setters, manual additions,
  and sequential imports. The compact UTF-8 JSON mirrors backend wire names:
  `scenario`, `enable_security`, `enable_sensitive`, `enable_ad_extreme`,
  `custom_glossary`, and `banned_words`.
- Exactly 64 KiB is accepted. Any projected mutation over the limit raises the
  typed `options-too-large` error with the deterministic message
  `完整检查设置不能超过 64 KiB。` before state changes. Independent
  500-entry and 200-code-point limits remain intact.
- `VerificationSettings` validates scenario and switch changes against the
  complete supplied option context. `TerminologyEditor` initializes and
  atomically resynchronizes the terminology composable with the supplied
  scenario, switches, glossary, and banned words.
- `readTerminologyFile` now returns decoded content plus its extension-derived
  CSV/TSV/TXT format. CSV is comma-only, TSV is tab-only, and TXT alone
  automatically detects tab, arrow, then comma.
- The fixed-delimiter parser now supports quoted fields containing LF, CRLF,
  escaped quotes, commas, arrows, and tabs while retaining the starting
  physical source line for deterministic validation errors. Failed imports
  remain transactional.
- Removed native `maxlength` from glossary and banned-word fields so the
  code-point validator accepts 200 astral characters and rejects 201 without
  mutation.
- Source upload and terminology import each expose one visible focusable
  semantic control. Their native file inputs are programmatically activated,
  hidden, removed from tab order, and hidden from the accessibility tree.
- Added an immediate parent submission lock covering direct text, direct file,
  asynchronous create-job upload, and recheck entry paths. Duplicate source
  events are ignored before source mutation, optional-settings confirmation,
  request-generation changes, or API invocation; existing generation checks
  remain unchanged.

### Task 2 independent review TDD and validation evidence

- Focused pre-fix baseline:
  `npm test -- SourceInputPanel.spec.ts VerificationSettings.spec.ts useTerminology.spec.ts TerminologyEditor.spec.ts WorkspaceView.spec.ts --reporter=dot`
  passed 40 tests across 5 files.
- RED `useTerminology.spec.ts`: 6 failed and 16 passed.
- RED `TerminologyEditor.spec.ts`: 4 failed and 4 passed.
- RED `VerificationSettings.spec.ts`: 1 failed and 2 passed.
- RED `SourceInputPanel.spec.ts`: 1 failed and 7 passed.
- RED `WorkspaceView.spec.ts`: 3 failed and 12 passed.
- Follow-up CSV-comment RED: `useTerminology.spec.ts` failed with 1 failure
  and 25 passes.
- Follow-up multiline physical-line RED: `useTerminology.spec.ts` failed with
  1 failure and 26 passes.
- Focused GREEN: the focused command passed 61 tests across 5 files.
- Full frontend GREEN: `npm test -- --run --reporter=dot` passed 132 tests
  across 8 files. Node emitted the existing experimental `localStorage`
  warning; all tests passed.
- Production build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3
  with 29 modules transformed.

Ruling: The backend's 64 KiB contract applies to the complete serialized
verification options object, not independently accumulated import payloads.
All option-producing UI paths must validate the projected backend-shaped
snapshot transactionally; cost if wrong is rejecting a mutation before API
submission rather than surfacing a backend validation failure later.

Ruling: File extensions select strict CSV or TSV grammar, while only TXT uses
delimiter auto-detection. This preserves delimiters inside declared-format
fields and makes multiline quote handling deterministic; cost if wrong is
requiring users to choose the correct extension for their delimiter grammar.

Task 2: fix round 1/5 (5 addressed, 0 open — complete options size, format-faithful multiline import, duplicate submission lock, Unicode manual limits, visible focus semantics; commits 537bd80..8d0e407)

Task 2: complete (commits 6bbe971..8d0e407, review clean)

## Task 3 implementation — 2026-09-03

- Added `DocumentViewer`, `IssueList`, and `IssueDetails` as focused accessible
  workspace components, plus `useIssueNavigation` for stable-ID selection,
  offset selection, composed filters, deterministic fallback, and scrolling.
- Removed the document `v-html` path. Sentence and continuous views now render
  source exclusively through Vue text nodes and preserve exact source
  whitespace, blank lines, newlines, and trailing newlines.
- Converted canonical Python code-point offsets only at JavaScript string
  boundaries. Astral-character coverage includes document segmentation and
  tracked-text fallback export.
- Migrated WorkspaceView review state, suggestion overrides, batch operations,
  session serialization, component keys, and navigation from array indexes to
  canonical `issue_id` values through `useVerificationWorkspace`.
- Added `clearResult()` to the canonical workspace boundary so the existing
  reset action clears result, decisions, overrides, revisions, conflict state,
  and batch history before a later analysis.
- Preserved existing analysis, job/progress, settings, terminology, summary,
  search/edit controls, export entry points, theme, privacy, and session
  behavior without implementing Task 4 or Task 5.

### Task 3 TDD and validation evidence

- Fresh pre-change baseline:
  `cd apps/web && npm test -- --run --reporter=dot` passed 132 tests across
  8 files.
- Initial RED:
  `npm test -- DocumentViewer.spec.ts IssueNavigation.spec.ts` failed both
  suites on missing component imports.
- Workspace integration RED: the focused WorkspaceView test failed because the
  new source and issue components were not present.
- Focused regression REDs reproduced incorrect duplicate-text tracked export
  after an astral character, missing accepted/rejected source states, a
  manual-only issue with one unselectable alternative, missing arbitrary
  overlap styling, and stale canonical state after workspace reset.
- Focused GREEN:
  `npm test -- DocumentViewer.spec.ts IssueNavigation.spec.ts WorkspaceView.spec.ts useVerificationWorkspace.spec.ts --reporter=dot`
  passed 87 tests across 4 files.
- WorkspaceView GREEN:
  `npm test -- WorkspaceView.spec.ts --reporter=dot` passed 17 tests.
- Full frontend GREEN:
  `npm test -- --run --reporter=dot` passed 152 tests across 10 files. Node
  emitted the existing experimental `localStorage` warning.
- Production build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3
  with 40 modules transformed.
- `git diff --check` passed with no output.

Ruling: Crossing and nested issue ranges are represented by deterministic
non-crossing text segments plus one empty-text, focusable marker at each
issue's canonical start. Segments show aggregate highlight/overlap state while
every issue remains independently navigable through its stable marker — this
avoids invalid crossing DOM marks, duplicated source text, and silently dropped
issues; cost if wrong is a marker-based interaction instead of making every
highlighted character itself a separate issue button.

Ruling: Offset selection uses half-open canonical ranges and chooses the
shortest containing issue, then ascending `start`, `end`, and `issue_id` —
this makes boundaries and overlaps independent of backend array order; cost if
wrong is selecting a narrow rule finding when a user expected the broader
finding at the same character.

Ruling: When filtering hides the selected issue, navigation chooses the next
visible issue in canonical order, then the nearest prior visible issue, then
`null`; a still-visible selection is preserved — this avoids retaining a
hidden current item; cost if wrong is an automatic selection change when a user
might prefer filters always clear selection.

Ruling: `null` suggestions are manual-only and do not mutate source text,
whereas `""` is the explicit deletion replacement. Alternatives are
deduplicated against the primary suggestion and the first remaining actual
alternative is marked recommended — this matches the Task 1 replacement
boundary; cost if wrong is changing the legacy UI label that previously
conflated nullable suggestions with deletion.

## Task 3 review fixes — 2026-09-03

- Modified export now checks canonical replacement conflicts before any Blob
  fallback or original-file API call. Crossing, nested, and identical accepted
  ranges all fail closed with one deterministic conflict-resolution message
  while preserving the last valid canonical revision.
- WorkspaceView delegates accept-all, reject-all, and batch undo to
  `acceptIssues`, `rejectIssues`, and `undoLastBatch`. The composable exposes a
  frozen reactive `canUndoLastBatch` facade backed by identity-bound batch
  history; loads, clear/reset, manual revision, undo, and session restoration
  clear eligibility.
- Batch acceptance publishes the complete stable-ID state once. Accepted
  overlap conflicts retain the prior revision instead of exposing an
  intermediate partial replacement, and undo restores the exact prior state.
- Hidden-selection fallback uses the selected issue's index in full
  `orderedIssues`; newly visible later findings win over earlier visible
  findings, followed by nearest prior and then `null`.
- `useIssueNavigation` no longer queries or scrolls the global document.
  `DocumentViewer` and `IssueList` each own a root, query only their own
  role-specific stable-ID control, scroll on mount/remount and selection
  changes, guard unsupported scrolling, and reject stale scheduled IDs.
- Added exact-once segmentation coverage for nested and identical ranges plus
  empty source text. No Task 4-6 behavior was introduced.

### Task 3 review-fix TDD and validation evidence

- Focused pre-fix baseline:
  `npm test -- DocumentViewer.spec.ts IssueNavigation.spec.ts useVerificationWorkspace.spec.ts WorkspaceView.spec.ts --reporter=dot`
  passed 87 tests across 4 files.
- RED: the focused command failed with 22 failures and 89 passes after the new
  regressions were added. The new segmentation-only cases already passed.
- Focused GREEN: the focused command passed 111 tests across 4 files.
- Full frontend GREEN: `npm test -- --run --reporter=dot` passed 176 tests
  across 10 files. Node emitted the existing experimental `localStorage`
  warning.
- Production build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3
  with 40 modules transformed.
- `git diff --check` passed with no output.

Ruling: Export conflict checks precede every output path and use the canonical
workspace conflict flag — no renderer or API path may independently choose an
overlap winner; cost if wrong is requiring the user to resolve accepted
overlaps before exporting.

Ruling: Scrolling belongs to each mounted rendering component, not the
selection composable. A scheduled scroll is valid only while its captured
stable ID remains selected in that same component instance — this prevents
stale rapid-selection scrolls and cross-workspace DOM effects; cost if wrong is
duplicating a small scheduling helper in the two role-specific components.

## Task 3 review fixes — round 2 — 2026-09-03

- Exposed the existing exact-snapshot machinery through the canonical
  `setIssueStates(issueIds, state)` method. Accept all, reject all, and reset
  all now enter the same identity-bound LIFO history through one
  `WorkspaceView` call.
- Accept all followed by reset all now undoes reset first and accept second.
  Exact snapshots preserve explicit `pending` versus absent properties.
  New-result load, clear/reset, and manual revision still clear history, and
  accepted overlap batches remain atomic.
- Added identity-bound `restoreReviewState(...)` for untrusted session
  decisions and explicit suggestion overrides. It prunes IDs outside current
  safe issues, validates all values, preserves explicit `null` and empty
  overrides, replaces both maps synchronously, clears undo history, and
  creates at most one review revision.
- Crossing and nested restored accepts now expose conflicts without replacing
  the prior/source revision or modified text with an intermediate partial
  result. Nonconflicting restored state produces one correct review revision.
- `WorkspaceView.restoreSession()` now performs `loadResult` followed by one
  atomic restore call. Session maps remain keyed only by stable issue IDs.

### Task 3 fix-round-2 TDD and validation evidence

- Focused baseline passed 82 tests across
  `useVerificationWorkspace.spec.ts` and `WorkspaceView.spec.ts`.
- Batch RED failed 2 tests with 82 passing; batch GREEN passed 84 tests.
- Restore RED failed 7 tests with 84 passing; focused GREEN passed 91 tests.
- All Task 3 tests passed 120 tests across 4 files.
- The full frontend suite passed 185 tests across 10 files. Node emitted the
  existing experimental `localStorage` warning.
- `npm run build` passed `vue-tsc -b` and Vite 6.4.3 with 40 modules
  transformed.
- `git diff --check` passed with no output.

Ruling: Every valid all-action is a separate latest batch in a LIFO history;
undoing twice after accept all then reset all intentionally reaches the
pre-accept state — this matches the existing stack model and exact-snapshot
contract; cost if wrong is retaining more than one small batch snapshot.

Ruling: Restored review state is accepted only for the currently loaded
document/source/run identity and only for current safe stable IDs. Decisions
and overrides are installed together before one revision attempt, so an
accepted replacement conflict can retain the complete prior/source revision;
cost if wrong is pruning malformed legacy session entries without fallback.
