# Canonical Models and Compatibility Baseline — final fix report

**Date:** 2026-08-31
**Scope:** Single final-fix wave for every Critical/Important and listed Minor finding
**Worktree:** Existing user-directed checkout at `/Users/yhe/Work/Text-Virification` on `main`
**Delegation:** No subagents or external reviewers were used.

## Status

All listed findings were addressed in one coherent compatibility-preserving
change set. The final backend suite, Ruff, mypy, wheel-content inspection,
frontend suite, and frontend production build completed successfully.

## Findings addressed

### 1. Execution and analysis modes

- Replaced the LLM-oriented `execution_mode` values with transport values:
  - `synchronous`
  - `asynchronous`
- Added a separate `analysis_mode`:
  - `local_only`
  - `local_plus_llm`
- The current compatibility service reports `synchronous`.
- Disabled LLM review now reports `local_only` without degradation.
- A configured LLM call that fails falls back to local results, reports
  `local_only`, and records `llm_review_failed`.
- Successful configured LLM review reports `local_plus_llm`.
- Added both fields to the compatibility response and frontend types.

### 2. Source-version propagation

- Added required `source_version` to canonical `VerificationResult`.
- Propagated `DocumentModel.source_version` verbatim through the service and
  response mapper.
- Direct text continues to use SHA-256 of the direct text.
- Uploaded documents now use SHA-256 of immutable stored source bytes, not
  extracted/normalized text.
- The legacy mapper no longer recomputes source versions.
- Added a UTF-8 versus UTF-16 upload regression proving equal extracted text
  retains distinct source-byte versions.

### 3. Canonical invariants

- `TextBlock` validates matching global/local widths and an anchored local
  range.
- `DocumentModel` validates:
  - unique block IDs;
  - existing, non-self, acyclic parent relationships;
  - parent containment;
  - overlap only for parent-child containment;
  - block ranges and text slices against document text.
- `Issue` validates:
  - global range width against `original`;
  - block ID/offset pairing;
  - block-local width against global width.
- `VerificationResult` validates:
  - issue document ownership;
  - issue verification-run ownership;
  - issue range and original slice against result text;
  - summary total and bucket totals;
  - exact rule counts and exact canonical bucket counts when canonical keys are
    present.
- Summary bucket values now reject negative counts.
- Localized legacy summary labels remain accepted when their totals are
  internally consistent.

### 4. Source-rule contracts

- Expanded the data-driven contract inventory from three cases to coverage for:
  - punctuation priority over width-mixed duplicates;
  - scenario filtering;
  - independent security, sensitive-language, and advertising switches;
  - custom glossary;
  - banned words;
  - representative character, vocabulary, sentence, format, discourse, and
    compliance rules;
  - uppercase `X` and distinct lowercase `x` identity-card cases;
  - statistics;
  - provider-error and invalid-response LLM fallback.
- Every rule case validates sorted offsets, unique issues, half-open ranges,
  and exact source slices.
- Targeted rule assertions filter by rule ID; unrelated issue types are not
  asserted brittlely.

### 5. Capability manifest production use

- Added typed capability profiles:
  - `synchronous_compatibility` for all seven formats;
  - `asynchronous_job` for the intentional DOCX/PDF/TXT baseline.
- Added MIME types and profile membership to each format capability.
- `/formats`, the compatibility parser declaration, compatibility upload
  allowlist, async `JobStorage` allowlist, and async declared-MIME checks now
  derive from the manifest.
- Removed the independent backend extension, upload-file-type, and MIME maps.
- Preserved current `UploadWorkspace.vue` behavior. The ledger explicitly
  records `/formats` consumption as Stage 4 workspace scope rather than
  changing the workspace in this stage.

### 6. LLM bounds and safe failures

- Added finite validated upper bounds:
  - maximum review candidates: `200`;
  - context radius: `2,000` characters;
  - timeout: `300` seconds.
- Provider exception details are logged with exception context.
- Response metadata exposes only stable safe codes and reasons:
  - `llm_client_unavailable`;
  - `llm_provider_error`;
  - `llm_invalid_response`.
- Provider exception text is not included in summary metadata.

### 7. Dictionary failures and cleanup

- `UnicodeDecodeError`, `PermissionError`, and suitable `OSError` failures now
  become `DictionaryLoadError`.
- Client-visible dictionary errors remain path- and detail-safe.
- Added direct-text API coverage using an actually invalid dictionary encoding.
- Added upload coverage proving the stored upload is cleaned when the same
  normalized dictionary failure occurs.

### 8. Lowercase identity-card `x`

- Added a distinct data-driven contract for
  `11010519491231002x`, including exact offsets and slice.

### 9. Nullable legacy suggestions

- The compatibility mapper now preserves `None` as JSON `null`.
- The legacy analyzer annotation now reflects nullable suggestions.
- Frontend `VerificationIssue.suggestion` is `string | null`.
- Workspace state normalizes `null` to an empty replacement only at editing
  and export boundaries, preserving safe deletion behavior.
- HTML report rendering keeps nullable suggestions blank rather than displaying
  the string `None`.

## TDD RED/GREEN evidence

### Baseline

Backend:

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
.venv/bin/python -m pytest -q
```

Result before fixes: `129 passed, 8 skipped`.

Frontend:

```bash
cd /Users/yhe/Work/Text-Virification/apps/web
npm test -- --reporter=dot
```

Result before fixes: `29 passed`.

### Execution-domain contract RED

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
.venv/bin/python -m pytest tests/unit/domain/test_execution_contracts.py -q
```

RED: collection failed because `VerificationAnalysisMode` did not exist.

GREEN:

```text
4 passed
```

### Service and LLM-mode RED

```bash
.venv/bin/python -m pytest \
  tests/unit/compatibility/test_llm_review.py \
  tests/unit/compatibility/test_service.py \
  tests/integration/test_compatibility_api.py::test_analyze_direct_text_supports_legacy_options \
  -q --tb=short
```

RED: `5 failed`; failures showed the missing stable failure code, obsolete
`RULES_WITH_OPTIONAL_LLM` value, disabled-LLM degradation, and missing
transport/analysis separation.

GREEN:

```text
9 passed
```

### Source-version RED

Unit command:

```bash
.venv/bin/python -m pytest \
  tests/unit/compatibility/test_source_versions.py \
  tests/unit/compatibility/test_adapters.py::test_legacy_response_keeps_existing_fields_and_adds_canonical_metadata \
  -q --tb=short
```

RED: collection failed because `source_version_for_file` did not exist.

Upload command:

```bash
.venv/bin/python -m pytest \
  tests/integration/test_compatibility_api.py::test_uploaded_source_version_hashes_source_bytes_not_extracted_text \
  -q --tb=short
```

RED: UTF-16 upload returned the extracted-text hash instead of its source-byte
hash.

GREEN:

```text
4 passed
```

### Canonical-invariant RED

```bash
.venv/bin/python -m pytest \
  tests/unit/domain/test_models.py \
  tests/unit/domain/test_verification.py \
  -q --tb=short
```

RED: `13 failed, 14 passed`; missing checks included local block range,
duplicate IDs, illegal overlap, parent containment, issue span width, result
ownership, document-slice consistency, and summary consistency.

GREEN:

```text
27 passed
```

Additional summary-bound RED:

```bash
.venv/bin/python -m pytest \
  tests/unit/domain/test_verification.py::test_verification_summary_rejects_negative_bucket_counts \
  -q --tb=short
```

RED: negative bucket count did not raise.

GREEN: `1 passed`.

### Capability-manifest RED

```bash
.venv/bin/python -m pytest \
  tests/unit/domain/test_capabilities.py \
  tests/unit/infrastructure/test_storage.py::test_job_storage_uses_manifest_async_profile \
  tests/integration/test_compatibility_api.py::test_scenarios_and_formats_are_discoverable \
  -q --tb=short
```

RED: collection failed because `CapabilityProfile` did not exist.

GREEN:

```text
9 passed
```

### Dictionary-normalization RED

```bash
.venv/bin/python -m pytest \
  tests/unit/infrastructure/test_dictionary_loader.py::test_dictionary_loader_normalizes_invalid_encoding \
  tests/unit/infrastructure/test_dictionary_loader.py::test_dictionary_loader_normalizes_safe_os_errors \
  tests/integration/test_compatibility_api.py::test_analyze_direct_text_normalizes_dictionary_encoding_failure \
  tests/integration/test_compatibility_api.py::test_uploaded_file_is_deleted_when_dictionary_encoding_is_invalid \
  -q --tb=short
```

RED: `5 failed`; raw `UnicodeDecodeError`, `PermissionError`, and `OSError`
escaped the dictionary boundary and API-safe handling.

GREEN:

```text
5 passed
```

### Nullable-suggestion RED

Backend:

```bash
.venv/bin/python -m pytest \
  tests/unit/compatibility/test_adapters.py::test_legacy_response_preserves_nullable_suggestion_semantics \
  -q --tb=short
```

RED: `None` was converted to `""`.

Frontend workspace:

```bash
npm test -- WorkspaceView.spec.ts -t "nullable suggestion" --reporter=dot
```

RED: accepting a nullable suggestion rendered literal `null` in the preview.

Frontend type:

```bash
npm run build
```

RED: TypeScript reported `Type 'null' is not assignable to type 'string'`.

GREEN:

```text
Backend adapter: 1 passed
Workspace regression: 1 passed
Verification API regression: 1 passed
Frontend build: succeeded
```

HTML-report RED:

```bash
.venv/bin/python -m pytest \
  tests/integration/test_compatibility_api.py::test_export_html_report_keeps_nullable_suggestion_display_safe \
  -q --tb=short
```

RED: the report rendered `<td class="suggestion">None</td>`.

GREEN: `1 passed`.

### Source-contract inventory RED

```bash
.venv/bin/python -m pytest \
  tests/contract/test_source_rule_contracts.py::test_source_rule_contract_inventory_covers_preserved_families_and_interactions \
  -q --tb=short
```

RED: required rule-family and interaction case names were absent.

GREEN contract suite:

```bash
.venv/bin/python -m pytest tests/contract/test_source_rule_contracts.py -q
```

Result: `23 passed`.

## Focused verification

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
.venv/bin/python -m pytest \
  tests/unit/domain \
  tests/unit/compatibility/test_adapters.py \
  tests/unit/compatibility/test_service.py \
  tests/unit/compatibility/test_llm_review.py \
  tests/unit/compatibility/test_source_versions.py \
  tests/unit/infrastructure/test_dictionary_loader.py \
  tests/contract \
  tests/integration/test_compatibility_api.py \
  -q --tb=short
```

Result: `108 passed`.

## Final verification

### Full backend suite

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
.venv/bin/python -m pytest -q
```

Result: `185 passed, 8 skipped, 6 warnings`.

The skips are the existing environment-gated live API and PostgreSQL tests.

### Ruff and mypy

```bash
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy src
```

Results:

```text
All checks passed!
Success: no issues found in 41 source files
```

### Wheel-content inspection

```bash
rm -rf dist build
uv build --wheel --out-dir dist --quiet
```

The resulting `text_verification-0.1.0-py3-none-any.whl` was opened with
`zipfile.ZipFile`; exact packaged dictionary entries were:

```text
text_verification/resources/dictionaries/ad_extreme_words.json
text_verification/resources/dictionaries/sensitive_rules.json
```

### Full frontend suite and build

```bash
cd /Users/yhe/Work/Text-Virification/apps/web
npm test -- --reporter=dot
npm run build
```

Results:

```text
3 test files passed
31 tests passed
vue-tsc -b succeeded
vite build succeeded
```

## Files changed

### Backend production

- `apps/api/src/text_verification/api/routes/jobs.py`
- `apps/api/src/text_verification/compatibility/adapters.py`
- `apps/api/src/text_verification/compatibility/analyzer.py`
- `apps/api/src/text_verification/compatibility/llm_review.py`
- `apps/api/src/text_verification/compatibility/parser.py`
- `apps/api/src/text_verification/compatibility/reports.py`
- `apps/api/src/text_verification/compatibility/service.py`
- `apps/api/src/text_verification/compatibility/storage.py`
- `apps/api/src/text_verification/config.py`
- `apps/api/src/text_verification/domain/capabilities.py`
- `apps/api/src/text_verification/domain/documents.py`
- `apps/api/src/text_verification/domain/issues.py`
- `apps/api/src/text_verification/domain/verification.py`
- `apps/api/src/text_verification/infrastructure/dictionary_loader.py`
- `apps/api/src/text_verification/infrastructure/storage.py`

### Backend tests/contracts

- `apps/api/tests/contract/cases/llm_fallback.json`
- `apps/api/tests/contract/cases/source_rules.json`
- `apps/api/tests/contract/cases/source_statistics.json`
- `apps/api/tests/contract/test_source_rule_contracts.py`
- `apps/api/tests/integration/test_compatibility_api.py`
- `apps/api/tests/unit/compatibility/test_adapters.py`
- `apps/api/tests/unit/compatibility/test_llm_review.py`
- `apps/api/tests/unit/compatibility/test_service.py`
- `apps/api/tests/unit/compatibility/test_source_versions.py`
- `apps/api/tests/unit/domain/test_capabilities.py`
- `apps/api/tests/unit/domain/test_execution_contracts.py`
- `apps/api/tests/unit/domain/test_models.py`
- `apps/api/tests/unit/domain/test_verification.py`
- `apps/api/tests/unit/infrastructure/test_dictionary_loader.py`
- `apps/api/tests/unit/infrastructure/test_storage.py`

### Frontend

- `apps/web/src/types/verification.ts`
- `apps/web/src/views/WorkspaceView.vue`
- `apps/web/tests/WorkspaceView.spec.ts`
- `apps/web/tests/verificationApi.spec.ts`

### Ledger/report

- `.superpowers/sdd/2026-08-30-canonical-models-and-compatibility-baseline/progress.md`
- `.superpowers/sdd/2026-08-30-canonical-models-and-compatibility-baseline/final-fix-report.md`

## Self-review

- Reviewed the complete working-tree diff and ran `git diff --check`.
- Searched for removed concepts and independent backend format constants:
  - no `rules_with_optional_llm`;
  - no `rules_only`;
  - no `llm_review_disabled`;
  - no legacy-mapper source-version recomputation;
  - no backend `SUPPORTED_EXTENSIONS`, `SUPPORTED_UPLOAD_FILE_TYPES`, or
    `FILE_TYPE_MIME_TYPES`.
- Confirmed the remaining frontend seven-format literal is limited to
  `UploadWorkspace.vue` and is explicitly ledgered as Stage 4 scope.
- Removed generated wheel build directories from the working tree.
- Did not implement the unified pipeline, persistence expansion, or frontend
  redesign.

## Remaining concerns

1. `TEST_DATABASE_URL` was not set, so six PostgreSQL repository tests remained
   skipped.
2. `LIVE_API_URL` was not set, so two live Compose upload-lifecycle tests
   remained skipped.
3. Existing Starlette/httpx and PyMuPDF/SWIG deprecation warnings remain; they
   are pre-existing and unrelated to this final-fix wave.
4. The frontend still owns its current seven-format upload literal until the
   approved Stage 4 workspace migration consumes `/formats`.

## Authorized corrective wave — 2026-08-31

### Scope and fixes

- Canonical verification summaries now accept only exact canonical counts or
  the explicitly supported localized legacy counts. Mixed canonical and
  unknown keys are rejected for type, severity, and layer buckets.
- Source-rule contracts now record and assert issue severity. Representative
  cases also assert summary totals and selected buckets, and a representative
  rule case asserts its complete text statistics. Rule assertions remain
  filtered by rule ID so unrelated hits are not constrained.
- The synchronous compatibility capability profile now encodes the established
  TXT-first order. `/api/v1/formats` continues to derive its response from the
  manifest and has an exact-order regression test.

### TDD evidence

Summary validation RED:

```text
3 failed, 1 passed
```

Summary validation GREEN:

```text
4 passed
```

Source-rule contract RED:

```text
15 failed, 9 passed
```

Source-rule contract GREEN:

```text
23 passed
```

Format-order RED:

```text
3 failed
```

Format-order GREEN:

```text
3 passed
```

### Corrected validation counts

The earlier `108 passed` focused-verification count is superseded by rerunning
the identical command on the corrective-wave tree:

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
.venv/bin/python -m pytest \
  tests/unit/domain \
  tests/unit/compatibility/test_adapters.py \
  tests/unit/compatibility/test_service.py \
  tests/unit/compatibility/test_llm_review.py \
  tests/unit/compatibility/test_source_versions.py \
  tests/unit/infrastructure/test_dictionary_loader.py \
  tests/contract \
  tests/integration/test_compatibility_api.py \
  -q --tb=short
```

Result:

```text
114 passed, 6 warnings
```

The narrower corrective-wave domain/contract/API command passed:

```text
61 passed, 6 warnings
```

The earlier `185 passed, 8 skipped` full-backend count is superseded for the
corrective-wave tree by:

```bash
cd /Users/yhe/Work/Text-Virification/apps/api
.venv/bin/python -m pytest -q
```

Result:

```text
189 passed, 8 skipped, 6 warnings
```

Static validation:

```text
Ruff: All checks passed!
mypy: Success: no issues found in 41 source files
```

Frontend files were untouched, so the frontend suite and build were not
repeated in this backend-only corrective wave.

### Corrective-wave concerns

1. Six PostgreSQL tests remain skipped because `TEST_DATABASE_URL` is not set.
2. Two live Compose tests remain skipped because `LIVE_API_URL` is not set.
3. The six existing Starlette/httpx and PyMuPDF/SWIG warnings remain unrelated
   to these fixes.

### Corrective-wave self-review

- Reviewed every changed production, test, contract-data, ledger, and report
  file and ran `git diff --check`.
- Confirmed the format order is profile-owned and no route-local order was
  introduced.
- Confirmed summary validation still accepts the legacy localized/canonical
  fallback mix produced for unmapped legacy issue types.
- Confirmed no pipeline, persistence, exporter, or frontend redesign work was
  included.
