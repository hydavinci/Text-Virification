# Platform Foundation Implementation Plan

> Historical note: This foundation was originally implemented before the Monorepo migration. Historical commit output and earlier task records may still show the old `backend/`, `frontend/`, and pre-`infra/compose.yaml` paths.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-shaped vertical slice where a user uploads a DOCX, PDF, or TXT file in Vue, FastAPI creates an isolated job, Celery processes a stub pipeline, PostgreSQL records durable state, Redis carries queued work, and the browser receives progress through SSE.

**Architecture:** During the foundation phase, the legacy Flask Demo under `translation-pre-checker/` remained available as a historical parallel implementation while the new platform was created under `apps/api/` and `apps/web/`. The approved repository-layout migration later removed that retired Demo. FastAPI handles validation and job APIs; PostgreSQL is the source of truth for jobs and events; Celery performs background work; per-job storage owns temporary files; Vue consumes REST and SSE. This plan establishes domain and adapter interfaces but deliberately does not implement document parsing, proofreading engines, dictionaries, review decisions, or exports.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis 7, Celery 5, pytest, Vue 3, TypeScript, Vite, Vitest, Docker Compose

**Spec:** `docs/architecture/document-verification-platform.md`

## Global Constraints

- The system targets an enterprise intranet with about 20 concurrent users.
- The maximum accepted upload size is exactly 25 MiB (`25 * 1024 * 1024` bytes).
- The first supported formats are DOCX, PDF, and TXT only.
- Every job uses an unguessable UUID and a dedicated storage directory.
- Jobs, source files, and generated artifacts expire after 24 hours.
- Document text and personal dictionary content must never be logged.
- The API must expose no server filesystem path.
- CPU-bound or long-running work must execute in Celery, not in FastAPI request handlers.
- PostgreSQL is the durable source of truth; Redis is not the only copy of job state.
- New code lives outside the historical `translation-pre-checker/`; that retired Demo was preserved during the foundation phase and removed later by the approved repository-layout migration.
- Use Windows-compatible development commands and paths, while containers use Linux paths internally.
- Initialize Git before the first commit because `C:\Work\text-verification` is not currently a repository.

## Planned File Structure

```text
text-verification/
├── .env.example
├── .gitignore
├── infra/
│   └── compose.yaml
├── apps/
│   ├── api/
│   │   ├── Dockerfile
│   │   ├── alembic.ini
│   │   ├── pyproject.toml
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   └── versions/
│   │   │       └── 0001_create_jobs_and_events.py
│   │   ├── src/text_verification/
│   │   │   ├── __init__.py
│   │   │   ├── main.py
│   │   │   ├── config.py
│   │   │   ├── api/
│   │   │   │   ├── dependencies.py
│   │   │   │   ├── router.py
│   │   │   │   └── routes/
│   │   │   │       ├── health.py
│   │   │   │       └── jobs.py
│   │   │   ├── domain/
│   │   │   │   ├── documents.py
│   │   │   │   ├── issues.py
│   │   │   │   ├── jobs.py
│   │   │   │   └── ports.py
│   │   │   ├── infrastructure/
│   │   │   │   ├── database.py
│   │   │   │   ├── orm.py
│   │   │   │   ├── repositories.py
│   │   │   │   └── storage.py
│   │   │   └── workers/
│   │   │       ├── celery_app.py
│   │   │       ├── pipeline.py
│   │   │       └── tasks.py
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── unit/
│   │       └── integration/
│   └── web/
│       ├── Dockerfile
│       ├── package.json
│       ├── tsconfig.json
│       ├── vite.config.ts
│       ├── src/
│       │   ├── main.ts
│       │   ├── App.vue
│       │   ├── api/jobs.ts
│       │   ├── components/JobProgress.vue
│       │   ├── components/UploadWorkspace.vue
│       │   ├── types/jobs.ts
│       │   └── views/WorkspaceView.vue
│       └── tests/
│           └── WorkspaceView.spec.ts
```

---

This implementation plan records the foundation work as originally executed. Historical command transcripts may reference the old layout; active repository commands should use `apps/api`, `apps/web`, and `docker compose -f infra/compose.yaml ...`.
