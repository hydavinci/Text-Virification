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
