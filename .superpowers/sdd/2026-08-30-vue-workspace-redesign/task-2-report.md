# Task 2 report — workspace input, settings, and terminology

## Status

Completed on 2026-09-02 and fixed after independent review on 2026-09-03
from base `6bbe97149c469736a89158c138357d66d275e366`.

## Files

- Created `apps/web/src/components/workspace/SourceInputPanel.vue`.
- Created `apps/web/src/components/workspace/VerificationSettings.vue`.
- Created `apps/web/src/components/workspace/TerminologyEditor.vue`.
- Created `apps/web/src/composables/useTerminology.ts`.
- Created focused tests for all three components and the composable.
- Updated `apps/web/src/views/WorkspaceView.vue`.
- Adapted `apps/web/tests/WorkspaceView.spec.ts`.
- Updated the Vue redesign progress ledger.

## Delivered behavior

- File and direct-text input remain separate, with draft preservation and
  Ctrl/Command+Enter text submission.
- Upload supports DOCX, DOC, PDF, TXT, RTF, MD, and CSV by picker or
  drag-and-drop. Exactly 25 MiB is accepted; one byte more is rejected.
- The drop zone is the single visible, focusable upload action. Native upload
  and terminology-import inputs are programmatic controls hidden from the tab
  order and accessibility tree.
- Six scenarios and the security, sensitive-language, and advertising-extreme
  switches emit complete immutable-by-convention option snapshots.
- Glossary pairs and banned words support manual add, duplicate suppression,
  deletion, clear, CSV/TSV/TXT import, and example download.
- File extension determines CSV, TSV, or TXT parsing. CSV uses comma only and
  TSV uses tab only, both with quoted-field handling. TXT alone automatically
  detects tab, arrow, then comma delimiters.
- Quoted CSV fields preserve commas, arrows, tabs, escaped quotes, LF, and
  CRLF. Parser errors report deterministic physical source lines.
- Import validation is deterministic and transactional, with typed errors for
  malformed rows, quoting, empty or identical values, unsupported file types,
  overlong values, oversized files, and excessive entry counts.
- Every manual addition, set operation, and import merge validates the
  projected complete backend-shaped compact JSON options object. Exactly
  64 KiB is accepted and one projected mutation over the limit is rejected
  without changing state.
- The complete snapshot uses `scenario`, `enable_security`,
  `enable_sensitive`, `enable_ad_extreme`, `custom_glossary`, and
  `banned_words`, encoded as compact UTF-8 JSON. The independent 500-entry and
  200-Unicode-code-point bounds remain enforced.
- Rapid duplicate text or file submissions are synchronously ignored while
  the first analysis or create-job promise is pending. Existing generation
  checks remain in place for stale asynchronous callbacks.
- Imported values are rendered as text through Vue interpolation; no
  terminology content is passed to `v-html`.
- Existing direct analysis, optional-settings confirmation, asynchronous job
  progress, current review behavior, nullable suggestions, export, and session
  logic remain operational.
- No Jobs API or other Task 3–6 interfaces were changed.

## Limits and contracts

- Source upload maximum: `25 * 1024 * 1024` bytes, inclusive.
- Terminology import maximum: `64 * 1024` UTF-8 bytes.
- Complete serialized verification options maximum: `64 * 1024` UTF-8 bytes,
  inclusive.
- Glossary and banned-word maximum: 500 entries each.
- Imported/manual value maximum: 200 Unicode code points.
- Component events: `submit-text`, `submit-file`, `update:text`,
  `update:options`, and `notify`.

## TDD evidence

- Baseline: 83 frontend tests passed before Task 2 changes.
- Initial RED: all four new focused suites failed on missing component and
  composable imports.
- Workspace RED: the adapted workspace suite failed before component
  integration and caught the unsupported-format wording regression.
- Review REDs: malformed quote handling and collision-safe glossary identity
  each failed in a focused test before their parser fixes.
- Restart audit REDs: focused tests reproduced cumulative glossary state being
  rejected by the per-import byte bound and TSV values containing commas being
  split at the comma.
- Focused GREEN: 40 tests passed across the 5 Task 2/workspace files.
- Full GREEN: 111 tests passed across 8 frontend files.
- Build GREEN: `vue-tsc -b` and Vite production build passed; 29 modules were
  transformed.

### Independent review fix round — 2026-09-03

- Focused pre-fix baseline: 40 tests passed across the five Task 2/workspace
  suites.
- RED `useTerminology.spec.ts`: 6 failed and 16 passed, reproducing multiline
  CSV/physical-line handling, file-format loss, complete-snapshot manual/set/
  sequential-import validation, and transactional failure.
- RED `TerminologyEditor.spec.ts`: 4 failed and 4 passed, reproducing lost CSV
  format, missing full-context size validation, UTF-16 `maxlength`, and the
  invisible tabbable import control.
- RED `VerificationSettings.spec.ts`: 1 failed and 2 passed because an
  over-limit scenario mutation still emitted.
- RED `SourceInputPanel.spec.ts`: 1 failed and 7 passed because the nested
  native file input remained a second accessible/tabbable upload control.
- RED `WorkspaceView.spec.ts`: 3 failed and 12 passed because duplicate text,
  direct-file, and asynchronous create-job submissions each invoked the API
  twice while the first promise was pending.
- Follow-up parser RED: `useTerminology.spec.ts` failed with 1 failure and
  25 passes because a CSV comment containing quote/delimiter text was parsed
  instead of ignored.
- Physical-line RED: `useTerminology.spec.ts` failed with 1 failure and
  26 passes because malformed text on the second physical line of a multiline
  quoted field reported line 1.
- Focused GREEN:
  `npm test -- SourceInputPanel.spec.ts VerificationSettings.spec.ts useTerminology.spec.ts TerminologyEditor.spec.ts WorkspaceView.spec.ts --reporter=dot`
  passed 61 tests across 5 files.
- Full GREEN: `npm test -- --run --reporter=dot` passed 132 tests across
  8 files. Node emitted the existing experimental `localStorage` warning.
- Build GREEN: `npm run build` passed `vue-tsc -b` and Vite 6.4.3 with
  29 modules transformed.
- Final `git diff --check` is recorded in the handoff.

## Scope

The fix commit includes only Task 2 frontend components, the terminology
composable, `WorkspaceView`, focused/adapted frontend tests, and Task 2 SDD
evidence. Tasks 3–6 and the Jobs API remain untouched.
