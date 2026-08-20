# Task 7 Report

## Summary
- Replaced the temporary non-desktop export fallback with a compact `ToolRail` bottom mode for every review layout at `<=1279px`.
- Added compact workspace state in `ReviewWorkspaceView` for document, issues, search, batch, and phone issue detail/list flows while keeping the desktop `>=1280px` shell intact.
- Extended `ReviewNavigation` so issue selection emits the real trigger element, then used it to restore focus when phone users return from issue details to the list.
- Preserved mounted compact panel state by switching views with `v-show`, kept checker-failure notices ahead of compact issue navigation, and kept export dialog focus restoration through the shared rail trigger.
- Updated breakpoints in `WorkspaceView.vue` and `DocumentViewer.vue`, plus refreshed focused/accessibility tests to cover the bottom rail, phone back navigation, and document header source name.

## Validation
- `npm test -- ReviewWorkspace.spec.ts WorkspaceView.spec.ts reviewAccessibility.spec.ts`
  - `Test Files  3 passed (3)`
  - `Tests  93 passed (93)`
- `npm run build`
  - `vite v6.4.3 building for production...`
  - `✓ built in 953ms`
- `npm test`
  - `Test Files  7 passed (7)`
  - `Tests  126 passed (126)`

## Self-review
- Checked `git diff --stat` and `git diff --check` to confirm the task stayed limited to the requested review workspace files and to catch whitespace issues before commit.
- Re-read the compact/phone template branches to verify the five-entry bottom rail replaces the temporary export path, the desktop shell remains unchanged, and the phone back action restores focus to the originating issue card.
- Verified the new tests cover the trigger-carrying `ReviewNavigation` event, compact panel persistence, phone issue detail return flow, focused suites, build, and full Vitest.

## Concerns
- None.

## Round 1/5 Fix
- Addressed the compact bottom-rail overflow by changing bottom mode in `apps/web/src/components/review/ToolRail.vue` from flex sizing to a five-column grid: `grid-template-columns: repeat(5, minmax(0, 1fr))`, with `.tool-rail__main` / `.tool-rail__footer` set to `display: contents` so all five controls occupy equal tracks.
- Bottom-mode buttons now use `min-width: 0` and `padding: 10px 4px` while the shared `.tool-rail__button` rule still keeps `min-height: 44px`; desktop rail sizing stays on the existing inline `width: 64px; flex: 0 0 64px` contract.
- Added `review workspace accessibility > ships a five-track bottom rail with shrinkable 44px controls` in `apps/web/tests/reviewAccessibility.spec.ts` to assert the five `minmax(0, 1fr)` tracks, shrinkable bottom buttons, and 44px minimum touch height.

### Exact evidence
- Red test before the fix:
  - `npm test -- reviewAccessibility.spec.ts`
  - `1 failed | 6 passed (7)`
  - `expected '\r\n  flex-direction: row;\r\n  align…' to contain 'display: grid'`
- Verification after the fix:
  - `npm test -- reviewShellComponents.spec.ts reviewAccessibility.spec.ts && npm run build`
  - `Test Files  2 passed (2)`
  - `Tests  13 passed (13)`
  - `vite v6.4.3 building for production...`
  - `✓ built in 1.01s`
