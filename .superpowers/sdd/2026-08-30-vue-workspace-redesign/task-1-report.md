# Task 1 report — stable-ID verification workspace

## Files

- Created `apps/web/src/composables/useVerificationWorkspace.ts`.
- Created `apps/web/tests/useVerificationWorkspace.spec.ts`.
- Updated `apps/web/src/types/verification.ts`.
- Updated the Vue redesign progress ledger with implementation evidence and rulings.

## Behavior

- Stores decisions and explicit suggestion overrides by `issue_id`; untouched issues always use the current backend suggestion.
- Preserves matching decisions and explicit overrides only for the same `document_id`, document `source_version`, and `verification_run_id`. Missing IDs and different result identities reset or prune state.
- Treats issue `source_version` as checker/rule provenance rather than document identity. Canonical issue ownership remains enforced by `document_id` and `verification_run_id`.
- Validates canonical Python Unicode code-point `start`/`end` and block-local offsets, converting them to UTF-16 indices only for JavaScript slicing and replacement. Wire offsets remain unchanged.
- Applies accepted effective suggestions in descending canonical offsets, including deletion for `''`, while treating `null` as no automatic replacement.
- Retains all individually canonical overlapping findings in `visibleIssues` and `summary`; duplicate `issue_id` payloads are still selected deterministically.
- Detects overlap only among accepted issues with effective non-null suggestions and exposes reactive `replacementConflictIssueIds` plus `hasReplacementConflicts`.
- Fails closed on conflicting replacements: it keeps the last valid revision/text, creates no arbitrary partial draft, and resumes revision generation after rejection, undo, or suggestion changes resolve the conflict.
- Restores exact pre-batch state, including absent versus explicit properties.
- Exposes computed modified text, visible issues, review summary, frozen document revisions, manual revision creation, and re-verification state.
- Models revisions as a strict source/draft/persisted union. Source and draft revisions use `revision_number: null`; review/manual drafts use client UUIDs, run/source identity, ISO timestamps, and `persistence_state: 'draft'`. Positive numbers are reserved for server-returned persisted revisions.
- Removes per-instance revision numbering while retaining UUID noncollision and `parent_revision_id` chaining to the prior valid non-source revision.
- Adds backend-compatible image, PDF, OCR, JSON metadata, and revision types while retaining legacy aliases only for compatibility.

## Tests and validation

- Original Task 1 RED: the focused suite was written first and observed failing on the missing composable.
- Independent-review fix RED: `npm test -- useVerificationWorkspace.spec.ts` failed with 20 failed and 3 passed tests. Failures showed production-shaped checker source versions being discarded, code-point offsets rejected, stale defaults copied into overrides, missing revision persistence fields/UUIDs, and state leaking across run identity.
- Independent-review fix GREEN: `npm test -- useVerificationWorkspace.spec.ts` passed 23 tests in 1 file.
- Final `npm test -- --run`: 54 tests passed across 4 files.
- Final `npm run build`: `vue-tsc -b` and Vite 6.4.3 production build passed; 22 modules transformed.
- The full test run emitted Node's existing experimental `localStorage` availability warning; all tests passed.

### Second scoped review

- Finding: canonical overlap suppression hid valid findings emitted by different backend rules.
- Finding: applying multiple accepted overlapping replacements would require an arbitrary winner and could not safely update review text.
- Finding: local positive revision sequences conflict with the backend's unique per-run numbering when independent browser instances persist drafts.
- RED: `npm test -- useVerificationWorkspace.spec.ts` failed with 8 failed and 19 passed tests (27 total).
- GREEN: `npm test -- useVerificationWorkspace.spec.ts` passed 27 tests in 1 file; final effective-null conflict coverage increased the focused suite to 28 passing tests.
- Final `npm test -- --run`: 59 tests passed across 4 files.
- Final `npm run build`: `vue-tsc -b` and Vite 6.4.3 passed with 22 modules transformed.
- Final behavior: overlapping findings remain visible/countable; accepted replacement conflicts expose both deterministic IDs and preserve the last valid text; non-overlapping code-point replacements remain descending and astral-safe; local review/manual revisions are UUID drafts with null revision numbers.
- Task 6 persistence boundary: the browser sends draft UUID/text/run/source metadata, while the backend allocates the positive per-run number under database locking and returns the persisted revision.

## Commit

- Original subject: `feat: add stable verification workspace state`
- Independent-review fix subject: `fix: align workspace state with canonical results`
- Second scoped-review fix subject: `fix: preserve overlapping verification issues`
- Scope: Task 1 tracked files and required SDD ledger/report only.
- Attribution: required Copilot co-author and session trailers are included in this commit.
