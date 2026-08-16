# Task 6 Report

## RED evidence
- Initial TDD command:
  - `Get-Content .env | ForEach-Object { ... }; $env:TEST_DATABASE_URL = $env:DATABASE_URL; & .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_create_job.py apps\api\tests\integration\test_analysis_api.py apps\api\tests\integration\test_job_repository.py apps\api\tests\integration\test_pipeline_task.py -q`
- Result: `6 failed, 36 passed, 11 errors`.
- Failures proved the missing behavior:
  - create-job responses/options were absent,
  - `0004_add_job_check_options` migration was missing,
  - persisted non-default options were not reaching `CheckerRegistry.run`,
  - analysis read APIs/cursor handling were missing,
  - raw local PostgreSQL access via compose host alias `postgres` was invalid on Windows host, so real PostgreSQL verification had to derive `TEST_DATABASE_URL` from runtime `DATABASE_URL` inside a container on the compose network.

## GREEN evidence
### Focused create/pipeline verification
- Command:
  - `& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\integration\test_create_job.py apps\api\tests\integration\test_pipeline_task.py -q`
- Result: `40 passed, 1 warning`.

### Real-PostgreSQL API/repository/migration verification
- Command:
  - `$repo = (Get-Location).Path; docker run --rm --network text-verification_default --env-file .env -v "$repo\apps\api\pyproject.toml:/app/pyproject.toml" -v "$repo\apps\api\src:/app/src" -v "$repo\apps\api\tests:/app/tests" -v "$repo\apps\api\alembic:/app/alembic" -v "$repo\apps\api\alembic.ini:/app/alembic.ini" -v "$repo\resources:/app/resources" text-verification-backend:development sh -lc 'export TEST_DATABASE_URL="$DATABASE_URL"; python -m pytest tests/integration/test_job_repository.py tests/integration/test_analysis_repository.py tests/integration/test_analysis_api.py -q'`
- Result: `18 passed, 1 warning`.
- This command derives a safe real `TEST_DATABASE_URL` from runtime `DATABASE_URL` inside the container and avoids the unreliable checked-in compose `TEST_DATABASE_URL` for local host execution.

### Full backend tests where feasible
- Host command:
  - `Remove-Item Env:TEST_DATABASE_URL -ErrorAction SilentlyContinue; & .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -q`
- Result: `99 passed, 22 skipped, 1 warning`.
- Expected skips:
  - PostgreSQL-only tests are covered by the containerized command above.
  - Live E2E requires `LIVE_API_URL`.
  - Two symlink-protection tests are skipped on this Windows host without symlink privilege.

### Static verification
- `& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api` → `All checks passed!`
- `& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src` → `Success: no issues found in 35 source files`

## Migration evidence
- Added Alembic migration: `apps/api/alembic/versions/0004_add_job_check_options.py`
- Verified fresh-head and old-head round-trip coverage via:
  - `tests/integration/test_job_repository.py::test_database_schema_matches_head_migration`
  - `tests/integration/test_job_repository.py::test_upgrade_from_old_0003_adds_job_check_options_and_keeps_repository_round_trip`
  - `tests/integration/test_job_repository.py::test_head_downgrades_back_through_0003_before_removing_analysis_tables`
- Migration lineage is `0003_add_issue_roundtrip_fields -> 0004_add_job_check_options` as required.

## Implemented scope
- Multipart upload parsing for `scenario` plus repeated `enabled_categories`.
- Job persistence/model/repository mapping for check options with legacy defaults.
- New analysis read APIs:
  - `GET /api/v1/jobs/{job_id}/document`
  - `GET /api/v1/jobs/{job_id}/issues`
  - `GET /api/v1/jobs/{job_id}/summary`
- Ready/not-found/partial semantics with `checker_failures` on partial jobs.
- Paginated document blocks and issues with normalized cursors.
- Structured Chinese cursor errors for malformed document/issue cursors.
- Regression proving persisted non-default options flow to `CheckerRegistry.run` through the runner path, while legacy jobs still default to `general` + all categories.
- README endpoint documentation update.

## Commit
- Commit message: `feat: implement task 6 upload options and analysis read APIs`
- Co-authored-by trailer required.
- Final commit hash recorded in the CLI response after commit.

## Self-review
- Kept unrelated `apps/web` work untouched.
- Limited behavioral changes to Task 6 upload/job/analysis paths plus tiny backend formatting-only fixes required to satisfy repository Ruff checks.
- Used real PostgreSQL verification for migration/repository/analysis API coverage, and host verification for the broader backend suite because the prebuilt container image lacks current parser deps while the local `.venv` already has them.

## Concerns
- Verification still reports a pre-existing `fastapi.testclient` / `httpx` deprecation warning.
- Host full-suite run still skips live E2E and Windows symlink-privilege cases by design.
