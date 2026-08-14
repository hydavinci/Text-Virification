# Platform Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-shaped vertical slice where a user uploads a DOCX, PDF, or TXT file in Vue, FastAPI creates an isolated job, Celery processes a stub pipeline, PostgreSQL records durable state, Redis carries queued work, and the browser receives progress through SSE.

**Architecture:** Keep the existing Flask Demo untouched under `translation-pre-checker/` while creating a new `backend/` and `frontend/`. FastAPI handles validation and job APIs; PostgreSQL is the source of truth for jobs and events; Celery performs background work; per-job storage owns temporary files; Vue consumes REST and SSE. This plan establishes domain and adapter interfaces but deliberately does not implement document parsing, proofreading engines, dictionaries, review decisions, or exports.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, Redis 7, Celery 5, pytest, Vue 3, TypeScript, Vite, Vitest, Docker Compose

**Spec:** `docs/superpowers/specs/2026-08-14-document-proofreading-web-design.md`

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
- New code lives outside `translation-pre-checker/`; do not modify or delete the Demo in this plan.
- Use Windows-compatible development commands and paths, while containers use Linux paths internally.
- Initialize Git before the first commit because `C:\Work\text-verification` is not currently a repository.

## Planned File Structure

```text
text-verification/
├── .env.example
├── .gitignore
├── compose.yaml
├── backend/
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── pyproject.toml
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   │       └── 0001_create_jobs_and_events.py
│   ├── src/text_verification/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   ├── dependencies.py
│   │   │   ├── router.py
│   │   │   └── routes/
│   │   │       ├── health.py
│   │   │       └── jobs.py
│   │   ├── domain/
│   │   │   ├── documents.py
│   │   │   ├── issues.py
│   │   │   ├── jobs.py
│   │   │   └── ports.py
│   │   ├── infrastructure/
│   │   │   ├── database.py
│   │   │   ├── orm.py
│   │   │   ├── repositories.py
│   │   │   └── storage.py
│   │   └── workers/
│   │       ├── celery_app.py
│   │       ├── pipeline.py
│   │       └── tasks.py
│   └── tests/
│       ├── conftest.py
│       ├── unit/
│       └── integration/
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    ├── src/
    │   ├── main.ts
    │   ├── App.vue
    │   ├── api/jobs.ts
    │   ├── components/JobProgress.vue
    │   ├── components/UploadWorkspace.vue
    │   ├── types/jobs.ts
    │   └── views/WorkspaceView.vue
    └── tests/
        └── WorkspaceView.spec.ts
```

---

### Task 1: Initialize Git and create the FastAPI health slice

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `backend/pyproject.toml`
- Create: `backend/src/text_verification/__init__.py`
- Create: `backend/src/text_verification/config.py`
- Create: `backend/src/text_verification/main.py`
- Create: `backend/src/text_verification/api/router.py`
- Create: `backend/src/text_verification/api/routes/health.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/integration/test_health.py`

**Interfaces:**
- Consumes: None.
- Produces: `text_verification.main:create_app() -> FastAPI`, `GET /api/v1/health`, and cached `get_settings() -> Settings`.

- [ ] **Step 1: Initialize the repository and write root configuration**

Run from `C:\Work\text-verification`:

```powershell
git init -b main
```

Create `.gitignore`:

```gitignore
.env
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage
backend/.venv/
frontend/node_modules/
frontend/dist/
var/
*.log
.idea/
.vscode/
```

Create `.env.example`:

```dotenv
APP_ENV=development
DATABASE_URL=postgresql+psycopg://text_verification:text_verification@localhost:5432/text_verification
REDIS_URL=redis://localhost:6379/0
STORAGE_ROOT=./var/jobs
JOB_RETENTION_HOURS=24
MAX_UPLOAD_BYTES=26214400
CORS_ORIGINS=http://localhost:5173
```

- [ ] **Step 2: Declare backend dependencies**

Create `backend/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "text-verification"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
  "alembic>=1.14,<2",
  "celery[redis]>=5.4,<6",
  "fastapi>=0.115,<1",
  "psycopg[binary]>=3.2,<4",
  "pydantic-settings>=2.7,<3",
  "python-multipart>=0.0.20,<1",
  "sqlalchemy>=2.0.36,<3",
  "uvicorn[standard]>=0.34,<1",
]

[project.optional-dependencies]
dev = [
  "httpx>=0.28,<1",
  "mypy>=1.14,<2",
  "pytest>=8.3,<9",
  "pytest-cov>=6,<7",
  "ruff>=0.9,<1",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
addopts = "-ra --strict-markers"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP"]

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
```

Install the editable backend:

```powershell
Set-Location backend
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

- [ ] **Step 3: Write the failing health test**

Create `backend/tests/conftest.py`:

```python
import pytest
from fastapi.testclient import TestClient

from text_verification.main import create_app


@pytest.fixture
def client() -> TestClient:
    with TestClient(create_app()) as test_client:
        yield test_client
```

Create `backend/tests/integration/test_health.py`:

```python
def test_health_returns_service_status(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "text-verification-api",
        "version": "0.1.0",
    }
```

- [ ] **Step 4: Run the test to verify it fails**

Run:

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_health.py -v
```

Expected: FAIL during import because `text_verification.main` does not exist.

- [ ] **Step 5: Implement settings, router, and application factory**

Create `backend/src/text_verification/config.py`:

```python
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://text_verification:text_verification"
        "@localhost:5432/text_verification"
    )
    redis_url: str = "redis://localhost:6379/0"
    storage_root: Path = Path("./var/jobs")
    job_retention_hours: int = Field(default=24, ge=1)
    max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

Create `backend/src/text_verification/api/routes/health.py`:

```python
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "text-verification-api",
        "version": "0.1.0",
    }
```

Create `backend/src/text_verification/api/router.py`:

```python
from fastapi import APIRouter

from text_verification.api.routes.health import router as health_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
```

Create `backend/src/text_verification/main.py`:

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from text_verification.api.router import api_router
from text_verification.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="text-verification", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )
    app.include_router(api_router)
    return app


app = create_app()
```

- [ ] **Step 6: Run checks**

Run:

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_health.py -v
& .\backend\.venv\Scripts\python.exe -m ruff check backend
& .\backend\.venv\Scripts\python.exe -m mypy backend\src
```

Expected: all commands pass.

- [ ] **Step 7: Commit**

```powershell
git add .gitignore .env.example backend
git commit -m "feat: initialize FastAPI service"
```

Commit trailers:

```text
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
Copilot-Session: dc70da84-4b3a-45f3-8709-b22c5f7f49e1
```

---

### Task 2: Define document, issue, job, and extension port contracts

**Files:**
- Create: `backend/src/text_verification/domain/documents.py`
- Create: `backend/src/text_verification/domain/issues.py`
- Create: `backend/src/text_verification/domain/jobs.py`
- Create: `backend/src/text_verification/domain/ports.py`
- Test: `backend/tests/unit/domain/test_models.py`

**Interfaces:**
- Consumes: Pydantic 2.
- Produces: `DocumentModel`, `TextBlock`, `Issue`, `JobStatus`, `JobRead`, `Parser`, `Checker`, `Exporter`, and `CheckContext`.

- [ ] **Step 1: Write failing domain model tests**

Create `backend/tests/unit/domain/test_models.py`:

```python
from uuid import uuid4

import pytest
from pydantic import ValidationError

from text_verification.domain.documents import DocumentModel, FileType, TextBlock
from text_verification.domain.issues import Issue, IssueSeverity
from text_verification.domain.jobs import JobStatus


def test_document_owns_block_local_offsets():
    block = TextBlock(
        block_id="p-1",
        kind="paragraph",
        text="需要检查的文本",
        page=None,
        paragraph_index=0,
        parent_id=None,
        style={},
        source_locator={"paragraph_index": 0},
    )
    document = DocumentModel(
        document_id=uuid4(),
        file_type=FileType.DOCX,
        source_name="sample.docx",
        blocks=[block],
    )

    assert document.blocks[0].text[2:4] == "检查"


def test_issue_rejects_range_beyond_original_block_contract():
    with pytest.raises(ValidationError):
        Issue(
            issue_id=uuid4(),
            document_id=uuid4(),
            block_id="p-1",
            page=None,
            start=5,
            end=3,
            original="错",
            suggestion="正",
            alternatives=[],
            type="typo",
            severity=IssueSeverity.WARNING,
            layer="vocabulary",
            message="错别字",
            rule_id="legacy.typo",
            source="legacy",
            source_version="1",
            confidence=0.9,
            auto_fixable=True,
            context="上下文",
        )


def test_job_status_contains_all_pipeline_states():
    assert {status.value for status in JobStatus} == {
        "queued",
        "upload_validated",
        "parsing",
        "checking_format",
        "checking_sensitive",
        "checking_chinese",
        "checking_english",
        "completed",
        "partial",
        "failed",
        "expired",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run:

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\domain\test_models.py -v
```

Expected: FAIL because the domain modules do not exist.

- [ ] **Step 3: Implement document and issue models**

Create `backend/src/text_verification/domain/documents.py`:

```python
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FileType(StrEnum):
    DOCX = "docx"
    PDF = "pdf"
    TXT = "txt"


class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    kind: Literal["paragraph", "heading", "table_cell", "header", "footer"]
    text: str
    page: int | None
    paragraph_index: int | None
    parent_id: str | None
    style: dict[str, Any]
    source_locator: dict[str, Any]


class DocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    file_type: FileType
    source_name: str
    blocks: list[TextBlock]
```

Create `backend/src/text_verification/domain/issues.py`:

```python
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IssueSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: UUID
    document_id: UUID
    block_id: str
    page: int | None
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    original: str
    suggestion: str | None
    alternatives: list[str]
    type: str
    severity: IssueSeverity
    layer: str
    message: str
    rule_id: str
    source: str
    source_version: str
    confidence: float = Field(ge=0, le=1)
    auto_fixable: bool
    context: str

    @model_validator(mode="after")
    def validate_range(self) -> "Issue":
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self
```

- [ ] **Step 4: Implement job models and extension protocols**

Create `backend/src/text_verification/domain/jobs.py`:

```python
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobStatus(StrEnum):
    QUEUED = "queued"
    UPLOAD_VALIDATED = "upload_validated"
    PARSING = "parsing"
    CHECKING_FORMAT = "checking_format"
    CHECKING_SENSITIVE = "checking_sensitive"
    CHECKING_CHINESE = "checking_chinese"
    CHECKING_ENGLISH = "checking_english"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    EXPIRED = "expired"


TERMINAL_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.PARTIAL,
    JobStatus.FAILED,
    JobStatus.EXPIRED,
}


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    source_name: str
    file_type: str
    size_bytes: int
    status: JobStatus
    progress: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class JobEvent:
    sequence: int
    status: JobStatus
    progress: int
    message: str
    created_at: datetime
```

Create `backend/src/text_verification/domain/ports.py`:

```python
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from text_verification.domain.documents import DocumentModel, FileType
from text_verification.domain.issues import Issue


@dataclass(frozen=True)
class CheckContext:
    industry_dictionary_ids: tuple[str, ...]
    personal_dictionary: tuple[dict[str, str], ...]


class Parser(Protocol):
    supported_type: FileType

    def parse(self, source_path: Path) -> DocumentModel: ...


class Checker(Protocol):
    name: str
    version: str
    supported_languages: set[str]

    def check(self, document: DocumentModel, context: CheckContext) -> list[Issue]: ...


class Exporter(Protocol):
    file_type: FileType

    def export(self, document: DocumentModel, issues: list[Issue], target: Path) -> Path: ...
```

- [ ] **Step 5: Run domain checks**

Run:

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\domain\test_models.py -v
& .\backend\.venv\Scripts\python.exe -m mypy backend\src
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/text_verification/domain backend/tests/unit/domain
git commit -m "feat: define document processing contracts"
```

Include the required commit trailers.

---

### Task 3: Persist jobs and ordered job events

**Files:**
- Create: `backend/src/text_verification/infrastructure/database.py`
- Create: `backend/src/text_verification/infrastructure/orm.py`
- Create: `backend/src/text_verification/infrastructure/repositories.py`
- Create: `backend/src/text_verification/api/dependencies.py`
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/0001_create_jobs_and_events.py`
- Test: `backend/tests/integration/test_job_repository.py`

**Interfaces:**
- Consumes: `JobStatus`, `JobRead`, and `Settings.database_url`.
- Produces: `JobRepository.create_job()`, `get_job()`, `transition()`, `list_events_after()`, `expire_jobs_before()`, and `get_session()`.

- [ ] **Step 1: Write the failing repository test**

Create `backend/tests/integration/test_job_repository.py`:

```python
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from text_verification.domain.jobs import JobStatus
from text_verification.infrastructure.repositories import JobRepository


def test_repository_persists_job_and_ordered_events(db_session):
    repository = JobRepository(db_session)
    job_id = uuid4()
    now = datetime.now(UTC)

    repository.create_job(
        job_id=job_id,
        source_name="example.docx",
        file_type="docx",
        size_bytes=1024,
        storage_key=str(job_id),
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    repository.transition(job_id, JobStatus.UPLOAD_VALIDATED, 10, "上传校验完成")
    repository.transition(job_id, JobStatus.PARSING, 25, "开始解析")
    db_session.commit()

    job = repository.get_job(job_id)
    events = repository.list_events_after(job_id, after_sequence=0)

    assert job is not None
    assert job.status == JobStatus.PARSING
    assert [(event.sequence, event.status) for event in events] == [
        (1, JobStatus.QUEUED),
        (2, JobStatus.UPLOAD_VALIDATED),
        (3, JobStatus.PARSING),
    ]
```

Add a PostgreSQL test session fixture to `backend/tests/conftest.py`; use
`TEST_DATABASE_URL` and create/drop metadata per test session. Do not use SQLite,
because PostgreSQL UUID, locking, and migration behavior are part of this contract.

- [ ] **Step 2: Run the repository test to verify it fails**

Start the isolated test PostgreSQL container:

```powershell
docker run --detach --name text-verification-test-postgres `
  --env POSTGRES_USER=text_verification `
  --env POSTGRES_PASSWORD=text_verification `
  --env POSTGRES_DB=text_verification_test `
  --publish 5432:5432 `
  postgres:16
```

Wait until `docker logs text-verification-test-postgres` contains
`database system is ready to accept connections`, then run:

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://text_verification:text_verification@localhost:5432/text_verification_test'
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_job_repository.py -v
```

Expected: FAIL because the repository modules do not exist.

- [ ] **Step 3: Implement SQLAlchemy tables**

Create `backend/src/text_verification/infrastructure/orm.py` with:

```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "jobs"

    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(16))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    events: Mapped[list["JobEventRow"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobEventRow(Base):
    __tablename__ = "job_events"
    __table_args__ = (
        Index("ix_job_events_job_sequence", "job_id", "sequence", unique=True),
    )

    event_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.job_id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    progress: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    job: Mapped[JobRow] = relationship(back_populates="events")
```

- [ ] **Step 4: Implement database and repository APIs**

Create `database.py` with one cached engine/session factory derived from
`Settings.database_url`. Implement `JobRepository` so `transition()` locks the
job row with `SELECT ... FOR UPDATE`, calculates `max(sequence) + 1`, updates the
job, and inserts the event in the same transaction. Map persisted status strings
to `JobStatus` when returning domain records.

Required signatures:

```python
class JobRepository:
    def create_job(
        self,
        *,
        job_id: UUID,
        source_name: str,
        file_type: str,
        size_bytes: int,
        storage_key: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> JobRead: ...

    def get_job(self, job_id: UUID) -> JobRead | None: ...

    def transition(
        self,
        job_id: UUID,
        status: JobStatus,
        progress: int,
        message: str,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None: ...

    def list_events_after(
        self, job_id: UUID, after_sequence: int
    ) -> list[JobEvent]: ...

    def expire_jobs_before(self, cutoff: datetime) -> list[UUID]: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...
```

Import `dataclass` in `domain/jobs.py`. Implement `commit()` and `rollback()` as
thin calls to the repository's injected SQLAlchemy `Session`; this keeps route
transactions explicit and gives tests one replacement boundary.

- [ ] **Step 5: Add and apply the initial migration**

Configure Alembic to import `Base.metadata`. The migration must create `jobs`,
`job_events`, the status/expiry indexes, and the unique `(job_id, sequence)`
index. It must drop them in reverse order in `downgrade()`.

Run:

```powershell
Set-Location backend
& .\.venv\Scripts\alembic.exe upgrade head
& .\.venv\Scripts\alembic.exe downgrade base
& .\.venv\Scripts\alembic.exe upgrade head
Set-Location ..
```

Expected: all three commands succeed.

- [ ] **Step 6: Run repository tests and static checks**

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_job_repository.py -v
& .\backend\.venv\Scripts\python.exe -m ruff check backend
& .\backend\.venv\Scripts\python.exe -m mypy backend\src
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend
git commit -m "feat: persist jobs and progress events"
```

Include the required commit trailers.

---

### Task 4: Implement isolated upload storage and content validation

**Files:**
- Create: `backend/src/text_verification/infrastructure/storage.py`
- Test: `backend/tests/unit/infrastructure/test_storage.py`

**Interfaces:**
- Consumes: `Settings.storage_root`, `Settings.max_upload_bytes`, `FileType`.
- Produces: `JobStorage.save_stream()`, `save_bytes()`, `job_directory()`, `delete_job()`, and `delete_expired_directories()`.

- [ ] **Step 1: Write failing storage tests**

Create `backend/tests/unit/infrastructure/test_storage.py`:

```python
import io
import zipfile
from uuid import uuid4

import pytest

from text_verification.infrastructure.storage import (
    InvalidUpload,
    JobStorage,
    UploadTooLarge,
)


def make_docx_bytes() -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return data.getvalue()


def test_save_upload_uses_job_directory_and_server_filename(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=25 * 1024 * 1024)
    job_id = uuid4()

    stored = storage.save_bytes(job_id, "../../客户文档.docx", make_docx_bytes())

    assert stored.file_type.value == "docx"
    assert stored.path == tmp_path / str(job_id) / "source.docx"
    assert stored.path.read_bytes() == make_docx_bytes()


def test_rejects_upload_larger_than_configured_limit(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=4)

    with pytest.raises(UploadTooLarge):
        storage.save_bytes(uuid4(), "large.txt", b"12345")


def test_rejects_extension_content_mismatch(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)

    with pytest.raises(InvalidUpload, match="does not match"):
        storage.save_bytes(uuid4(), "fake.pdf", b"plain text")
```

Append these concrete cases to the same test file:

```python
def test_accepts_pdf_signature(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    stored = storage.save_bytes(uuid4(), "sample.pdf", b"%PDF-1.7\n%%EOF")
    assert stored.file_type.value == "pdf"


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("utf8.txt", "中文".encode("utf-8")),
        ("utf16.txt", "中文".encode("utf-16")),
        ("gbk.txt", "中文".encode("gbk")),
    ],
)
def test_accepts_supported_text_encodings(tmp_path, name, payload):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    assert storage.save_bytes(uuid4(), name, payload).file_type.value == "txt"


def test_rejects_docx_without_document_xml(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    with pytest.raises(InvalidUpload, match="word/document.xml"):
        storage.save_bytes(uuid4(), "broken.docx", data.getvalue())


def test_rejects_docx_with_too_many_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "text_verification.infrastructure.storage.MAX_ZIP_ENTRIES", 2
    )
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("word/extra.xml", "<x/>")
    storage = JobStorage(tmp_path, max_upload_bytes=4096)
    with pytest.raises(InvalidUpload, match="too many entries"):
        storage.save_bytes(uuid4(), "large.docx", data.getvalue())


def test_rejects_docx_declaring_excessive_uncompressed_size(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "text_verification.infrastructure.storage.MAX_ZIP_UNCOMPRESSED_BYTES", 4
    )
    with pytest.raises(InvalidUpload, match="uncompressed size"):
        JobStorage(tmp_path, 4096).save_bytes(
            uuid4(), "large.docx", make_docx_bytes()
        )


def test_delete_job_removes_only_requested_uuid_directory(tmp_path):
    storage = JobStorage(tmp_path, max_upload_bytes=1024)
    first = uuid4()
    second = uuid4()
    storage.save_bytes(first, "first.txt", b"first")
    storage.save_bytes(second, "second.txt", b"second")

    storage.delete_job(first)

    assert not storage.job_directory(first).exists()
    assert storage.job_directory(second).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\infrastructure\test_storage.py -v
```

Expected: FAIL because `storage.py` does not exist.

- [ ] **Step 3: Implement storage exceptions and value object**

Use:

```python
@dataclass(frozen=True)
class StoredUpload:
    original_name: str
    path: Path
    file_type: FileType
    size_bytes: int


class InvalidUpload(ValueError):
    pass


class UploadTooLarge(InvalidUpload):
    pass
```

`JobStorage` must resolve `storage_root`, build the job path solely from
`str(job_id)`, and save as `source.docx`, `source.pdf`, or `source.txt`.
Never include the user filename in a server path.

- [ ] **Step 4: Implement streaming save and validation**

Required public methods:

```python
class JobStorage:
    def __init__(self, root: Path, max_upload_bytes: int) -> None: ...
    def job_directory(self, job_id: UUID) -> Path: ...
    def save_stream(self, job_id: UUID, original_name: str, source: BinaryIO) -> StoredUpload: ...
    def save_bytes(self, job_id: UUID, original_name: str, data: bytes) -> StoredUpload: ...
    def delete_job(self, job_id: UUID) -> None: ...
    def delete_expired_directories(self, live_job_ids: set[UUID]) -> list[UUID]: ...
```

Write the incoming stream in 1 MiB chunks to `source.uploading`; stop and delete
the partial file as soon as cumulative bytes exceed 25 MiB. Validate content
after the stream closes, atomically rename to `source.<ext>`, and delete the job
directory on any validation failure.

For DOCX, inspect the ZIP central directory before extraction. Reject encrypted
entries, more than 10,000 entries, any entry above 100 MiB, total declared
uncompressed size above 200 MiB, absolute paths, drive-prefixed paths, and `..`
path segments.

- [ ] **Step 5: Run storage tests**

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\unit\infrastructure\test_storage.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/text_verification/infrastructure/storage.py backend/tests/unit/infrastructure
git commit -m "feat: add isolated upload storage"
```

Include the required commit trailers.

---

### Task 5: Create jobs through the upload API

**Files:**
- Modify: `backend/src/text_verification/api/dependencies.py`
- Modify: `backend/src/text_verification/api/router.py`
- Create: `backend/src/text_verification/api/routes/jobs.py`
- Test: `backend/tests/integration/test_create_job.py`

**Interfaces:**
- Consumes: `JobStorage.save_stream()`, `JobRepository.create_job()`, and `process_job.delay(str(job_id))`.
- Produces: `POST /api/v1/jobs -> 202 JobRead`.

- [ ] **Step 1: Write the failing upload API test**

Create `backend/tests/integration/test_create_job.py`:

```python
def test_create_txt_job_persists_and_enqueues(client, task_spy, tmp_path):
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", "需要检查".encode(), "text/plain")},
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["source_name"] == "sample.txt"
    assert payload["file_type"] == "txt"
    assert payload["status"] == "queued"
    assert payload["progress"] == 0
    assert "storage_key" not in payload
    assert task_spy.calls == [payload["job_id"]]
```

Append these concrete cases:

```python
def test_create_job_requires_file(client):
    assert client.post("/api/v1/jobs").status_code == 422


def test_create_job_rejects_unsupported_extension(client):
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.exe", b"MZ", "application/octet-stream")},
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_file_type"


def test_create_job_rejects_extension_content_mismatch(client):
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.pdf", b"plain text", "application/pdf")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_upload"


def test_create_job_rejects_oversized_upload(client, monkeypatch):
    monkeypatch.setattr(
        "text_verification.infrastructure.storage.READ_CHUNK_BYTES", 8
    )
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("large.txt", b"x" * (25 * 1024 * 1024 + 1), "text/plain")},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "upload_too_large"


def test_database_failure_removes_written_job_directory(
    client, failing_repository, storage
):
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", "text/plain")},
    )
    assert response.status_code == 500
    assert list(storage.root.iterdir()) == []


def test_create_job_response_never_exposes_storage_path(client):
    response = client.post(
        "/api/v1/jobs",
        files={"file": ("sample.txt", b"text", "text/plain")},
    )
    serialized = response.text.lower()
    assert "storage_key" not in serialized
    assert "source.txt" not in serialized
    assert "\\\\" not in serialized
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_create_job.py -v
```

Expected: FAIL with 404 for `/api/v1/jobs`.

- [ ] **Step 3: Implement dependencies**

`api/dependencies.py` must provide:

```python
def get_db_session() -> Iterator[Session]: ...
def get_job_repository(session: Session = Depends(get_db_session)) -> JobRepository: ...
def get_job_storage(settings: Settings = Depends(get_settings)) -> JobStorage: ...
```

Tests override repository, storage root, and task dispatcher explicitly; do not
connect to Redis from an API unit test.

- [ ] **Step 4: Implement the upload route**

Use a synchronous route so FastAPI runs blocking file/database operations in its
thread pool:

```python
@router.post("/jobs", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    file: UploadFile,
    repository: JobRepository = Depends(get_job_repository),
    storage: JobStorage = Depends(get_job_storage),
) -> JobRead:
    job_id = uuid4()
    now = datetime.now(UTC)
    try:
        stored = storage.save_stream(job_id, file.filename or "upload", file.file)
        job = repository.create_job(
            job_id=job_id,
            source_name=stored.original_name,
            file_type=stored.file_type.value,
            size_bytes=stored.size_bytes,
            storage_key=str(job_id),
            created_at=now,
            expires_at=now + timedelta(hours=get_settings().job_retention_hours),
        )
        repository.commit()
    except Exception:
        storage.delete_job(job_id)
        repository.rollback()
        raise
    dispatch_process_job(str(job_id))
    return job
```

Move dispatch behind `dispatch_process_job(job_id: str) -> None` so tests can
replace it. Map `UploadTooLarge` to 413 and `InvalidUpload` subclasses to explicit
400/415 error responses. Log only `job_id`, file type, byte size, and error code.

- [ ] **Step 5: Register the jobs router and run tests**

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_create_job.py -v
& .\backend\.venv\Scripts\python.exe -m ruff check backend
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/text_verification/api backend/tests/integration/test_create_job.py
git commit -m "feat: create verification jobs from uploads"
```

Include the required commit trailers.

---

### Task 6: Execute a durable Celery pipeline stub

**Files:**
- Create: `backend/src/text_verification/workers/celery_app.py`
- Create: `backend/src/text_verification/workers/pipeline.py`
- Create: `backend/src/text_verification/workers/tasks.py`
- Modify: `backend/src/text_verification/api/routes/jobs.py`
- Test: `backend/tests/integration/test_pipeline_task.py`

**Interfaces:**
- Consumes: `JobRepository.transition()`, a valid stored upload, and `Settings.redis_url`.
- Produces: Celery task `text_verification.process_job`, `dispatch_process_job()`, and `PipelineRunner.run(job_id: UUID)`.

- [ ] **Step 1: Write the failing eager-task test**

Create `backend/tests/integration/test_pipeline_task.py`:

```python
def test_pipeline_stub_completes_job(repository, stored_txt_job, celery_eager):
    from text_verification.workers.tasks import process_job

    result = process_job.delay(str(stored_txt_job.job_id))

    assert result.successful()
    job = repository.get_job(stored_txt_job.job_id)
    assert job.status.value == "completed"
    assert job.progress == 100
    assert [event.status.value for event in repository.list_events_after(
        stored_txt_job.job_id, 0
    )] == [
        "queued",
        "upload_validated",
        "parsing",
        "completed",
    ]
```

Add a test where `PipelineRunner` raises `InvalidUpload`; assert status `failed`,
progress remains below 100, and `error_code == "pipeline_failed"`. Assert the
stored exception message is user-safe and contains no filesystem path.

- [ ] **Step 2: Run tests to verify they fail**

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_pipeline_task.py -v
```

Expected: FAIL because worker modules do not exist.

- [ ] **Step 3: Configure Celery**

Create `workers/celery_app.py`:

```python
from celery import Celery

from text_verification.config import get_settings

settings = get_settings()
celery_app = Celery(
    "text_verification",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["text_verification.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=900,
    task_soft_time_limit=840,
    timezone="UTC",
)
```

- [ ] **Step 4: Implement the pipeline and task**

`PipelineRunner.run()` must transition to `UPLOAD_VALIDATED` at 10,
`PARSING` at 25, verify the stored source still exists, and transition to
`COMPLETED` at 100. It is intentionally a stub: do not parse document text.

`process_job(job_id: str)` must:

1. Parse the UUID.
2. Open its own database session.
3. Load the job and no-op if missing or terminal.
4. Run `PipelineRunner`.
5. On expected validation errors, transition to `FAILED`.
6. On unexpected errors, transition to `FAILED`, log the exception with job ID,
   then re-raise so Celery records failure.
7. Close the session in `finally`.

Implement:

```python
def dispatch_process_job(job_id: str) -> None:
    process_job.delay(job_id)
```

The API route imports this function instead of calling the Celery task directly.

- [ ] **Step 5: Run eager task tests**

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_pipeline_task.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add backend/src/text_verification/workers backend/src/text_verification/api/routes/jobs.py backend/tests/integration/test_pipeline_task.py
git commit -m "feat: process jobs with Celery"
```

Include the required commit trailers.

---

### Task 7: Add job status, SSE progress, and expiry cleanup

**Files:**
- Modify: `backend/src/text_verification/api/routes/jobs.py`
- Modify: `backend/src/text_verification/workers/celery_app.py`
- Modify: `backend/src/text_verification/workers/tasks.py`
- Test: `backend/tests/integration/test_job_progress.py`
- Test: `backend/tests/integration/test_cleanup.py`

**Interfaces:**
- Consumes: `JobRepository.get_job()`, `list_events_after()`, `expire_jobs_before()`, `JobStorage.delete_job()`.
- Produces: `GET /api/v1/jobs/{job_id}`, `GET /api/v1/jobs/{job_id}/events`, and periodic task `text_verification.cleanup_expired_jobs`.

- [ ] **Step 1: Write failing status and SSE tests**

Create `backend/tests/integration/test_job_progress.py`:

```python
def test_get_job_returns_404_for_unknown_job(client):
    response = client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "job_not_found"


def test_sse_replays_events_after_last_event_id(client, completed_job):
    response = client.get(
        f"/api/v1/jobs/{completed_job.job_id}/events",
        headers={"Last-Event-ID": "1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "id: 2" in response.text
    assert '"status":"upload_validated"' in response.text
    assert "event: done" in response.text
```

The test repository must already contain a terminal job so the streaming response
closes deterministically.

- [ ] **Step 2: Run the progress tests to verify they fail**

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_job_progress.py -v
```

Expected: FAIL with 404 for both unimplemented routes.

- [ ] **Step 3: Implement status and resumable SSE**

Implement `GET /jobs/{job_id}` with response model `JobRead`.

Implement an async SSE generator that:

- reads `Last-Event-ID` as a non-negative integer;
- opens a fresh short-lived DB session on each polling iteration;
- emits events as `id`, `event: progress`, and one-line JSON `data`;
- sends `: keepalive` every 15 seconds without events;
- polls every 500 ms;
- emits `event: done` and closes after a terminal status;
- emits `event: expired` and closes when the job is absent or expired;
- never holds a database transaction while sleeping.

- [ ] **Step 4: Write the failing cleanup test**

Create `backend/tests/integration/test_cleanup.py`:

```python
def test_cleanup_expires_database_job_and_deletes_exact_directory(
    repository, storage, expired_job
):
    from text_verification.workers.tasks import cleanup_expired_jobs

    cleanup_expired_jobs()

    assert repository.get_job(expired_job.job_id).status.value == "expired"
    assert not storage.job_directory(expired_job.job_id).exists()
```

Also create a live job directory and assert it remains.

- [ ] **Step 5: Implement and schedule cleanup**

Add a Celery beat schedule:

```python
celery_app.conf.beat_schedule = {
    "cleanup-expired-jobs-hourly": {
        "task": "text_verification.cleanup_expired_jobs",
        "schedule": 3600.0,
    }
}
```

`cleanup_expired_jobs` selects jobs whose `expires_at <= now`, marks each
`EXPIRED`, commits, and then deletes exactly that job's directory. If deletion
fails, log job ID and retry on the next hourly run; do not roll the database state
back to active.

- [ ] **Step 6: Run progress and cleanup tests**

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\integration\test_job_progress.py backend\tests\integration\test_cleanup.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend
git commit -m "feat: stream progress and expire jobs"
```

Include the required commit trailers.

---

### Task 8: Build the Vue upload and progress workspace

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/types/jobs.ts`
- Create: `frontend/src/api/jobs.ts`
- Create: `frontend/src/components/UploadWorkspace.vue`
- Create: `frontend/src/components/JobProgress.vue`
- Create: `frontend/src/views/WorkspaceView.vue`
- Test: `frontend/tests/WorkspaceView.spec.ts`

**Interfaces:**
- Consumes: `POST /api/v1/jobs`, `GET /api/v1/jobs/{id}`, and SSE event payloads.
- Produces: a browser workspace that validates file type/size, uploads one file, and renders durable progress.

- [ ] **Step 1: Scaffold dependencies and test configuration**

Create `frontend/package.json`:

```json
{
  "name": "text-verification-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
  "dev": "vite",
  "build": "vue-tsc -b && vite build",
  "test": "vitest run"
  },
  "dependencies": {
    "vue": "^3.5.0"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.2.0",
    "@vue/test-utils": "^2.4.6",
    "jsdom": "^26.0.0",
    "typescript": "~5.7.0",
    "vite": "^6.0.0",
    "vitest": "^3.0.0",
    "vue-tsc": "^2.2.0"
  }
}
```

Configure Vite to proxy `/api` to `http://localhost:8000` and Vitest to use
`jsdom`.

Install:

```powershell
Set-Location frontend
npm install
Set-Location ..
```

- [ ] **Step 2: Write the failing workspace test**

Create `frontend/tests/WorkspaceView.spec.ts`:

```typescript
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import WorkspaceView from '../src/views/WorkspaceView.vue'

describe('WorkspaceView', () => {
  it('uploads an allowed file and displays progress', async () => {
    const createJob = vi.fn().mockResolvedValue({
      job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
      source_name: 'sample.txt',
      file_type: 'txt',
      size_bytes: 6,
      status: 'queued',
      progress: 0,
      error_code: null,
      error_message: null,
      created_at: '2026-08-14T00:00:00Z',
      expires_at: '2026-08-15T00:00:00Z'
    })
    const subscribe = vi.fn((_id, onEvent) => {
      onEvent({ sequence: 2, status: 'parsing', progress: 25, message: '开始解析' })
      onEvent({ sequence: 3, status: 'completed', progress: 100, message: '完成' })
      return () => undefined
    })
    const wrapper = mount(WorkspaceView, {
      global: { provide: { jobsApi: { createJob, subscribe } } }
    })
    const input = wrapper.get('input[type="file"]')
    const file = new File(['检查'], 'sample.txt', { type: 'text/plain' })

    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    await flushPromises()

    expect(createJob).toHaveBeenCalledWith(file)
    expect(wrapper.text()).toContain('100%')
    expect(wrapper.text()).toContain('完成')
  })
})
```

Add these cases inside the existing `describe` block:

```typescript
it('rejects unsupported extensions before upload', async () => {
  const createJob = vi.fn()
  const wrapper = mount(WorkspaceView, {
    global: { provide: { jobsApi: { createJob, subscribe: vi.fn() } } }
  })
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', {
    value: [new File(['MZ'], 'sample.exe')]
  })

  await input.trigger('change')

  expect(createJob).not.toHaveBeenCalled()
  expect(wrapper.get('[role="alert"]').text()).toContain('DOCX、PDF 或 TXT')
})


it('rejects files larger than 25 MiB before upload', async () => {
  const createJob = vi.fn()
  const wrapper = mount(WorkspaceView, {
    global: { provide: { jobsApi: { createJob, subscribe: vi.fn() } } }
  })
  const input = wrapper.get('input[type="file"]')
  const oversized = new File(
    [new Uint8Array(25 * 1024 * 1024 + 1)],
    'large.txt',
    { type: 'text/plain' }
  )
  Object.defineProperty(input.element, 'files', { value: [oversized] })

  await input.trigger('change')

  expect(createJob).not.toHaveBeenCalled()
  expect(wrapper.get('[role="alert"]').text()).toContain('25 MiB')
})
```

- [ ] **Step 3: Run tests to verify they fail**

```powershell
Set-Location frontend
npm test -- WorkspaceView.spec.ts
Set-Location ..
```

Expected: FAIL because the Vue files do not exist.

- [ ] **Step 4: Implement API types and client**

`types/jobs.ts` defines the exact backend statuses and:

```typescript
export interface JobRead {
  job_id: string
  source_name: string
  file_type: 'docx' | 'pdf' | 'txt'
  size_bytes: number
  status: JobStatus
  progress: number
  error_code: string | null
  error_message: string | null
  created_at: string
  expires_at: string
}

export interface JobProgressEvent {
  sequence: number
  status: JobStatus
  progress: number
  message: string
}
```

`api/jobs.ts` implements:

```typescript
export interface JobsApi {
  createJob(file: File): Promise<JobRead>
  subscribe(
    jobId: string,
    onEvent: (event: JobProgressEvent) => void,
    onError: (message: string) => void
  ): () => void
}
```

Use `fetch` for upload and native `EventSource` for progress. Parse error JSON and
surface its `detail.message`; do not include a local file path.

- [ ] **Step 5: Implement the upload and progress components**

`UploadWorkspace.vue`:

- accepts exactly `.docx,.pdf,.txt`;
- rejects files greater than `25 * 1024 * 1024`;
- emits the selected valid `File`;
- displays validation errors with `role="alert"`.

`JobProgress.vue`:

- renders source name, numeric progress, current message, and terminal state;
- uses a native `<progress max="100">`;
- displays backend failure messages;
- never renders server strings with `v-html`.

`WorkspaceView.vue`:

- injects `JobsApi`;
- creates one job at a time;
- closes a prior EventSource before starting another upload;
- unsubscribes on component unmount;
- retains the last terminal state on screen.

- [ ] **Step 6: Run frontend tests and build**

```powershell
Set-Location frontend
npm test
npm run build
Set-Location ..
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add frontend
git commit -m "feat: add upload progress workspace"
```

Include the required commit trailers.

---

### Task 9: Containerize the vertical slice and verify it end to end

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `compose.yaml`
- Create: `backend/tests/e2e/test_upload_lifecycle.py`
- Create: `README.md`

**Interfaces:**
- Consumes: all services and APIs from Tasks 1-8.
- Produces: `docker compose up --build` development stack and an automated upload-to-completion acceptance test.

- [ ] **Step 1: Write the failing end-to-end test**

Create `backend/tests/e2e/test_upload_lifecycle.py`:

```python
import time

import httpx


def test_txt_upload_reaches_completed_state(live_api_url):
    response = httpx.post(
        f"{live_api_url}/api/v1/jobs",
        files={"file": ("sample.txt", "需要检查".encode(), "text/plain")},
        timeout=30,
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = httpx.get(f"{live_api_url}/api/v1/jobs/{job_id}", timeout=10).json()
        if job["status"] == "completed":
            assert job["progress"] == 100
            return
        time.sleep(0.25)

    raise AssertionError("job did not complete within 30 seconds")
```

- [ ] **Step 2: Create backend and frontend images**

The backend image must:

- use `python:3.12-slim`;
- install `backend` as a wheel;
- run as a non-root user;
- expose 8000;
- use separate Compose commands for API, worker, beat, and migration.

The frontend build must:

- use Node 22 for the build stage;
- produce static assets;
- serve through nginx;
- proxy `/api/` to the API service with buffering disabled for SSE.

- [ ] **Step 3: Create Compose services**

`compose.yaml` defines:

- `postgres` using PostgreSQL 16 with healthcheck and named volume;
- `redis` using Redis 7 with healthcheck;
- one-shot `migrate` running `alembic upgrade head`;
- `api` depending on healthy PostgreSQL/Redis and successful migration;
- `worker` running `celery -A text_verification.workers.celery_app:celery_app worker`;
- `beat` running the Celery scheduler;
- `web` exposing `http://localhost:8080`;
- a named `job-data` volume mounted at `/var/lib/text-verification/jobs` by API,
  worker, and beat.

Do not publish PostgreSQL or Redis ports by default. Add a `dev` profile override
only if local test commands need host access.

- [ ] **Step 4: Document exact developer workflow**

`README.md` must include:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose exec api pytest
docker compose logs -f api worker
docker compose down
```

Document:

- application URL `http://localhost:8080`;
- health URL `http://localhost:8080/api/v1/health`;
- supported types and 25 MiB limit;
- 24-hour retention;
- the fact that this foundation only completes a stub pipeline;
- how to run backend and frontend tests;
- how to run Alembic upgrade/downgrade;
- how to stop without deleting volumes and how to explicitly remove development volumes.

- [ ] **Step 5: Start the stack and run the acceptance test**

Run:

```powershell
docker compose up --build -d
docker compose ps
$env:LIVE_API_URL='http://localhost:8080'
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests\e2e\test_upload_lifecycle.py -v
```

Expected:

- all six services are healthy/running as applicable;
- the E2E test passes;
- `GET http://localhost:8080/api/v1/health` returns 200.

- [ ] **Step 6: Run the complete foundation verification**

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests -v
& .\backend\.venv\Scripts\python.exe -m ruff check backend
& .\backend\.venv\Scripts\python.exe -m mypy backend\src
Set-Location frontend
npm test
npm run build
Set-Location ..
```

Expected: all commands pass.

- [ ] **Step 7: Commit**

```powershell
git add backend frontend compose.yaml README.md
git commit -m "feat: deliver platform foundation"
```

Include the required commit trailers.

---

## Follow-on Plans

Create and approve these plans separately after this foundation is running:

1. `document-docx-txt-workflow`: real DOCX/TXT parsing, preview mapping, review decisions, precise DOCX/TXT export, CSV/XLSX reports.
2. `proofreading-engines`: legacy rule migration, Python Aho-Corasick sensitive-word engine, pycorrector, LanguageTool, plugin partial-failure behavior.
3. `pdf-workflow`: PDF.js viewer, text/scanned classification, OCR, coordinate mapping, text-PDF replacement, scanned-PDF annotation.
4. `dictionary-management-and-hardening`: shared dictionary CRUD/import/version/rollback, IndexedDB personal dictionaries, metrics, load tests, and deployment hardening.
