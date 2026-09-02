# Task 1 report — stable-ID verification workspace

## Files

- Created `apps/web/src/composables/useVerificationWorkspace.ts`.
- Created `apps/web/tests/useVerificationWorkspace.spec.ts`.
- Updated `apps/web/src/types/verification.ts`.
- Updated the Vue redesign progress ledger with implementation evidence and rulings.

## Behavior

- Stores decisions and selected suggestions by `issue_id`.
- Preserves only matching IDs for the same document/source revision and resets state across source identities.
- Validates canonical ownership, `start`/`end`, source slices, and block mappings; safely excludes duplicate, stale, overlapping, and invalid issues.
- Applies accepted replacements in descending offsets, including deletion for `''`, while treating `null` as no automatic replacement.
- Restores exact pre-batch state, including absent versus explicit properties.
- Exposes computed modified text, visible issues, review summary, frozen document revisions, manual revision creation, and re-verification state.
- Adds backend-compatible image, PDF, OCR, JSON metadata, and revision types while retaining legacy aliases only for compatibility.

## Tests and validation

- The focused suite was written first and observed failing on the missing composable.
- `npm test -- useVerificationWorkspace.spec.ts`: 12 tests passed.
- Final `npm test -- --run`: 43 tests passed across 4 files.
- `npm run build`: `vue-tsc -b` and Vite production build passed.
- Fresh pre-change frontend baseline: 31 tests passed.

## Commit

- Subject: `feat: add stable verification workspace state`
- Scope: Task 1 tracked files and required SDD ledger/report only.
- Attribution: required Copilot co-author and session trailers are included in this commit.
