# Task 2 Report — Persist immutable analysis versions

## Summary
- Replaced destructive analysis persistence with immutable version creation and active-version switching.
- Added `RevisionRepository` to own queued/analyzing/succeeded/failed lifecycle transitions and atomic active-version updates.
- Kept existing job-scoped readers compatible by resolving `jobs.active_version_id`, while adding explicit version-scoped reads for historical queries.
- Updated integration test infrastructure so PostgreSQL-backed tests automatically start a unique temporary `postgres:16` container when `TEST_DATABASE_URL` is absent and remove that exact container afterward.

## Files changed
### Created
- `apps/api/src/text_verification/infrastructure/revision_repository.py`
- `apps/api/tests/integration/test_revision_repository.py`
- `.superpowers/sdd/2026-08-21-versioned-review-loop/task-2-report.md`

### Modified
- `apps/api/src/text_verification/infrastructure/analysis_repositories.py`
- `apps/api/src/text_verification/infrastructure/decision_repository.py`
- `apps/api/src/text_verification/api/dependencies.py`
- `apps/api/tests/conftest.py`
- `apps/api/tests/integration/test_analysis_repository.py`
- `apps/api/tests/integration/test_decision_api.py`
- `apps/api/tests/integration/test_export_task.py`

## Implementation details
1. Added `RevisionRepository` with:
   - `create_queued_version(job_id, parent_version_id, reason, idempotency_key)`
   - `mark_analyzing(version_id)`
   - `complete_analysis(version_id, document, issues, failures)`
   - `fail_version(version_id, code, message)`
   - `get_active_version(job_id)` / `list_versions(job_id)`
   - `ImmutableDocumentVersionError` for attempted mutation of succeeded/failed versions.
2. Refactored `AnalysisRepository`:
   - `replace_analysis()` now creates a new version instead of deleting prior versions.
   - Added `persist_version_analysis(version_id, ...)` for version-scoped writes.
   - Added optional `version_id` parameters to readers so historical document/issues/checker failures/summaries remain queryable.
   - Preserved rollout compatibility by keeping existing job-scoped calls defaulting to the active version.
3. Tightened decision lookup scope:
   - `DecisionRepository.apply()` now resolves only the active version’s issues for current-job commands, while still reporting stale-version conflicts for older issue versions.
4. Updated tests:
   - New repository integration tests prove parent retention, immutability after success, and failed versions never becoming active.
   - Existing repository and concurrency/export tests were updated to assert retained parent state rather than destructive deletion.
5. Updated PostgreSQL integration harness:
   - If `TEST_DATABASE_URL` is unset, tests launch a unique `postgres:16` container, wait for health plus successful connections, set `TEST_DATABASE_URL`/`DATABASE_URL`, clear cached engine/settings factories, and force-remove that exact container in teardown.

## RED evidence
### Command
```powershell
Push-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_revision_repository.py tests\integration\test_analysis_repository.py -q
Pop-Location
```

### Output
```text
ERROR tests/integration/test_revision_repository.py
ModuleNotFoundError: No module named 'text_verification.infrastructure.revision_repository'

ERROR tests/integration/test_analysis_repository.py
ModuleNotFoundError: No module named 'text_verification.infrastructure.revision_repository'
```

This confirmed the new immutable-version repository surface did not exist before implementation.

## GREEN / verification evidence
### Ruff on changed files
```powershell
Push-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
& .\.venv\Scripts\python.exe -m ruff check src\text_verification\infrastructure\analysis_repositories.py src\text_verification\infrastructure\revision_repository.py src\text_verification\infrastructure\decision_repository.py src\text_verification\api\dependencies.py tests\conftest.py tests\integration\test_revision_repository.py tests\integration\test_analysis_repository.py tests\integration\test_decision_api.py tests\integration\test_export_task.py
Pop-Location
```

```text
All checks passed!
```

### Required targeted PostgreSQL repository tests
```powershell
Push-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_revision_repository.py tests\integration\test_analysis_repository.py tests\integration\test_decision_repository.py -q
Pop-Location
```

```text
28 passed, 1 warning in 7.31s
```

### Broad backend suite from repository root
Run from repo root so resource-relative checker files resolve correctly.

```powershell
Push-Location C:\Work\text-verification\.worktrees\versioned-review-loop
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -q -k "not test_html_and_pdf_reports_share_title_counts_issues_failures_and_warnings and not test_html_and_pdf_reports_render_unknown_issue_layer_as_raw_text"
Pop-Location
```

```text
297 passed, 6 skipped, 2 deselected, 1 warning in 33.73s
```

### Focused regression verification while iterating
```powershell
Push-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_revision_repository.py tests\integration\test_analysis_repository.py -x -vv
& .\.venv\Scripts\python.exe -m pytest tests\integration\test_decision_api.py tests\integration\test_export_task.py -x -vv
Pop-Location
```

```text
11 passed, 1 warning in 5.55s
27 passed, 1 skipped, 1 warning in 13.40s
```

### Temporary container cleanup check
```powershell
docker ps -a --filter "name=text-verification-test-pg16-" --format "{{.Names}}"
```

```text
(no output)
```

This verified the session-scoped temporary PostgreSQL container was cleaned up.

## Self-review
- Reviewed the new persistence path to confirm historical `documents`, `issues`, `checker_failures`, and decisions stay attached to their original `version_id` rows rather than being job-wide deleted.
- Reviewed compatibility behavior: existing job-scoped readers still resolve through `jobs.active_version_id`, so current routes and worker callers keep working during rollout.
- Reviewed concurrency-sensitive tests and adjusted expectations to retained-parent semantics; the deadlock serialization test still passes with reanalysis creating a new version instead of removing the prior one.
- Reviewed the temporary PostgreSQL fixture for teardown safety and added an explicit connection-acceptance wait after Docker health turns green to avoid transient startup races.

## Concerns
1. `RevisionRepository.create_queued_version()` uses repository-level sequential `revision_number` generation, while issue staleness still depends on `DocumentModel.version`; current callers align, but later reanalysis/edit flows should keep those concepts intentionally coordinated.
2. The broad local suite still includes pre-existing environment skips unrelated to this task (`LIVE_API_URL`, Windows symlink privilege limits, and the Windows-gated PDF export integration test). The requested manual exclusion remains limited to the two known WeasyPrint unit tests.

## Commit
- `3b4004c72028bfc5d207b3b66bc3b264e78d535a` — `Persist immutable analysis versions`

## Fix round 1

### Summary
- Restored the opt-in `TEST_DATABASE_URL` convention in `tests/conftest.py`: PostgreSQL-backed integration tests now skip when the variable is unset, and a configured value is yielded while `DATABASE_URL` plus cached settings/session factories are aligned and safely restored.
- Moved `ImmutableDocumentVersionError` into `text_verification.domain.revisions` to avoid repository import cycles and enforced a version-row lock plus terminal-status check in `AnalysisRepository.persist_version_analysis()`.
- Added focused regressions for the configured fixture yield/cache path and for rejecting direct persistence into succeeded and failed versions without mutating stored content.

### Verification evidence

#### Ruff on changed Python files
```powershell
Push-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
& .\.venv\Scripts\python.exe -m ruff check src\text_verification\domain\revisions.py src\text_verification\infrastructure\analysis_repositories.py src\text_verification\infrastructure\revision_repository.py tests\conftest.py tests\integration\test_analysis_repository.py tests\integration\test_revision_repository.py tests\unit\infrastructure\test_postgres_fixture.py
Pop-Location
```

```text
All checks passed!
```

#### Focused fixture regression tests
```powershell
Push-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
& .\.venv\Scripts\python.exe -m pytest tests\unit\infrastructure\test_postgres_fixture.py -q
Pop-Location
```

```text
..                                                                       [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
2 passed, 1 warning in 0.13s
```

#### Relevant PostgreSQL integration tests with explicit `TEST_DATABASE_URL`
```powershell
Push-Location C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api
$container = 'tv-task2-verify-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse('127.0.0.1'), 0)
$listener.Start()
$port = ($listener.LocalEndpoint).Port
$listener.Stop()
try {
  docker run --detach --name $container --publish "${port}:5432" --env POSTGRES_PASSWORD=postgres --env POSTGRES_DB=text_verification --health-cmd "pg_isready -U postgres -d text_verification" --health-interval 1s --health-timeout 5s --health-retries 60 postgres:16 | Out-Null
  # wait for health, then:
  $env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:postgres@127.0.0.1:$port/text_verification"
  $env:DATABASE_URL = $env:TEST_DATABASE_URL
  & .\.venv\Scripts\python.exe -m pytest tests\integration\test_revision_repository.py tests\integration\test_analysis_repository.py tests\integration\test_decision_repository.py -q
}
finally {
  docker rm --force $container | Out-Null
  docker ps -a --filter "name=$container" --format "{{.Names}}"
  Pop-Location
}
```

```text
TEST_DATABASE_URL=******127.0.0.1:61151/text_verification
..............................                                           [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Work\text-verification\.worktrees\versioned-review-loop\apps\api\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
30 passed, 1 warning in 4.36s
CLEANUP_CHECK=none
```
