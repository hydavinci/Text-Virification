# Review Workspace Redesign — Final Fix Report

## Scope

Completed the four final-review findings as one fix wave. No backend API, composable contract, decision semantics, export lifecycle, or breakpoint values changed.

## Finding 1 — Compact highlight selection and deterministic Back

### Root cause

`selectHighlightAndShowDetails` only activated details when the compact Issues view was already active. Phone detail return also had a single list-only path and no way to refocus the regenerated selected highlight.

### RED

Command:

```powershell
Set-Location apps\web
npm test -- --run tests/ReviewWorkspace.spec.ts tests/reviewShellComponents.spec.ts
```

Result: **FAIL**, 6 failed / 75 passed. Relevant failures:

- `opens the compact issues view with selected details when a highlight is activated`
- `returns a phone highlight detail to the document focus and preserves overlap cycling`

The tablet test remained on Document; the phone test never opened the detail subview.

### Fix

- Compact highlight activation now always selects the Issues main view.
- At 768–1279, the selected IssuePanel is visible alongside the issue list.
- At <=767, the detail subview records whether it came from the document or issue list.
- Phone Back returns document-origin details to Document and focuses the current regenerated selected highlight.
- List-origin Back returns to the list and focuses the exact issue trigger.
- `DocumentViewer` exposes typed `focusSelectedHighlight()`.
- The phone overlap regression cycles `issue-a` to `issue-b` after returning to the originating highlight.

### GREEN

The focused review suite passed **89/89**, including both origins and overlap cycling.

## Finding 2 — Responsive state preservation

### Root cause

- Separate compact and desktop `ExportPanel` instances were inside the 1279/1280 `v-if` branches, so crossing the breakpoint unmounted polling and result state.
- Phone and tablet rendered separate `ReviewNavigation` and `IssuePanel` branches, so 767/768 transitions destroyed pending local drafts.

### RED

Relevant failing tests from the RED run:

- `preserves export polling and focus return across live 1279 and 1280 transitions`
  - Expected status polling after the transition; export API `get` had 0 calls.
- `preserves pending issue search and custom replacement drafts across live 767 and 768 transitions`
  - Pending issue search value was reset to an empty string.

### Fix

- `ReviewWorkspaceView` now mounts exactly one `ExportPanel` outside both responsive shells.
- Export trigger clicks pass the invoking element to the parent. Close focuses that trigger when connected, or the current responsive rail trigger after a breakpoint replacement.
- Export polling, warning, failure, and download state remain owned by the unchanged single `ExportPanel`.
- Compact Issues now has one stable `ReviewNavigation` and one stable `IssuePanel`; `v-show` changes phone/tablet presentation without remounting them.
- Live `matchMedia` test support dispatches real change listeners at 1279/1280 and 767/768.

### GREEN

- Queued export continued polling across 1279→1280, produced a download, retained it across 1280→1279, and returned focus to the current compact trigger.
- Pending 250 ms issue search and unsaved custom replacement drafts survived 767→768→767.

## Finding 3 — Export dialog keyboard isolation

### Root cause

Dialog keydown events bubbled to the workspace root. Non-editable dialog controls therefore activated the global `j`/`k` issue shortcuts.

### RED

`does not let export dialog key events trigger workspace issue shortcuts` failed after `j` on the dialog close button changed selection from issue 1.

### Fix

`onWorkspaceKeydown` now exits while `isExportOpen` is true. Dialog controls and background key events cannot change issue selection.

### GREEN

The regression passes for both a dialog control and the dialog background.

## Finding 4 — Desktop side-panel close focus

### Root cause

`WorkspaceSidePanel` used `v-show`; closing it hid the focused close button without moving focus.

### RED

`restores focus to the corresponding desktop rail tool after closing the side panel` failed because `document.activeElement` remained the hidden close button.

### Fix

- `ToolRail` now exposes typed `focusTool(tool)` alongside `focusExportButton()`.
- Closing the desktop side panel records the active side-panel tool and focuses its rail button after Vue updates the hidden panel.

### GREEN

The integration focus regression and ToolRail exposed-method coverage pass.

## Files changed

- `apps/web/src/components/review/DocumentViewer.vue`
- `apps/web/src/components/review/ToolRail.vue`
- `apps/web/src/views/ReviewWorkspaceView.vue`
- `apps/web/tests/ReviewWorkspace.spec.ts`
- `apps/web/tests/reviewAccessibility.spec.ts`
- `apps/web/tests/reviewShellComponents.spec.ts`
- `.superpowers/sdd/2026-08-19-review-workspace-redesign/final-fix-report.md`

## Iteration evidence

1. Baseline:

   ```powershell
   npm test -- --run tests/ReviewWorkspace.spec.ts
   ```

   Result: **70/70 passed** before adding regressions.

2. RED:

   ```powershell
   npm test -- --run tests/ReviewWorkspace.spec.ts tests/reviewShellComponents.spec.ts
   ```

   Result: **6 failed / 75 passed**; all six failures matched the requested missing behaviors.

3. First GREEN:

   ```powershell
   npm test -- --run tests/ReviewWorkspace.spec.ts tests/reviewShellComponents.spec.ts
   ```

   Result: **81/81 passed**.

4. Related accessibility contracts:

   ```powershell
   npm test -- --run tests/reviewAccessibility.spec.ts
   ```

   Initial result: **2 failed / 6 passed** because source assertions still required the removed duplicate compact export selector and static list-only Back label. After updating those structural contracts: **8/8 passed**.

5. Focused responsive browser verification:

   ```powershell
   npx playwright test --config playwright.config.ts tests/layout/reviewWorkspaceLayout.spec.ts --grep 'compact search controls|switches exactly'
   ```

   Result: **3/3 passed**.

6. Final focused review suites:

   ```powershell
   npm test -- --run tests/ReviewWorkspace.spec.ts tests/reviewShellComponents.spec.ts tests/reviewAccessibility.spec.ts
   ```

   Result: **89/89 passed**.

## Final verification

Command:

```powershell
Set-Location apps\web
npm test && npm run test:layout && npm run build && git -C C:\Work\text-verification\.worktrees\review-workspace-redesign -c core.whitespace=cr-at-eol diff --check
```

Results:

- `npm test`: **7 files, 133/133 tests passed**
- `npm run test:layout`: **7/7 Playwright tests passed**
- `npm run build`: **PASS**, Vue type-check and Vite production build; 71 modules transformed
- `git -c core.whitespace=cr-at-eol diff --check`: **PASS**, exit code 0 with no output

## Self-review

- Confirmed one `ExportPanel` mount in source and no duplicated export business state.
- Confirmed one compact `ReviewNavigation` and one compact `IssuePanel` subtree across 767/768.
- Confirmed phone Back behavior is origin-specific and focus-safe.
- Confirmed overlap cycling still advances after returning to the document.
- Confirmed export polling timers remain inside unchanged `ExportPanel` lifecycle code.
- Confirmed desktop rail behavior, compact five-item navigation, 44 px targets, API/composable interfaces, and exact 767/768 and 1279/1280 breakpoints remain intact.
- Reviewed the diff for unrelated refactors; changes are limited to responsive composition, focus routing, keyboard guarding, and regression coverage.

## Concerns

None known.
