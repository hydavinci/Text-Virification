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
