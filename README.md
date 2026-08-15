# Text Verification Platform Foundation

This repository contains a production-shaped development foundation for uploading
DOCX, PDF, and TXT documents, tracking jobs in PostgreSQL, dispatching work through
Redis and Celery, and streaming progress to the Vue application.

The current worker is intentionally a **stub pipeline**. It validates and stores an
upload, records progress transitions, verifies that the stored source exists, and
marks the job completed. It does not yet parse document content, run proofreading
engines, produce issues, or export corrected documents.

## Run the development stack

Prerequisites are Docker with the Compose plugin. From the repository root:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec api pytest
docker compose logs -f api worker
docker compose down
```

Open the application at <http://localhost:8080>. The health endpoint is
<http://localhost:8080/api/v1/health>.

The stack has seven services. `migrate` exits successfully after applying Alembic
migrations; PostgreSQL, Redis, API, worker, beat, and web remain running. PostgreSQL
and Redis are internal-only and do not publish host ports.

Uploads support `.docx`, `.pdf`, and `.txt` files up to exactly 25 MiB
(26,214,400 bytes). Jobs and stored files expire after 24 hours. This development
configuration uses explicit development-only database credentials and is not a
production security configuration.

## Tests and builds

Run the complete backend suite from the repository root:

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests -v
& .\backend\.venv\Scripts\python.exe -m ruff check backend
& .\backend\.venv\Scripts\python.exe -m mypy backend\src
```

PostgreSQL integration tests require `TEST_DATABASE_URL`; without it they skip
rather than substituting SQLite. The live acceptance test also skips unless
`LIVE_API_URL` is set:

```powershell
$env:LIVE_API_URL='http://localhost:8080'
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\e2e\test_upload_lifecycle.py -v
```

Run frontend tests and the production asset build:

```powershell
Set-Location frontend
npm test
npm run build
Set-Location ..
```

## Database migrations

Apply all migrations or roll back one revision using the one-shot migration image:

```powershell
docker compose run --rm migrate alembic upgrade head
docker compose run --rm migrate alembic downgrade -1
```

## Stop or reset

`docker compose down` stops the stack while preserving the `postgres-data` and
`job-data` named volumes. To explicitly remove all development data:

```powershell
docker compose down --volumes
```

Removing volumes permanently deletes the development database and uploaded job
files.

## Environment limitations

The Compose workflow requires Docker and a PostgreSQL-backed stack. Do not use
SQLite as a substitute: database migrations, UUID behavior, and repository locking
are PostgreSQL contracts. Host-side backend tests can run without PostgreSQL, but
the PostgreSQL integration tests and live upload lifecycle test will be skipped.
