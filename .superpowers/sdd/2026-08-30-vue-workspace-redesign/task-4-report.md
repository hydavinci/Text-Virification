# Task 4 report — document review workflows

## Status

Completed on 2026-09-03 from base
`8bd4e6bfd61f526c23763380a2af85622234aacd`.
Independent review findings were fixed on 2026-09-03 from Task 4 HEAD
`b4964e9293bb1654d8ab30b41043784eab35de9b`.
Fix round 2 was completed on 2026-09-03 from Task 4 fix-round-1 HEAD
`e40192e3aff3541180cc7143deed6a2606fd49b5`.
Fix round 3 was completed on 2026-09-03 from Task 4 fix-round-2 HEAD
`85b5e4592a6d4cabaa8f2104084e4fa1ac7a6a2f`.
Fix round 4 was completed on 2026-09-03 from Task 4 fix-round-3 HEAD
`6212a58f4b798c23c1db5c1e89cee259341703a1`.

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

## Independent review fixes

- Replaced fixed-code-point-window collation with deterministic per-code-point
  NFKD and locale-stable case folding. Folded boundaries map back to original
  code-point ranges, supporting ligatures, sharp-s, and composed/decomposed
  equivalents while rejecting half-expansion matches.
- Made identical replace-current, replace-all, and manual-edit operations true
  no-ops. They create no revision, notification, decision reset, or undo reset.
- Added immutable edit-base tracking. A prop/revision change during editing
  marks a conflict, disables save, preserves the newer revision, and requires
  cancel/reopen with focus restoration.
- Replaced shallow staged session restoration with one canonical atomic
  `restoreWorkspaceState` path. It constructs fresh deeply frozen result,
  block, issue, metadata, revision, and null-prototype map values; validates
  UUIDs, enums, discriminants, timestamps, ownership, revision ancestry, and
  source/review/manual consistency; preserves valid draft identities; migrates
  legacy sessions atomically; and commits refs only after complete success.
- Disabled and defensively guarded report export while re-verification is
  required.
- Rechecks now retain only a safe display filename. They explicitly clear old
  `file_id` and `file_ext`, so later modified export uses the text fallback and
  cannot target the old binary.

## Independent review TDD and validation evidence

- Pre-fix focused baseline passed 108 tests across
  `useSearchReplace`, `EditPreview`, `useVerificationWorkspace`, and
  `WorkspaceView`.
- Initial review RED failed 30 tests with 106 passing. Failures covered
  length-changing folds, expansion boundaries, replacement/manual no-ops,
  stale drafts, atomic untrusted restore, report gating, and recheck identity.
- Conflict-history RED failed 1 test with 84 passing before restoration was
  updated to preserve the last valid review revision under newly conflicting
  decisions.
- Final focused, full-suite, build, and whitespace evidence is recorded in the
  Task 4 independent-review section of `progress.md`.

No Task 5 or Task 6 implementation was included in the fix wave.

## Fix round 2

- Replaced per-code-point insensitive folding with whole-candidate NFKD and
  stable `und` uppercase/lowercase folding. Candidate scans start and end only
  at original code-point boundaries, stop when the monotonically decomposed
  candidate exceeds the folded query length, retain deterministic
  left-to-right non-overlap, and cap unusually large folded queries. Reordered
  combining marks now match in both directions and replacements use the exact
  mapped original ranges; ligature, sharp-s, composed/decomposed,
  half-expansion, astral, and non-overlap coverage remains green.
- Made restored summaries issue-derived invariants. `total`, type, severity,
  rule, and layer maps must match exact issue counts with no missing, extra, or
  zero bogus buckets. Type, severity, and layer accept either canonical keys or
  the backend compatibility labels; rules remain canonical.
- Mirrored backend OCR/PDF validation at the atomic session boundary:
  positive ordered unique OCR pages; compatibility-payload OCR/metadata
  consistency; finite positive geometry; nonzero directions; exact character
  source ranges and mapping-state rules; span/cell reconstruction and
  contiguous ranges; span group-ID uniqueness; table shape and coordinate
  ownership; positive page/xref values; page-origin, density, coverage, and
  content-bound checks; ordered pages and OCR/page-flag agreement.
- Nested JSON copying continues to reject non-finite values in block style,
  source locators, LLM review metadata, and PDF metadata while constructing
  fresh null-prototype records. Any invalid nested value aborts preparation
  before workspace publication.

### Fix round 2 TDD and validation evidence

- Search RED:
  `npm test -- --run tests/useSearchReplace.spec.ts --reporter=dot` failed the
  2 new cross-boundary canonical-equivalence tests with 10 existing tests
  passing.
- Session RED:
  `npm test -- --run tests/useVerificationWorkspace.spec.ts --reporter=dot`
  failed 22 new summary/OCR/PDF parity tests with 91 tests passing.
- Focused GREEN:
  `npm test -- --run tests/useSearchReplace.spec.ts tests/useVerificationWorkspace.spec.ts tests/WorkspaceView.spec.ts --reporter=dot`
  passed 175 tests across 3 files. Node emitted the existing experimental
  `localStorage` warning.
- Full frontend GREEN: `npm test -- --run --reporter=dot` passed 281 tests
  across 14 files with the same existing Node warning.
- Production build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3
  with 50 modules transformed.
- Backend parity probe: the representative frontend PDF metadata fixture
  passed authoritative `PdfDocumentMetadata.model_validate` and round-trip
  JSON equality.
- `git diff --check` passed with no output.

No Task 5 result-loading work or Task 6 revision persistence work was included
in fix round 2.

## Fix round 3

- Case-insensitive search now segments source text into extended grapheme
  clusters with `Intl.Segmenter('und', { granularity: 'grapheme' })`. Each
  complete cluster is folded exactly once with the established whole-value
  NFKD, stable `und` uppercase/lowercase, and final NFKD transform. Folded
  grapheme start/end boundaries map back to original Unicode code-point
  offsets.
- The complete query is folded once and matched against the concatenated
  folded text with KMP. Only candidates whose folded start and end are recorded
  grapheme boundaries are accepted; accepted matches advance
  non-overlappingly, while rejected inside-grapheme or inside-expansion
  candidates continue through the bounded matcher.
- Accent-sensitive semantics now reject a base-only query inside an accented
  grapheme and reject a combining-mark-only query when the mark is attached to
  a base. Canonically equivalent reordered marks, composed/decomposed text,
  ligatures, sharp-s, astral offsets, literal case-sensitive behavior, and the
  4096-code-point folded-query guard remain covered.
- Replacement regressions assert exact original code-point ranges and prove
  that replacing or rejecting an accented grapheme cannot leave a dangling
  combining mark. A deterministic 10,001-cluster/512-code-point regression
  counts exactly two normalization calls per text cluster plus one complete
  query fold, ruling out candidate-substring refolding.

### Fix round 3 TDD and validation evidence

- Search RED:
  `npm test -- --run tests/useSearchReplace.spec.ts --reporter=dot` failed 4
  new grapheme-safety/complexity tests with 13 existing tests passing. The
  observed failures included a base match at `{ start: 0, end: 1 }`, an
  attached-mark match at `{ start: 1, end: 2 }`, an unsafe replacement, and
  94,260 normalization calls instead of the bounded 20,004.
- Focused search GREEN: the same command passed 17 tests in 1 file.
- Task 4/workspace GREEN:
  `npm test -- --run tests/ReviewActions.spec.ts tests/SearchReplacePanel.spec.ts tests/EditPreview.spec.ts tests/useSearchReplace.spec.ts tests/useVerificationWorkspace.spec.ts tests/WorkspaceView.spec.ts --reporter=dot`
  passed 192 tests across 6 files. Node emitted the existing experimental
  `localStorage` warning.
- Full frontend GREEN: `npm test -- --run --reporter=dot` passed 286 tests
  across 14 files with the same existing warning.
- Production build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3
  with 50 modules transformed. An earlier build caught and prompted correction
  of a test-only `String.normalize` spy overload mismatch.
- `git diff --check` passed with no output.

No Task 5 result-loading/API work or Task 6 backend revision persistence work
was included in fix round 3.

## Fix round 4

- Query folding now uses the same extended-grapheme pipeline as source-text
  folding. Each query cluster is independently normalized with whole-cluster
  NFKD, stable `und` uppercase/lowercase, and final NFKD, so context-sensitive
  final and non-final Greek sigma forms canonicalize identically without
  changing accent sensitivity, expansion boundaries, KMP matching, or
  original code-point mappings.
- Added `unicode-segmenter` `^0.17.3` as an `apps/web` runtime dependency.
  Native `Intl.Segmenter` remains preferred when available; otherwise the
  Unicode 17 UAX #29 extended-grapheme implementation supplies the same
  internal segment/start/end contract without a module-startup exception.
- Native and fallback regressions cover decomposed combining sequences,
  astral code-point offsets, Greek sigma variants, ligature expansion, and
  equivalent relevant ranges. Greek replacement coverage verifies exact
  original ranges for uppercase, final-sigma, and normal-sigma text.
- The normalization complexity assertion is derived from 10,001 text clusters
  plus 512 query clusters. Each cluster is folded once with two normalization
  calls, preserving deterministic O(n+m) segmentation, folding, and KMP
  matching.

### Fix round 4 TDD and validation evidence

- Search RED:
  `npm test -- --run tests/useSearchReplace.spec.ts --reporter=dot` failed 6
  tests with 16 passing. All three `ΟΣ`/`ος`/`οσ` query variants and the
  replacement regression returned no ranges, the normalization probe observed
  20,004 calls instead of the cluster-derived 21,026, and importing after
  removing `Intl.Segmenter` threw `TypeError: Intl.Segmenter is not a
  constructor`.
- Focused search GREEN: the same command passed 22 tests in 1 file.
- Task 4/workspace GREEN:
  `npm test -- --run tests/ReviewActions.spec.ts tests/SearchReplacePanel.spec.ts tests/EditPreview.spec.ts tests/useSearchReplace.spec.ts tests/useVerificationWorkspace.spec.ts tests/WorkspaceView.spec.ts --reporter=dot`
  passed 197 tests across 6 files. Node emitted the existing experimental
  `localStorage` warning.
- Full frontend GREEN: `npm test -- --run --reporter=dot` passed 291 tests
  across 14 files with the same existing warning.
- Production build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3
  with 53 modules transformed.
- `git diff --check` passed with no output.

No Task 5 result-loading/API work or Task 6 backend revision persistence work
was included in fix round 4.
