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
- Restores exact pre-batch state, including absent versus explicit properties.
- Exposes computed modified text, visible issues, review summary, frozen document revisions, manual revision creation, and re-verification state.
- Models source revisions as explicitly non-persisted (`revision_id: null`, `revision_number: 0`, `created_at: null`) and review/manual drafts as client-generated UUID revisions with run identity, positive per-result sequence numbers, source version, and ISO timestamps.
- Adds backend-compatible image, PDF, OCR, JSON metadata, and revision types while retaining legacy aliases only for compatibility.

## Tests and validation

- Original Task 1 RED: the focused suite was written first and observed failing on the missing composable.
- Independent-review fix RED: `npm test -- useVerificationWorkspace.spec.ts` failed with 20 failed and 3 passed tests. Failures showed production-shaped checker source versions being discarded, code-point offsets rejected, stale defaults copied into overrides, missing revision persistence fields/UUIDs, and state leaking across run identity.
- Independent-review fix GREEN: `npm test -- useVerificationWorkspace.spec.ts` passed 23 tests in 1 file.
- Final `npm test -- --run`: 54 tests passed across 4 files.
- Final `npm run build`: `vue-tsc -b` and Vite 6.4.3 production build passed; 22 modules transformed.
- The full test run emitted Node's existing experimental `localStorage` availability warning; all tests passed.

## Commit

- Original subject: `feat: add stable verification workspace state`
- Independent-review fix subject: `fix: align workspace state with canonical results`
- Scope: Task 1 tracked files and required SDD ledger/report only.
- Attribution: required Copilot co-author and session trailers are included in this commit.
