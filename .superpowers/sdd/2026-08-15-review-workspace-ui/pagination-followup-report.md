# Pagination follow-up bugfix report

## Status

- Branch: `task-3-review-workspace`
- Scope: frontend authoritative issue-page reconciliation and pagination visibility only
- Result: fixed and verified

## Phase 1 — exact data flow and reproduction

### Successful single decision

1. `decide()` builds a command for `selectedIssue`.
2. `submitDecision()` increments that issue's decision generation, applies an optimistic decision, and calls `putDecisions()`.
3. An `applied` outcome updates the local and cached authoritative decision.
4. `reloadAuthoritativeIssues()` and `loadSummary()` run together.
5. The issue reload increments the page-level `issueGeneration`, requests the current filters with `cursor: null` and `limit: 50`, checks the page generation, then calls `reconcileAuthoritativeIssuePage()`.

### Successful batch decision

1. `decideVisible()` builds commands from the visible filtered issues.
2. `submitDecisionBatch()` assigns a per-issue generation and optimistic decision to every command.
3. Current outcomes become reload guards, including successful outcomes.
4. The same authoritative filtered first-page reload and summary refresh run together.

### Pre-fix reconciliation

`reconcileAuthoritativeIssuePage()` cloned the existing `issuesById` and `issueIds`, then updated or removed only still-current guarded issue IDs. It did not insert other rows from the returned page or adopt the response order, but it did assign `response.next_cursor`.

For a full filtered page containing issues 1–50, deciding issue 1 and receiving an authoritative first page containing issues 2–51 therefore left local issues 2–50 while advancing to the cursor after issue 51. Issue 51 was missing and subsequent pagination skipped it.

The distinct empty-local case occurred when all guarded rows were removed while the authoritative response still supplied a next cursor. `ReviewNavigation` rendered pagination only when `issues.length > 0`, so the cursor was unreachable.

### Focused reproduction

The regression uses an API-shaped 50-item filtered page. After issue 1 is accepted, the authoritative response contains 50 rows including backfilled issue 51, a changed response order, and a next cursor. A follow-up page contains issue 52.

An additional batch regression returns an empty authoritative page with a next cursor after all visible rows are applied, then returns issue 3 from that cursor.

## Phase 2 — invariant comparison

Normal `loadIssuePage(null, false)` / `applyIssuePage(response, false)`:

- starts from empty `issuesById` and `issueIds`;
- inserts every response row;
- adopts authoritative response order;
- clears and rebuilds authoritative decision snapshots;
- assigns the cursor from that same applied page;
- repairs selection against the replacement page.

Pre-fix guarded reconciliation:

- started from the old local maps and order;
- touched only current guarded IDs;
- omitted backfilled/unseen authoritative rows;
- retained stale first-page rows and their old order;
- nevertheless assigned the new response cursor.

The broken invariant was that `issueIds`/`issuesById` represented one page while `issueCursor` represented a different authoritative page.

## Phase 3 — root-cause hypothesis

**Hypothesis:** the bug is caused by treating an authoritative first-page response as a guard-only patch while treating its cursor as a full-page replacement cursor. Rebuilding state from the response, with only newer per-issue generations overlaid for race protection, should restore the page/cursor invariant.

The focused RED validated the hypothesis:

- issue 51 was absent after the authoritative reload;
- the empty-local state exposed the false terminal empty message and hid pagination.

## Phase 4 — TDD fix

### RED evidence

An initial test command from the repository root failed with `ENOENT` for `package.json` and was discarded as a command error, not product RED.

Corrected command:

```powershell
Set-Location C:\Work\text-verification\apps\web
npm test -- ReviewWorkspace.spec.ts -t "applies the authoritative filtered first page before advancing its cursor|keeps authoritative pagination reachable when all applied rows leave the page empty"
```

Result before production edits: expected RED — `2` tests failed.

- Backfill test: issue 51 did not exist.
- Empty-page test: the terminal empty state was shown and pagination was not reachable.

### Implementation

- Kept the existing page-level `issueGeneration` request guard and current-decision guard gate unchanged.
- Rebuilt `issuesById`, `issueIds`, and authoritative decision snapshots from every row in the authoritative response.
- Adopted the response's exact row order and inserted backfilled rows.
- Removed still-current guarded rows absent from the response.
- Preserved local rows and decision snapshots for guarded issue IDs whose per-issue generation advanced while the reload was in flight; protected rows absent from the stale response remain temporarily reachable until their newer flow settles.
- Assigned `issueCursor` only while applying that authoritative page.
- Allowed pagination to render whenever a next cursor exists, even with zero local rows, and suppressed the false terminal empty message in that state.
- Did not change filter generations, issue page race checks, request parameters, or backend code.

### GREEN evidence

Focused regressions: PASS — `2` tests passed.

Review workspace spec:

```powershell
npm test -- ReviewWorkspace.spec.ts
```

PASS — `50` tests.

Accessibility spec:

```powershell
npm test -- reviewAccessibility.spec.ts
```

PASS — `3` tests.

Full frontend suite:

```powershell
npm test
```

PASS — `6` files, `97` tests.

Production build:

```powershell
npm run build
```

PASS — `vue-tsc -b && vite build`; 59 modules transformed.

## Preserved invariants

- `issueIds` order reflects the applied authoritative first page.
- Every ordinary response row is present in `issuesById`.
- Backfilled rows are not skipped by the response cursor.
- Current guarded decisions are authoritatively updated or removed.
- Newer guarded per-issue generations are not overwritten or deleted by a stale reload.
- `issueCursor` belongs to the exact authoritative page applied to local state, subject only to the explicit newer-generation overlay.
- Pagination remains reachable when the applied page is empty but has a next cursor.
- Filter request generations and page race guards remain intact.

## Files

- `apps/web/src/composables/useReviewWorkspace.ts`
- `apps/web/src/components/review/ReviewNavigation.vue`
- `apps/web/tests/ReviewWorkspace.spec.ts`
- `.superpowers/sdd/2026-08-15-review-workspace-ui/pagination-followup-report.md`

## Concerns

- None.

## Fix Round 1 — concurrent decision generations and loading announcement

### Root cause

- Authoritative reload reconciliation only derived protected issue IDs from
  `requestedGuards`. A decision generation that advanced for another loaded issue
  while the request was pending could therefore be overwritten or removed by the
  older page.
- An empty page with a next cursor rendered both the initial empty-list loading
  status and the pagination loading status.

### RED evidence

```powershell
Set-Location C:\Work\text-verification\apps\web
npm test -- ReviewWorkspace.spec.ts -t "preserves an unrelated newer decision while applying a stale authoritative page and cursor|keeps authoritative pagination reachable when all applied rows leave the page empty"
```

Expected RED — `2` tests failed:

- The stale authoritative page returned `issue-3` and `issue-1`, but removed the
  newer optimistic decision for unrelated `issue-2`.
- The empty paginated loading state exposed both `正在加载问题…` and
  `正在加载更多问题…` live announcements.

### GREEN implementation

- Snapshotted decision generations for every currently loaded issue when an
  authoritative reload starts.
- While applying the response, preserved each loaded issue whose generation
  advanced beyond that snapshot, regardless of whether it appeared in the
  reload's requested guards.
- Kept authoritative response order, backfilled rows, cursor, checker failures,
  and still-current guarded-row reconciliation unchanged.
- Suppressed the initial empty-list loading live region when a next cursor makes
  the pagination live region authoritative.

### GREEN evidence

- Focused regressions: PASS — `2` tests.
- `npm test -- ReviewWorkspace.spec.ts`: PASS — `51` tests.
- `npm test -- reviewAccessibility.spec.ts`: PASS — `3` tests.
- `npm test`: PASS — `6` files, `98` tests.
- `npm run build`: PASS — `vue-tsc -b && vite build`; 59 modules transformed.

### Concerns

- None.
