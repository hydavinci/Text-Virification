# Final review fix report — 2026-08-24

## Fixes

- Made deterministic checker-generated issue IDs version-scoped for literal rules and shared dictionaries so unchanged findings can persist across reanalysis without primary-key collisions.
- Propagated the selected version into export creation requests from the Vue workspace and `ExportPanel`, preserving historical export snapshots.
- Mapped derived-content overlap/validation failures to structured HTTP 409 responses in both derived preview and export creation routes.
- Added per-batch, server-backed undo actions to the operation history panel/state, scoped to the selected version and reusing existing conflict messaging.
- Updated verification notes for the Docker PyPI TLS blocker and the missing full Linux/container verification pass.

## RED evidence

- `python -m pytest apps\api\tests\unit\checkers\test_rule_checker.py apps\api\tests\integration\test_reanalysis_task.py::test_reanalysis_persists_unchanged_rule_finding_with_new_issue_id apps\api\tests\integration\test_versions_api.py::test_derived_endpoint_returns_conflict_for_overlapping_accepted_replacements apps\api\tests\integration\test_export_api.py::test_modified_document_export_returns_conflict_for_overlapping_replacements -q` failed with same-version issue IDs, PostgreSQL `issues_new_pkey` collision, and 500 instead of 409.
- `python -m pytest apps\api\tests\unit\checkers\test_dictionary_checker.py::test_dictionary_checker_scopes_deterministic_issue_ids_to_document_version -q` failed with same dictionary issue ID across document versions.
- `npm test -- tests\exportsApi.spec.ts tests\reviewShellComponents.spec.ts tests\reviewEditing.spec.ts` failed because per-batch undo buttons/state and export `version_id` propagation were absent.

## GREEN evidence

- `TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55433/text_verification_test python -m pytest apps\api\tests\unit\checkers\test_rule_checker.py apps\api\tests\unit\checkers\test_dictionary_checker.py apps\api\tests\integration\test_reanalysis_task.py::test_reanalysis_persists_unchanged_rule_finding_with_new_issue_id apps\api\tests\integration\test_versions_api.py::test_derived_endpoint_returns_conflict_for_overlapping_accepted_replacements apps\api\tests\integration\test_export_api.py::test_modified_document_export_returns_conflict_for_overlapping_replacements -q` → 9 passed.
- From `apps\api`: `TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55433/text_verification_test .\.venv\Scripts\python.exe -m pytest tests\unit tests\integration -q -k "not html_and_pdf_reports"` → 398 passed, 3 skipped, 2 deselected.
- `python -m ruff check apps\api\src apps\api\tests` → passed.
- `python -m mypy apps\api\src` → passed.
- From `apps\web`: `npm test` → 195 passed.
- From `apps\web`: `npm run build` → passed.

## Remaining verification gaps

- Full Windows backend suite still fails only the two known PDF report tests because WeasyPrint cannot load `libgobject-2.0-0` on this host.
- Full Linux/container verification was not completed in this wave because the Docker image path remains blocked by the known PyPI TLS certificate failure during dependency resolution. Rerun the compose build and full pytest inside the container once the TLS/mirror issue is fixed.

## Fresh verification update — 2026-08-24

- Full backend `tests\unit tests\integration` on Windows with temporary PostgreSQL was rerun after implementation. Result: 398 passed, 3 skipped, 2 failed; both failures are the known WeasyPrint native dependency gap (`libgobject-2.0-0`) in PDF report unit tests.
- Frontend `npm test` and `npm run build` were rerun after implementation. Result: 195 Vitest tests passed and production build succeeded.

## Round 2 stale-response fix — 2026-08-24

### Fixes

- Scoped `ExportPanel` create requests to a request generation and captured `versionId`, ignoring stale create successes/errors after version or format changes and clearing stale busy state on reset.
- Scoped per-batch history undo requests to the selected version and history generation, ignoring stale undo successes/conflicts after version-scope changes.

### RED evidence

- From `apps\web`: `npm test -- tests\reviewEditing.spec.ts -t "ignores stale undo|ignores stale export"` failed with stale undo success inserting `version-1` history, stale undo conflict appearing in the new scope, and stale export create showing an old-version download.

### GREEN evidence

- From `apps\web`: `npm test -- tests\reviewEditing.spec.ts -t "ignores stale undo|ignores stale export"` → 3 passed.
- From `apps\web`: `npm test -- tests\reviewEditing.spec.ts tests\reviewShellComponents.spec.ts tests\ReviewWorkspace.spec.ts` → 130 passed.
- From `apps\web`: `npm run build` → passed.

### Backend verification

- Backend code was untouched in round 2; no backend rerun was performed.
