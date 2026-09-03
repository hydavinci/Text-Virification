# Task 4 report — document review workflows

## Status

Completed on 2026-09-03 from base
`8bd4e6bfd61f526c23763380a2af85622234aacd`.

## Files

- Created `apps/web/src/components/workspace/ReviewActions.vue`.
- Created `apps/web/src/components/workspace/SearchReplacePanel.vue`.
- Created `apps/web/src/components/workspace/EditPreview.vue`.
- Created `apps/web/src/composables/useSearchReplace.ts`.
- Created focused component and composable tests.
- Extended `useVerificationWorkspace` with safe manual-revision session
  restoration.
- Integrated canonical review, search/replace, free edit, preview, session, and
  export fallback behavior into `WorkspaceView`.

## Delivered behavior

- `ReviewActions` is stateless with respect to decisions and history. It emits
  stable-ID selected actions, visible-filter batch actions, and canonical batch
  undo while displaying canonical counts, conflicts, and undo eligibility.
- Search uses explicit Unicode code-point `start`/`end` offsets, literal input,
  fixed-locale case-insensitive comparison, deterministic left-to-right
  non-overlapping matches, cyclic navigation, deletion, replace-current, and
  replace-all.
- Each successful search replacement invokes `saveManualEdit` exactly once.
  Free edits keep only a temporary component draft; unchanged and whitespace-
  only saves create no revision, while changed saves create one frozen manual
  draft parented to the current authored revision.
- Manual/search revisions clear source-bound decisions and batch history, hide
  stale filters/highlights/actions, clear navigation selection, and require
  re-verification. The current revision is the only post-edit text source.
- Modified export retains overlap conflict gating. Manual/search revisions use
  the current-text download fallback and never apply stale issue offsets;
  persisted original-format revision export remains Task 6.
- Frontend session schema version 2 serializes the current revision and
  re-verification state. Valid manual UUID drafts restore atomically without
  replaying stale decisions. Legacy sessions migrate differing `workingText`
  into one manual revision.
- Existing null suggestion (manual-only) and empty suggestion (deletion)
  behavior remains unchanged.

## TDD and validation evidence

- Fresh baseline:
  `npm test -- --run --reporter=dot` passed 185 tests across 10 files.
- Initial RED:
  `npm test -- ReviewActions.spec.ts SearchReplacePanel.spec.ts EditPreview.spec.ts useSearchReplace.spec.ts useVerificationWorkspace.spec.ts WorkspaceView.spec.ts --reporter=dot`
  failed 6 files. Five suites could not resolve the planned components or
  composable, and two workspace tests failed because
  `restoreWorkspaceState` did not exist; 63 existing tests passed.
- Restored-ID RED:
  `npm test -- useVerificationWorkspace.spec.ts --reporter=dot` failed 1 test
  with 65 passing because a non-UUID manual revision ID was accepted.
- Focused GREEN:
  `npm test -- ReviewActions.spec.ts SearchReplacePanel.spec.ts EditPreview.spec.ts useSearchReplace.spec.ts useVerificationWorkspace.spec.ts WorkspaceView.spec.ts --reporter=dot`
  passed 115 tests across 6 files.
- Full frontend GREEN:
  `npm test -- --run --reporter=dot` passed 209 tests across 14 files. Node
  emitted the existing experimental `localStorage` warning.
- Production build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3
  with 50 modules transformed.
- `git diff --check` passed with no output.

## Scope

No Task 5 result-loading/API changes or Task 6 backend revision persistence
were implemented.
