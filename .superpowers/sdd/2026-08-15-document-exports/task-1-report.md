# Task 1 Report — Document Exports

## Status
- Completed on `main` with task-only backend code committed as `ab81e1d` (`feat: add export lifecycle and storage`).
- Preserved unrelated uncommitted `apps/web` changes.

## Scope Delivered
- Added backend export domain model and terminal-state guardrails.
- Added `exports` ORM mapping, PostgreSQL migration `0008_create_exports`, and repository lifecycle persistence.
- Added job-scoped server-generated export storage paths with extension allow-list enforcement.
- Added `jinja2` and `weasyprint` runtime dependencies to `apps/api/pyproject.toml`.

## TDD Log
### RED
1. Added `apps/api/tests/integration/test_export_repository.py` covering lifecycle round-trip, terminal-state rejection, and unsafe filename rejection.
2. Extended `apps/api/tests/unit/infrastructure/test_storage.py` with export-path generation, extension validation, and path-containment checks.
3. Ran RED tests:
   - `& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_export_repository.py -v`
   - Result: 4 failed because `text_verification.domain.exports` and `ExportRepository` did not exist.
   - `& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_export_repository.py apps\api\tests\unit\infrastructure\test_storage.py -v`
   - Result: storage tests failed because `JobStorage.export_path` did not exist.

### GREEN
1. Implemented `text_verification.domain.exports` with `ExportType`, `ExportStatus`, file-name/extension validation, and `TerminalExportStateError`.
2. Added `ExportRow`, Alembic revision `0008_create_exports`, and `ExportRepository` lifecycle methods.
3. Added `JobStorage.export_path(job_id, export_id, extension)` using server-generated file names inside the job UUID directory.
4. Re-ran the focused export tests and got green.

## Files Changed
- `apps/api/pyproject.toml`
- `apps/api/alembic/versions/0008_create_exports.py`
- `apps/api/src/text_verification/domain/exports.py`
- `apps/api/src/text_verification/infrastructure/export_repository.py`
- `apps/api/src/text_verification/infrastructure/orm.py`
- `apps/api/src/text_verification/infrastructure/storage.py`
- `apps/api/tests/integration/test_export_repository.py`
- `apps/api/tests/unit/infrastructure/test_storage.py`

## Validation
- Dependency restore: `Set-Location .\apps\api; & .\.venv\Scripts\python.exe -m pip install -e '.[dev]'`
- Focused PostgreSQL + storage tests:
  - `& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_export_repository.py apps\api\tests\unit\infrastructure\test_storage.py -v`
  - Result: `31 passed, 2 skipped, 1 warning`
- Focused Ruff:
  - `& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api\pyproject.toml apps\api\src\text_verification\domain\exports.py apps\api\src\text_verification\infrastructure\export_repository.py apps\api\src\text_verification\infrastructure\orm.py apps\api\src\text_verification\infrastructure\storage.py apps\api\tests\integration\test_export_repository.py apps\api\tests\unit\infrastructure\test_storage.py apps\api\alembic\versions\0008_create_exports.py`
  - Result: pass after one import-order fix
- Focused mypy:
  - `& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src\text_verification\domain\exports.py apps\api\src\text_verification\infrastructure\export_repository.py apps\api\src\text_verification\infrastructure\orm.py apps\api\src\text_verification\infrastructure\storage.py`
  - Result: `Success: no issues found in 4 source files`
- Full backend suite (real PostgreSQL configured via local Docker test container):
  - `& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -v`
  - Result: `201 passed, 4 skipped, 1 warning`
  - Expected skips: live E2E requires `LIVE_API_URL`; two Windows symlink tests require elevated symlink privileges.

## Notes / Concerns
- Task 4 still owns report-template package-data and native runtime package verification for WeasyPrint/Docker images, per the user ruling.
- Task 5 still needs to wire asynchronous export creation, download endpoints, and worker lifecycle onto this repository/storage base.

## Fix round 1

### Finding addressed
- `ExportRepository.create` previously accepted a caller-supplied file name and only validated that its suffix was one of the allowed extensions. That allowed invalid `ExportType`/extension pairings (for example `html_report` + `pdf`) and left repository file-name generation separate from storage path generation.

### Root cause
- The repository enforced only the extension allow-list.
- Export-type-to-extension mapping was not represented in a shared helper.
- Repository storage-key construction and `JobStorage.export_path` each formatted export names independently.

### Files changed
- `apps/api/src/text_verification/domain/exports.py`
- `apps/api/src/text_verification/infrastructure/export_repository.py`
- `apps/api/src/text_verification/infrastructure/storage.py`
- `apps/api/tests/integration/test_export_repository.py`
- `apps/api/tests/unit/domain/test_exports.py`
- `apps/api/tests/unit/infrastructure/test_storage.py`

### RED
Command:
```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://text_verification:text_verification@localhost:55432/text_verification_test'
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_export_repository.py apps\api\tests\unit\domain\test_exports.py apps\api\tests\unit\infrastructure\test_storage.py -v
```
Output:
- `19 failed, 32 passed, 2 skipped, 1 warning in 2.13s`
- Failing signals matched the bug: `build_export_artifact` did not exist yet, `ExportRepository.create` still accepted the old caller-controlled file-name input, and mismatched export-type/extension tests failed.

### GREEN / verification
Command:
```powershell
& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api\src\text_verification\domain\exports.py apps\api\src\text_verification\infrastructure\export_repository.py apps\api\src\text_verification\infrastructure\storage.py apps\api\tests\integration\test_export_repository.py apps\api\tests\unit\domain\test_exports.py apps\api\tests\unit\infrastructure\test_storage.py
& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src\text_verification\domain\exports.py apps\api\src\text_verification\infrastructure\export_repository.py apps\api\src\text_verification\infrastructure\storage.py
$env:TEST_DATABASE_URL='postgresql+psycopg://text_verification:text_verification@localhost:55432/text_verification_test'
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_export_repository.py apps\api\tests\unit\domain\test_exports.py apps\api\tests\unit\infrastructure\test_storage.py -q
```
Output:
- Ruff: `All checks passed!`
- mypy: `Success: no issues found in 3 source files`
- pytest: `51 passed, 2 skipped, 1 warning in 1.70s`
- Expected skips remained the Windows symlink-privilege storage tests.

### Behavioral result
- Export naming is now server-generated from a shared domain helper.
- Valid mappings are enforced exactly: `modified_document -> txt|docx`, `html_report -> html`, `pdf_report -> pdf`.
- Repository file names and storage keys, plus storage export paths, now share the same derivation logic.
