# SDD ledger — plan: docs/superpowers/plans/2026-08-21-versioned-review-loop.md

Worktree: C:\Work\text-verification\.worktrees\versioned-review-loop
Branch: feature/versioned-review-loop
Starting commit: 22a5ca6

## Baseline

Ruling: Two pre-existing PDF report tests fail locally because WeasyPrint cannot load the Windows system library `libgobject-2.0-0`; this is an environment failure, not a repository regression. Local task gates exclude only those two tests, while Task 11 must run the complete suite in the Linux container. Cost if wrong: a PDF regression could remain hidden until Task 11, where it becomes blocking.

## Pre-flight consistency scan

| Scope | Producer → consumer | Finding / ruling |
|---|---|---|
| Task 1 internal | Domain contracts → migration and ORM | Consistent: names and persisted-vs-command decision semantics agree. |
| Task 2 internal | Version repository → scoped analysis persistence | Consistent: activation and analysis persistence share one transaction. |
| Task 3 internal | Draft repository → version/draft routes | Consistent: optimistic revision and structured `409` are specified together. |
| Task 4 internal | Draft snapshot → reanalysis worker and version SSE | Consistent: failed analysis preserves parent and draft. |
| Task 5 internal | Suggestions and decision preflight → history/undo | Consistent: `unreviewed` is a deletion command, not a stored state. |
| Task 6 internal | Canonical derived content → preview and export snapshot | Consistent: both consumers use the same version ID and decision hash. |
| Task 7 internal | Backend DTOs → TypeScript clients | Consistent: command and version fields match earlier tasks. |
| Task 8 internal | Typed clients → focused composables | Consistent: stale-response and optimistic-conflict behavior is explicit. |
| Task 9 internal | Version/draft state → document controls and views | Consistent: historical branching and active-version editing are distinct. |
| Task 10 internal | Decision/history/draft state → issue, search, and history UI | Consistent: replacement remains draft-only and undo remains server-backed. |
| Task 11 internal | Completed stack → E2E, layout, and feature matrix | Consistent: acceptance checks observable outcomes, not implementation proxies. |
| Tasks 1 → 2 | Version schema/domain → repositories | Clean; Task 2 consumes every required key and status. |
| Tasks 1 → 5 | Decision/suggestion/history schema → operation repository | Clean; persisted states and deletion command remain distinct. |
| Tasks 1 → 7 | Decision/version domain → frontend DTOs | Clean; Task 7 mirrors final replacement and optimistic revision. |
| Tasks 2 → 3 | Revision and analysis repositories → API routes | Clean; absent `version_id` retains active-version compatibility. |
| Tasks 2 → 4 | Version lifecycle → reanalysis worker | Clean; Task 4 adds only queued/analyzing execution behavior. |
| Tasks 2 → 5 | Version-scoped issues → decisions/history | Clean; historical decisions remain version-local. |
| Tasks 3 → 4 | Draft CRUD → reanalysis dispatch | Clean; reanalysis checks the submitted draft revision. |
| Tasks 3 → 6 | Version routes → derived routes | Clean; derived endpoints extend the same router and access boundary. |
| Tasks 3 → 7 | REST contracts → revisions client | Clean; paths, payloads, and errors have direct counterparts. |
| Tasks 4 → 8 | Version event stream → reanalysis progress state | Clean; request generations prevent stale terminal updates. |
| Tasks 5 → 6 | Stored final replacement → canonical derivation | Clean; Task 6 must not read the preferred suggestion again. |
| Tasks 5 → 7 | Atomic decision/history responses → TypeScript DTOs | Clean; batch ID and operation records are represented. |
| Tasks 5 → 8 | Decision/history API → workspace state | Clean; short and long undo use one operation batch. |
| Tasks 5 → 10 | Suggestions/history → review UI | Clean; edited candidates retain source IDs but store verbatim final text. |
| Tasks 6 → 7 | Derived response → TypeScript DTOs | Clean; both modified and diff carry the same snapshot hash. |
| Tasks 6 → 8 | Derived API → preview state | Clean; hash and generation guards cover independent staleness. |
| Tasks 6 → 9 | Derived blocks/diffs → document rendering | Clean; original highlight rendering remains separate. |
| Tasks 6 → 11 | Canonical derivation → preview/export parity E2E | Clean; acceptance compares normalized extracted output. |
| Tasks 7 → 8 | Typed API clients → composables | Clean; no new state-management dependency is introduced. |
| Tasks 7 → 10 | Analysis/revision types → issue/search/history components | Clean; `unreviewed` is available as a command only. |
| Tasks 8 → 9 | Version/draft/preview state → document UI | Clean; component events map to named composable methods. |
| Tasks 8 → 10 | Decision/history/draft state → interaction UI | Clean; both tasks share the orchestrator without duplicating state. |
| Tasks 8 → 11 | Stale guards and persistent state → lifecycle tests | Clean; E2E verifies the externally visible result. |
| Tasks 9 → 10 | `ReviewWorkspaceView` document modes → new tool panels | Clean; Task 10 extends rather than replaces Task 9 wiring. |
| Tasks 9 → 11 | Document controls → geometry/accessibility tests | Clean; existing one-screen constraint remains binding. |
| Tasks 10 → 11 | Complete interaction surface → final browser tests | Clean; history, search, and undo each have an acceptance assertion. |

## Task 1 review

Task 1: Ruling: The reviewer’s destructive `replace_analysis()` finding is real for the finished feature but is explicitly the deliverable of Task 2 (“Persist immutable analysis versions”), not Task 1’s schema/domain boundary. Do not pull repository lifecycle work forward; Task 2 remains blocked until it replaces this path and proves historical retention. Cost if wrong: Task 1’s interim commit can still overwrite history if used alone, but the branch is not releasable before Task 2.

Task 1: fix round 1/5 opened — align ORM-to-domain read fields and produce a real PostgreSQL migration test run.

Task 1: fix round 1/5 (2 addressed, 0 open — ORM hydration and PostgreSQL migration proof; commits 5a1b4a8..0dae830)

Task 1: complete (commits 22a5ca6..0dae830, review clean)

## Task 2 review

Task 2: fix round 1/5 opened — restore the configured PostgreSQL fixture path and enforce immutability at the low-level version-analysis write boundary.

Task 2: Ruling: Preserve the repository’s existing opt-in `TEST_DATABASE_URL` convention instead of permanently starting Docker from the session-scoped pytest fixture. Real PostgreSQL remains mandatory in task/final verification commands, but ordinary local tests without the variable continue to skip integration cases. Cost if wrong: developers without an explicit test database may miss integration regressions until CI or the final container gate.

Task 2: fix round 1/5 (2 addressed, 0 open — configured DB fixture and low-level immutability; commits 3b4004c..cb6745a)

Task 2: complete (commits 0dae830..cb6745a, review clean)

## Task 3 review

Task 3: minor (deferred): Initial RED evidence skipped because PostgreSQL was not configured; implementation behavior is covered by later real-PostgreSQL GREEN runs, but strict red-phase proof cannot be reconstructed.

Task 3: fix round 1/5 opened — make unknown version precedence deterministic and avoid revision churn for order-only equivalent draft updates.

Task 3: fix round 1/5 (2 addressed, 0 open — error precedence and semantic no-op revisions; commits f2cdd70..623b83d)

Task 3: complete (commits cb6745a..623b83d, review clean; 1 deferred minor)

## Task 4 review

Task 4: fix round 1/5 opened — correct container resource resolution, durable terminal failures, bounded idempotency, visible progress, expiration, duplicate dispatch, and missing regression/lint evidence. A fresh higher-capability implementer takes over because the original run exceeded five hours.

Task 4: fix round 1/5 (8 addressed, 0 open — production paths, terminal durability, idempotency, progress, expiry, dispatch, verification and lint; commits 76c5e86..4db22ca)

Task 4: complete (commits 623b83d..4db22ca, review clean)

## Task 5 review

Task 5: fix round 1/5 opened — support undo on historical versions, normalize empty suggestions consistently, and remove tracked SDD report artifacts.

Task 5: Ruling: Remove `.superpowers` artifacts from the branch head with a normal commit; do not rewrite the feature branch’s internal commit history merely to erase the two report-only commits. Cost if wrong: the scratch blob remains reachable in local commit history even though it is absent from the final tree.

Task 5: fix round 1/5 (3 addressed, 0 open — historical undo, blank suggestions, scratch artifact; commits abc0f99..1af3c7e)

Task 5: complete (commits 4db22ca..1af3c7e, review clean)

## Task 6 interruption

Task 6: Ruling: The first Task 6 implementer was cancelled after leaving uncommitted partial edits and no report. A fresh implementer must take ownership of the dirty Task 6 worktree, either complete those edits or replace them within Task 6 scope, then produce the normal report and commit. Cost if wrong: useful partial work may be discarded or a subtle partial assumption may survive, but the task review will gate the final diff.

## Task 6 review

Task 6: fix round 1/5 opened — preserve schema-v1 queued export warning semantics and replace the unreachable empty-replacement deletion test with real validator behavior.

Task 6: fix round 1/5 (2 addressed, 0 open — legacy warning planner and strict empty replacement validation; commits 9b0caa0..b94c504)

Task 6: fix round 2/5 opened — schema-v1 raw snapshots with legacy `custom` or null replacement decisions must deserialize before legacy planning, and v1/v2 planner selection must use `schema_version`.

Task 6: fix round 2/5 (2 addressed, 0 open — raw v1 decision compatibility and schema-version discriminator; commits b94c504..39e08ca)

Task 6: complete (commits 1af3c7e..39e08ca, review clean)

## Task 7 review

Task 7: fix round 1/5 opened — preserve stored final replacement in accepted commands and remove unsupported history pagination from the typed client.

Task 7: fix round 1/5 (3 addressed, 0 open — accepted decision command, history contract, live decision typing; commits 42b339e..b8a2f9b)

Task 7: complete (commits 39e08ca..b8a2f9b, review clean)

## Task 8 review

Task 8: fix round 1/5 opened — reanalysis idempotency, draft stale guards, authoritative history undo, active-version default semantics, decision response scoping, and derived hash guard testing.

Task 8: fix round 1/5 (4 addressed, 3 open — idempotency key lifetime, stale reanalysis after lifecycle change, stale history load race; commits e126f69..0043757)

Task 8: fix round 2/5 opened — keep reanalysis keys until lifecycle/revision changes, abort stale post-save reanalysis, and invalidate pending history loads on local mutation.

Task 8: fix round 2/5 (3 addressed, 0 open — idempotency key retention, stale reanalysis abort, history load invalidation; commits 0043757..3c5fc24)

Task 8: complete (commits b8a2f9b..3c5fc24, review clean)

## Task 9 review

Task 9: fix round 1/5 opened — prevent version switching while editing, dismiss SSE failure panels, surface draft-start errors, and clean edit-mode tab state.

Task 9: fix round 1/5 (4 addressed, 1 open — post-reanalysis control lock regression; commits 4f8c494..2ef3a13)

Task 9: fix round 2/5 opened — unlock document controls after successful reanalysis while preserving active edit locks and base-version guards.

Task 9: fix round 2/5 (1 addressed, 0 open — successful reanalysis unlock; commits 2ef3a13..6f68958)

Task 9: complete (commits 3c5fc24..6f68958, review clean)

## Task 10 review

Task 10: fix round 1/5 opened — preserve null/valid suggestion_id, scope find to visible draft mode, scope undo by version, and render local latest history batch.

Task 10: fix round 1/5 (4 addressed, 0 open — suggestion_id contract, hidden draft search, stale-version undo, latest history fallback; commits 9524815..677e52a)

Task 10: complete (commits 6f68958..677e52a, review clean)

## Task 11 review

Task 11: fix round 1/5 opened — strengthen backend preview/export content assertions and layout touch-target/editor containment acceptance coverage.

Task 11: fix round 1/5 (2 addressed, 0 open — explicit modified/export/undo content checks and active-control touch geometry; commits 9b0cf08..f22ca61)

Task 11: complete (commits 677e52a..f22ca61, review clean)

## Final review fix wave — 2026-08-24

Ruling: All five final-review findings are accepted. The implemented fixes are scoped to version-safe issue IDs, historical export request propagation, derived-content 409 mapping, per-batch history undo, and verification documentation. Docker/Linux full-suite verification remains blocked by the known PyPI TLS failure during container dependency resolution; Windows full backend verification still has the known WeasyPrint `libgobject-2.0-0` runtime gap for two PDF report unit tests.

Final fix wave complete (addressed 5/5):
- Version-scoped generated issue IDs now include the document revision for literal and shared-dictionary findings, with PostgreSQL reanalysis regression coverage for an unchanged finding across revision 1 and revision 2.
- Export creation requests now carry the selected workspace version through TypeScript types, `ExportPanel`, and `ReviewWorkspaceView`; backend snapshot tests cover requested historical versions.
- Derived-content validation and overlap failures from preview and export creation now return structured HTTP 409 responses with conflict issue IDs.
- Operation history exposes server-backed undo for each undoable batch in the selected version, while preserving the 10-second latest undo shortcut and conflict display.
- Feature matrix and this ledger document the Windows/PDF and Docker/Linux verification gaps.

## Final branch review

Final review: fix wave opened — version-scoped issue IDs, historical export version_id propagation, derived/export conflict 409s, per-batch history undo, and verification-gap documentation.

Final review: fix wave round 1 (3 addressed, 2 open — export stale response and per-batch undo stale response; commits f22ca61..0b57de7)

Final review: fix wave round 2 opened — scope export create and per-batch undo responses by version/generation.

Final review: fix wave round 2 (2 addressed, 0 open — historical export stale response and per-batch undo stale response; commits 0b57de7..3e4708b)

Final review: complete (commits 22a5ca6..3e4708b, review clean)
