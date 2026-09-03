# Task 3 report — document and issue navigation views

## Status

Completed on 2026-09-03 from base
`3afe0cebcb39de0523d7519de9957f8f395484ad`.

## Files

- Created `apps/web/src/components/workspace/DocumentViewer.vue`.
- Created `apps/web/src/components/workspace/IssueList.vue`.
- Created `apps/web/src/components/workspace/IssueDetails.vue`.
- Created `apps/web/src/composables/useIssueNavigation.ts`.
- Created `apps/web/tests/DocumentViewer.spec.ts`.
- Created `apps/web/tests/IssueNavigation.spec.ts`.
- Updated `apps/web/src/views/WorkspaceView.vue`.
- Updated `apps/web/tests/WorkspaceView.spec.ts`.
- Added the reset method required by integration to
  `useVerificationWorkspace` and its focused test.
- Updated the Vue redesign progress ledger.

## Delivered behavior

- Source documents render exclusively through Vue text nodes. The legacy
  `v-html` path and index-based source markers were removed.
- Sentence mode renders numbered source lines while retaining exact spaces,
  blank lines, newlines, and trailing newlines. Continuous mode renders the
  same exact source in one flow.
- Source slicing and segmentation use Unicode code points, matching canonical
  Python offsets even when text contains astral characters.
- Crossing and nested overlaps are split at every canonical boundary. Text is
  rendered once in non-crossing segments, overlapping segments are visibly
  distinguished, and each issue receives one focusable source marker keyed by
  `data-issue-id`.
- Source markers and issue-list controls select the same stable `issue_id`.
  Both expose `aria-current`, keyboard activation, visible focus treatment,
  and stable `data-issue-id`/`data-issue-role` attributes.
- Selection scrolls both the source marker and issue-list control after Vue
  renders. Calls are guarded when `scrollIntoView` is unavailable.
- `selectOffset` uses half-open ranges (`start <= offset < end`). For overlaps,
  the shortest containing interval wins, followed by canonical
  `start`, `end`, and `issue_id` ordering. Invalid and unmatched offsets clear
  selection.
- Severity and layer filters compose without mutating the frozen canonical
  issue array. A still-visible selection is retained; otherwise the next
  canonical visible issue is selected, then the nearest prior issue, then
  `null`.
- `IssueDetails` distinguishes a nonempty suggestion, an empty-string
  deletion, and a `null` manual-only issue. Alternatives are deduplicated,
  never repeat the primary suggestion, remain selectable for manual-only
  issues, and mark the first actual alternative as recommended.
- Review state, suggestion overrides, batch actions, session state, preview,
  and export now use stable issue IDs through `useVerificationWorkspace`.
  Tracked-text fallback export converts canonical code-point offsets to UTF-16
  only at the JavaScript string boundary.
- `clearResult()` resets canonical result and stable-ID state so the existing
  workspace reset action cannot leak review decisions into a later analysis.
- Existing input, settings, terminology, analysis, job progress, summary,
  edit/search controls, export entry points, theme, privacy, and session
  behavior remain in place. Task 4 and Task 5 redesigns were not implemented.

## TDD evidence

- Fresh baseline:
  `npm test -- --run --reporter=dot` passed 132 tests across 8 files.
- Initial RED:
  `npm test -- DocumentViewer.spec.ts IssueNavigation.spec.ts` failed both
  suites because the planned components did not exist.
- Workspace integration RED: the focused WorkspaceView test failed because
  `DocumentViewer` and `IssueList` were not rendered.
- Canonical tracked-export RED: the regression test received
  `😀甲【删除：错】【替换为：正】乙错` instead of changing the issue at code-point
  offset 4.
- Additional focused REDs covered accepted/rejected source marker state,
  manual-only selection of a single alternative, arbitrary overlap styling,
  and canonical workspace reset.
- Focused GREEN:
  `npm test -- DocumentViewer.spec.ts IssueNavigation.spec.ts WorkspaceView.spec.ts useVerificationWorkspace.spec.ts --reporter=dot`
  passed 87 tests across 4 files.
- WorkspaceView GREEN:
  `npm test -- WorkspaceView.spec.ts --reporter=dot` passed 17 tests.
- Full frontend GREEN:
  `npm test -- --run --reporter=dot` passed 152 tests across 10 files. Node
  emitted the existing experimental `localStorage` warning.
- Build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3 with
  40 modules transformed.
- `git diff --check` passed with no output.

## Scope

The Task 3 commit contains only the document/issue components, issue-navigation
composable, stable-ID workspace integration and reset support, focused tests,
and Task 3 SDD evidence. It does not implement the Task 4 search/free-edit
redesign or the Task 5 API/execution redesign.

## Review fixes — 2026-09-03

- Modified export now fails closed before either text-download fallback or
  `exportOriginal` when accepted effective replacements overlap. The
  deterministic toast is
  `存在重叠的已接受修改，请先解决冲突后再导出`.
- Workspace batch accept/reject and undo now delegate to the canonical
  identity-bound composable operations. The sealed reactive
  `canUndoLastBatch` facade drives the undo affordance and clears on result
  load, reset, manual revision, undo, and session restoration.
- Overlapping batch acceptance is one atomic state transition. Conflicts are
  exposed without publishing an intermediate partial revision, and exact undo
  restores property absence versus explicit state.
- Filter fallback now locates the hidden selection in full canonical
  `orderedIssues`, then chooses the first visible issue after it, the nearest
  visible issue before it, or `null`.
- Global document scrolling was removed from `useIssueNavigation`.
  `DocumentViewer` and `IssueList` now schedule role-specific scrolling inside
  their own roots, run on mount/remount as well as selection changes, guard
  unsupported `scrollIntoView`, and discard stale scheduled IDs.
- Added crossing, nested, identical, and empty-source coverage for conflict
  export and exact-once source segmentation without changing Task 4-6 scope.

### Review-fix TDD and validation evidence

- Focused pre-fix baseline:
  `npm test -- DocumentViewer.spec.ts IssueNavigation.spec.ts useVerificationWorkspace.spec.ts WorkspaceView.spec.ts --reporter=dot`
  passed 87 tests across 4 files.
- RED: the same focused command failed with 22 failures and 89 passes after
  adding the regressions. Failures covered missing conflict export gating,
  missing canonical undo eligibility, non-atomic View-local batching, stale
  filter fallback, global composable scrolling, and mount/remount-safe
  component scrolling. The segmentation-only cases were already green.
- Focused GREEN: the focused command passed 111 tests across 4 files.
- Full frontend GREEN:
  `npm test -- --run --reporter=dot` passed 176 tests across 10 files. Node
  emitted the existing experimental `localStorage` warning.
- Production build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3
  with 40 modules transformed.
- `git diff --check` passed with no output.

The review-fix commit remains limited to Task 3 navigation/export hardening,
the Task 1 composable facade needed by that integration, focused regressions,
and these evidence updates. Tasks 4-6 remain unimplemented.

## Review fixes — round 2 — 2026-09-03

- Exposed `setIssueStates(issueIds, state)` as the canonical general batch
  operation. `WorkspaceView` now uses exactly one call for accept all, reject
  all, and reset all.
- Every valid all-action pushes one identity-bound exact snapshot. Batch
  history is a LIFO stack: after accept all then reset all, the first undo
  restores accepted states and the second undo restores the state before
  accept all, including property absence versus explicit `pending`.
- Existing new-result, clear/reset, and manual-revision boundaries continue to
  clear the complete batch stack. Overlapping accepted batches remain one
  atomic transition and never publish a partial replacement revision.
- Added `restoreReviewState(...)` as the canonical versioned session-restore
  boundary. It requires the loaded document/run/source identity, retains only
  current safe issue IDs, validates decision values, and accepts only string
  or `null` suggestion overrides while preserving explicit `""` and `null`.
- Restore replaces both stable-ID maps synchronously, clears batch history,
  and attempts revision creation only after both maps are installed.
  Conflicting crossing or nested accepted replacements expose canonical
  conflicts while retaining the prior/source revision and text.
- `WorkspaceView.restoreSession()` now loads the result and invokes the atomic
  restore API once. It no longer replays decisions or suggestions one entry at
  a time, and no index fallback was introduced.

### Fix-round-2 TDD and validation evidence

- Focused pre-change baseline:
  `npm test -- useVerificationWorkspace.spec.ts WorkspaceView.spec.ts --reporter=dot`
  passed 82 tests across 2 files.
- Batch RED: the same command failed 2 tests with 82 passing. One failure
  showed the public canonical batch method was absent; the other showed reset
  all removed properties without becoming the latest undoable batch.
- Batch GREEN: the same command passed 84 tests across 2 files.
- Restore RED: the same command failed 7 tests with 84 passing. The failures
  reproduced crossing/nested partial restored revisions, a multi-revision
  nonconflicting restore, and the missing canonical restore validation API.
- Focused GREEN: the same command passed 91 tests across 2 files.
- All Task 3 tests:
  `npm test -- DocumentViewer.spec.ts IssueNavigation.spec.ts useVerificationWorkspace.spec.ts WorkspaceView.spec.ts --reporter=dot`
  passed 120 tests across 4 files.
- Full frontend GREEN: `npm test -- --run --reporter=dot` passed 185 tests
  across 10 files. Node emitted the existing experimental `localStorage`
  warning.
- Production build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3
  with 40 modules transformed.
- `git diff --check` passed with no output.

### Ledger line semantics

After review, the controller can record this wave as:

`Task 3: fix round 2/5 (2 addressed, 0 open — atomic all-action history and atomic versioned session restore; commits 97303cd..<round-2-sha>)`

This line records the numbered fix wave and resolved findings; it is not the
Task 3 completion line. The controller will add completion only after the
round-2 commit passes review.

Ruling: Batch history is a LIFO stack of identity-bound exact snapshots, not a
single undo slot — each all-action becomes the latest reversible operation,
while a second undo intentionally reaches the preceding batch; cost if wrong
is retaining multiple small state snapshots until a result/reset/manual-edit
boundary clears them.

Ruling: Session restore is one versioned composable transition after
`loadResult`, with both validated maps installed before conflict detection and
revision creation — replaying entries individually can publish a partial
revision before a later overlap is known; cost if wrong is discarding malformed
or stale saved entries instead of attempting best-effort index recovery.
