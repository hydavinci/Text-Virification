# Task 1 report — typed review workspace API clients

## Status

Completed in the current workspace and committed as `e1b77f2` on top of base `b075261`.

## Files

Committed Task 1 files only:

- `apps/web/src/api/jobs.ts`
- `apps/web/src/api/analysis.ts`
- `apps/web/src/api/exports.ts`
- `apps/web/src/api/client.ts`
- `apps/web/src/types/jobs.ts`
- `apps/web/src/types/review.ts`
- `apps/web/src/types/analysis.ts`
- `apps/web/src/types/api.ts`
- `apps/web/src/types/exports.ts`
- `apps/web/src/main.ts`
- `apps/web/tests/jobsApi.spec.ts`
- `apps/web/tests/analysisApi.spec.ts`
- `apps/web/tests/exportsApi.spec.ts`

Preserved and left unstaged per instruction:

- `apps/web/src/App.vue`
- `apps/web/src/components/JobProgress.vue`
- `apps/web/src/components/UploadWorkspace.vue`
- `apps/web/src/views/WorkspaceView.vue`
- `apps/web/tests/WorkspaceView.spec.ts`

## RED command / output reason

Command:

```powershell
Set-Location apps\web
npm test -- --run tests/analysisApi.spec.ts tests/exportsApi.spec.ts tests/jobsApi.spec.ts
```

Observed RED output:

- `tests/analysisApi.spec.ts`: failed to resolve import `../src/api/analysis`
- `tests/exportsApi.spec.ts`: failed to resolve import `../src/api/exports`
- `tests/jobsApi.spec.ts`: failed to resolve import `../src/types/api`

Reason: the typed analysis/export clients and shared structured API error types did not exist yet, which is the missing Task 1 behavior the new tests were written to drive.

## GREEN commands / results

Focused API specs:

```powershell
Set-Location apps\web
npm test -- --run tests/analysisApi.spec.ts tests/exportsApi.spec.ts tests/jobsApi.spec.ts
```

Result: PASS — `3` files, `26` tests passed.

Frontend build:

```powershell
Set-Location apps\web
npm run build
```

Result: PASS — `vue-tsc -b && vite build` completed successfully and emitted the production bundle.

## Commit

- `e1b77f2` — `feat: add typed review workspace clients`

## Self-review

- Reviewed only the Task 1 source/test diff before commit.
- Confirmed `JobsApi` still uses `fetch.call(globalThis, ...)`.
- Centralized JSON request/error handling preserves structured backend `detail.code`, `detail.message`, and export confirmation `detail.warnings` via `ApiError`, while remaining compatible with existing `Error.message` consumers.
- Added typed analysis and export clients plus Vue injection keys in `main.ts`.
- Staged only Task 1 files; unrelated accepted UI baseline files remain unstaged.

## Concerns

- `JobRead.scenario` and `enabled_categories` are typed as optional on the UI side so the accepted unstaged `WorkspaceView.spec.ts` baseline can remain untouched while the committed Task 1 files still build cleanly. Backend responses remain authoritative and are expected to include both fields.

---

## Fix round 1/5 — tighten review API contracts

### Status

Implemented in the current workspace for review follow-up on top of `e1b77f2`.

### Findings addressed

- Restored `JobRead.scenario` and `JobRead.enabled_categories` to the exact required wire contract.
- Replaced broad decision action/replacement typing with exact discriminated unions for commands, issue summaries, and applied decisions.
- Tightened structured API error narrowing so malformed warning entries no longer survive as typed export warnings.

### Files

- `apps/web/src/types/jobs.ts`
- `apps/web/src/types/analysis.ts`
- `apps/web/src/api/client.ts`
- `apps/web/tests/jobsApi.spec.ts`
- `apps/web/tests/analysisApi.spec.ts`
- `apps/web/tests/exportsApi.spec.ts`
- `apps/web/tests/WorkspaceView.spec.ts` — minimal fixture-only update so the exact `JobRead` contract still compiles under `vue-tsc`

### RED command / output reason

Command:

```powershell
Set-Location apps\web
npm test -- --run tests/exportsApi.spec.ts
```

Observed RED output:

- `tests/exportsApi.spec.ts`: `falls back when confirmation warnings are malformed` failed because the structured error guard still accepted `warnings` arrays containing non-string fields and preserved the malformed backend payload as typed warning data.

### GREEN commands / results

Focused API specs:

```powershell
Set-Location apps\web
npm test -- --run tests/analysisApi.spec.ts tests/exportsApi.spec.ts tests/jobsApi.spec.ts
```

Result: PASS — `3` files, `27` tests passed.

Frontend build:

```powershell
Set-Location apps\web
npm run build
```

Result: PASS — `vue-tsc -b && vite build` completed successfully and emitted the production bundle.

### Self-review

- Verified the runtime regression with a RED malformed-warning export test before tightening the guard.
- Updated committed API test fixtures to model the exact `JobRead` and decision wire shapes at compile time instead of weakening types.
- Limited the unrelated baseline touch to the existing `WorkspaceView.spec.ts` local `buildJobRead` helper because `apps/web/tsconfig.json` type-checks `tests/**/*.ts` during the build.

### Concerns

- `apps/web/tests/WorkspaceView.spec.ts` already contained unrelated unstaged baseline edits; only the `buildJobRead` fixture contract adjustment is part of this fix round and should be the only staged hunk from that file.
