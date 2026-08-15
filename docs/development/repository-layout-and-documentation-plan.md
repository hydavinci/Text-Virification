# Repository Layout and Documentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the repository as an `apps/`-based Monorepo, remove the retired Flask Demo, normalize resource and documentation names, and replace the root README with an accurate Chinese project guide.

**Architecture:** Move deployable applications to `apps/api` and `apps/web` without changing package names or runtime contracts. Move Compose to `infra`, compliance resources to `resources/dictionaries`, and project documents to purpose-specific directories; update every path consumer in the same task that moves its dependency.

**Tech Stack:** Git, PowerShell, Python 3.12, FastAPI, pytest, Ruff, mypy, Vue 3, TypeScript, Vitest, Vite, Docker Compose

**Spec:** `docs/architecture/repository-layout-and-documentation.md`

## Global Constraints

- Preserve Python package `text_verification`, npm package names, HTTP API paths, Celery task names, database schema, service names, ports, named volumes, and environment variable names.
- Delete `translation-pre-checker/`; do not migrate code from the retired Flask Demo.
- Preserve both dictionary JSON payloads byte-for-byte while renaming them.
- Use kebab-case repository resource names and lowercase locale suffix `zh-cn`.
- Root README content is Chinese-first; commands, paths, API names, and technology names remain English.
- Do not claim proofreading, sensitive-word checking, review, replacement, or export functionality is implemented.
- Do not add runtime dependencies or use SQLite in place of PostgreSQL.
- Docker and PostgreSQL are unavailable on the current host; record Compose, container, live E2E, and PostgreSQL checks as environment gaps rather than successful verification.
- Use Git-aware moves for tracked files and include the required commit trailers in every commit.

---

### Task 1: Move the API and Web applications

**Files:**
- Move: `backend/` → `apps/api/`
- Move: `frontend/` → `apps/web/`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: existing Python package `text_verification`, backend test suite, Vue package, and frontend test suite.
- Produces: stable application roots `apps/api` and `apps/web` consumed by Compose, README, and developer commands.

- [ ] **Step 1: Capture the pre-move application baselines**

Run from the repository root:

```powershell
& .\backend\.venv\Scripts\python.exe -m pytest backend\tests -q
& .\backend\.venv\Scripts\python.exe -m ruff check backend
& .\backend\.venv\Scripts\python.exe -m mypy backend\src
Set-Location frontend
npm test -- --run
npm run build
Set-Location ..
```

Expected: backend reports 71 passing tests with only documented environment skips; Ruff and mypy pass; frontend reports 26 passing tests and a successful production build. If the isolated worktree has no dependencies, create `backend/.venv`, install `backend[dev]`, and run `npm ci` before capturing the baseline.

- [ ] **Step 2: Move both tracked application trees**

Create `apps/`, then use Git-aware moves:

```powershell
New-Item -ItemType Directory -Path apps -Force | Out-Null
git mv backend apps/api
git mv frontend apps/web
```

Expected: `git status --short` shows renames under `apps/api` and `apps/web`; no tracked application file is deleted and recreated as unrelated content.

- [ ] **Step 3: Update repository ignore paths**

Replace application-specific entries in `.gitignore`:

```gitignore
apps/api/.venv/
apps/web/node_modules/
apps/web/dist/
apps/web/*.tsbuildinfo
```

Remove:

```gitignore
backend/.venv/
frontend/node_modules/
frontend/dist/
frontend/*.tsbuildinfo
translation-pre-checker/.venv/
```

Keep the existing root cache, environment, IDE, log, `var/`, `.worktrees/`, and `.superpowers/` rules.

- [ ] **Step 4: Verify application tests from their new roots**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -q
& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api
& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src
Set-Location apps\web
npm test -- --run
npm run build
Set-Location ..\..
```

If the move did not carry ignored dependency directories in the isolated worktree, create `apps/api/.venv`, install the API project with `-e "apps/api[dev]"`, and run `npm ci --prefix apps/web` before retrying. Expected: the same test counts and build result as Step 1.

- [ ] **Step 5: Verify old application roots are gone**

Run:

```powershell
if (Test-Path backend) { throw "backend still exists" }
if (Test-Path frontend) { throw "frontend still exists" }
if (-not (Test-Path apps\api\src\text_verification)) { throw "API source missing" }
if (-not (Test-Path apps\web\src)) { throw "Web source missing" }
git diff --check
```

Expected: no exception and no whitespace errors.

- [ ] **Step 6: Commit the application move**

```powershell
git add .gitignore apps
git commit -m "refactor: organize applications under apps" `
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" `
  -m "Copilot-Session: dc70da84-4b3a-45f3-8709-b22c5f7f49e1"
```

---

### Task 2: Move and rewire Docker Compose infrastructure

**Files:**
- Move: `compose.yaml` → `infra/compose.yaml`
- Verify: `apps/api/Dockerfile`
- Verify: `apps/api/.dockerignore`
- Verify: `apps/web/Dockerfile`
- Verify: `apps/web/.dockerignore`

**Interfaces:**
- Consumes: application roots `apps/api` and `apps/web` from Task 1, root `.env`.
- Produces: the canonical development stack command `docker compose -f infra/compose.yaml ...`.

- [ ] **Step 1: Record the path-dependent Compose fields**

Run:

```powershell
rg -n "context:|env_file:|Dockerfile|backend|frontend" compose.yaml
```

Expected before the move: API context is `./backend`, Web context is `./frontend`, and `env_file` is `.env`. These values would be invalid after moving the file to `infra/`.

- [ ] **Step 2: Move Compose into `infra/`**

```powershell
New-Item -ItemType Directory -Path infra -Force | Out-Null
git mv compose.yaml infra/compose.yaml
```

- [ ] **Step 3: Rebase Compose paths from the new file location**

In `infra/compose.yaml`, set:

```yaml
x-backend-service: &backend-service
  build:
    context: ../apps/api
  image: text-verification-backend:development
  env_file:
    - ../.env
```

Set the Web build context to:

```yaml
  web:
    build:
      context: ../apps/web
```

Do not change service names, commands, ports, health checks, dependency conditions, environment variables, volumes, image names, or restart policies.

- [ ] **Step 4: Run static Compose path checks**

Run:

```powershell
$compose = Get-Content infra\compose.yaml -Raw
if ($compose -notmatch 'context:\s+\.\./apps/api') { throw "API context is stale" }
if ($compose -notmatch 'context:\s+\.\./apps/web') { throw "Web context is stale" }
if ($compose -notmatch '\.\./\.env') { throw "env_file is stale" }
if ($compose -match '\./backend|\./frontend') { throw "old app path remains" }
if (-not (Test-Path apps\api\Dockerfile)) { throw "API Dockerfile missing" }
if (-not (Test-Path apps\web\Dockerfile)) { throw "Web Dockerfile missing" }
```

Expected: no exception.

- [ ] **Step 5: Attempt the authoritative Compose validation**

Run:

```powershell
docker compose -f infra/compose.yaml config
```

Expected on a Docker-capable host: exit 0 with seven services and the existing two named volumes. On the current host, record `docker` as unavailable; do not replace this command with a YAML-only claim.

- [ ] **Step 6: Commit the infrastructure move**

```powershell
git add infra apps\api\Dockerfile apps\web\Dockerfile
git commit -m "refactor: move compose configuration to infra" `
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" `
  -m "Copilot-Session: dc70da84-4b3a-45f3-8709-b22c5f7f49e1"
```

---

### Task 3: Remove the retired Demo and organize resources and documents

**Files:**
- Delete: `translation-pre-checker/`
- Move: `wordlists-backup/README.md` → `resources/dictionaries/README.md`
- Move: `wordlists-backup/ad_extreme_words.json` → `resources/dictionaries/advertising-extreme-terms.zh-cn.json`
- Move: `wordlists-backup/sensitive_rules.json` → `resources/dictionaries/compliance-sensitive-rules.zh-cn.json`
- Move: `docs/superpowers/specs/2026-08-14-document-proofreading-web-design.md` → `docs/architecture/document-verification-platform.md`
- Move: `docs/superpowers/plans/2026-08-14-platform-foundation.md` → `docs/development/platform-foundation-plan.md`
- Modify: `docs/architecture/document-verification-platform.md`
- Modify: `docs/development/platform-foundation-plan.md`
- Modify: `resources/dictionaries/README.md`

**Interfaces:**
- Consumes: the approved target layout and unchanged dictionary JSON payloads.
- Produces: canonical resource paths and user-facing architecture/development documentation without dependencies on the retired Demo.

- [ ] **Step 1: Capture dictionary hashes before moving**

Run:

```powershell
$adHash = (Get-FileHash wordlists-backup\ad_extreme_words.json -Algorithm SHA256).Hash
$rulesHash = (Get-FileHash wordlists-backup\sensitive_rules.json -Algorithm SHA256).Hash
Set-Content -Path $env:TEMP\text-verification-dictionary-hashes.txt `
  -Value @($adHash, $rulesHash)
```

Expected: two non-empty SHA-256 values. The temporary hash file contains hashes only, not dictionary content.

- [ ] **Step 2: Delete the retired Flask Demo**

Delete tracked files with:

```powershell
git rm -r translation-pre-checker
```

If the ignored path `translation-pre-checker/.venv` remains, delete that exact directory only:

```powershell
if (Test-Path translation-pre-checker\.venv) {
  Remove-Item -LiteralPath translation-pre-checker\.venv -Recurse
}
if (Test-Path translation-pre-checker) {
  $remaining = Get-ChildItem -LiteralPath translation-pre-checker -Force
  if ($remaining) { throw "Unexpected untracked legacy files remain" }
  Remove-Item -LiteralPath translation-pre-checker
}
```

Do not copy any Flask source into `apps/api`.

- [ ] **Step 3: Move and rename dictionary resources**

```powershell
New-Item -ItemType Directory -Path resources\dictionaries -Force | Out-Null
git mv wordlists-backup\ad_extreme_words.json `
  resources\dictionaries\advertising-extreme-terms.zh-cn.json
git mv wordlists-backup\sensitive_rules.json `
  resources\dictionaries\compliance-sensitive-rules.zh-cn.json
git mv wordlists-backup\README.md resources\dictionaries\README.md
```

Expected: `wordlists-backup/` no longer exists.

- [ ] **Step 4: Prove dictionary payloads are unchanged**

Run:

```powershell
$before = Get-Content $env:TEMP\text-verification-dictionary-hashes.txt
$after = @(
  (Get-FileHash resources\dictionaries\advertising-extreme-terms.zh-cn.json -Algorithm SHA256).Hash
  (Get-FileHash resources\dictionaries\compliance-sensitive-rules.zh-cn.json -Algorithm SHA256).Hash
)
if (Compare-Object $before $after) { throw "Dictionary payload changed during move" }
Remove-Item -LiteralPath $env:TEMP\text-verification-dictionary-hashes.txt
```

Expected: no exception.

- [ ] **Step 5: Rewrite the dictionary README for the new platform**

Replace `resources/dictionaries/README.md` with:

```markdown
# 合规词库资源

本目录保存由合规或法务团队审定的中文检查资源：

- `advertising-extreme-terms.zh-cn.json`：广告法绝对化用语词表。
- `compliance-sensitive-rules.zh-cn.json`：敏感内容分类和规范表述替换规则。

当前平台基础版本仍使用 Stub 流水线，尚未加载这些文件。后续敏感词引擎应通过配置
读取本目录，不应将文件复制覆盖到应用源码目录。

词库内容由合规或法务团队维护。工程变更不得擅自扩充、删除或重新解释词条。
```

- [ ] **Step 6: Move architecture and development documents**

```powershell
git mv docs\superpowers\specs\2026-08-14-document-proofreading-web-design.md `
  docs\architecture\document-verification-platform.md
git mv docs\superpowers\plans\2026-08-14-platform-foundation.md `
  docs\development\platform-foundation-plan.md
```

Remove the now-empty tracked directory structure implicitly; Git does not track empty directories.

- [ ] **Step 7: Update document references and historical path notes**

In `docs/development/platform-foundation-plan.md`:

- Change its `**Spec:**` link to `docs/architecture/document-verification-platform.md`.
- Change active repository paths from `backend/` to `apps/api/`.
- Change active repository paths from `frontend/` to `apps/web/`.
- Change active Compose commands to include `-f infra/compose.yaml`.
- Add an opening note that the foundation was originally implemented before the Monorepo migration and that paths shown by historical commit output may use the old layout.
- Replace claims that the Flask Demo remains supported with a historical statement that it was preserved during the foundation phase and removed by the approved repository-layout migration.

In `docs/architecture/document-verification-platform.md`:

- Replace the current-state paragraph about a Flask Demo under `translation-pre-checker/` with the current `apps/api` and `apps/web` platform state.
- Add a related-design link to `docs/architecture/repository-layout-and-documentation.md`.

Do not alter product requirements or claim follow-on proofreading features are implemented.

- [ ] **Step 8: Search for stale resource and document paths**

Run:

```powershell
rg -n "wordlists-backup|ad_extreme_words|sensitive_rules|docs/superpowers" `
  . -g "!apps/web/node_modules/**" -g "!apps/web/dist/**" -g "!.git/**"
```

Expected: no matches. Then run:

```powershell
rg -n "translation-pre-checker" docs resources README.md .gitignore
```

Expected: matches are limited to explicit historical migration context in
`docs/architecture/repository-layout-and-documentation.md` and the historical note in
`docs/development/platform-foundation-plan.md`; no command or active path references it.

- [ ] **Step 9: Commit resource and document organization**

```powershell
git add -A translation-pre-checker wordlists-backup resources docs
git commit -m "refactor: organize resources and documentation" `
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" `
  -m "Copilot-Session: dc70da84-4b3a-45f3-8709-b22c5f7f49e1"
```

---

### Task 4: Replace the project README and verify the Monorepo

**Files:**
- Modify: `README.md`
- Verify: `.env.example`
- Verify: `.gitignore`
- Verify: `infra/compose.yaml`
- Verify: `docs/architecture/*.md`
- Verify: `docs/development/*.md`

**Interfaces:**
- Consumes: final directory and command paths from Tasks 1-3.
- Produces: the canonical onboarding and operational guide for developers.

- [ ] **Step 1: Write the README capability boundary first**

Replace the title and opening sections with:

```markdown
# Text Verification

面向企业内网的中英文文档预检平台，目标是统一提供错别字检查、格式检查、行业敏感词
检测与替换、文件上传、在线审阅和结果导出。

> 当前状态：平台基础版本。已经实现 DOCX/PDF/TXT 安全上传、PostgreSQL 任务持久化、
> Redis/Celery 异步调度、SSE 进度推送、24 小时清理和 Vue 上传界面。Worker 目前
> 仍是 Stub 流水线，尚未实现正文解析、校对引擎、问题审阅和文件导出。
```

This statement is the source of truth for all later README sections.

- [ ] **Step 2: Add architecture and repository layout sections**

Document this request flow exactly:

```text
Browser → nginx → FastAPI → PostgreSQL
                      ↓
                 Redis/Celery → Job Storage
```

Add a directory table covering:

- `apps/api` — FastAPI, Celery, Alembic, backend tests.
- `apps/web` — Vue 3, SSE client, nginx, frontend tests.
- `infra` — Docker Compose development stack.
- `resources/dictionaries` — compliance-owned dictionary resources not yet wired into the Stub.
- `docs/architecture` — product and architecture decisions.
- `docs/development` — implementation plans and engineering history.

- [ ] **Step 3: Add exact quick-start and lifecycle commands**

Use:

```powershell
Copy-Item .env.example .env
docker compose -f infra/compose.yaml up --build -d
docker compose -f infra/compose.yaml exec api pytest
docker compose -f infra/compose.yaml logs -f api worker
docker compose -f infra/compose.yaml down
```

Document application URL `http://localhost:8080` and health URL
`http://localhost:8080/api/v1/health`. State that `migrate` exits successfully while the six long-running services remain.

- [ ] **Step 4: Add local development, tests, and migrations**

Backend setup and checks:

```powershell
py -3.12 -m venv apps\api\.venv
& .\apps\api\.venv\Scripts\python.exe -m pip install -e "apps\api[dev]"
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -v
& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api
& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src
```

Frontend setup and checks:

```powershell
Set-Location apps\web
npm ci
npm test
npm run build
Set-Location ..\..
```

Migration commands:

```powershell
docker compose -f infra/compose.yaml run --rm migrate alembic upgrade head
docker compose -f infra/compose.yaml run --rm migrate alembic downgrade -1
```

Live acceptance command:

```powershell
$env:LIVE_API_URL='http://localhost:8080'
& .\apps\api\.venv\Scripts\python.exe -m pytest `
  apps\api\tests\e2e\test_upload_lifecycle.py -v
```

- [ ] **Step 5: Add API, limits, security, resources, and roadmap**

Document:

- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/events`
- `GET /api/v1/health`
- `.docx`, `.pdf`, `.txt`, exact 25 MiB maximum, 24-hour retention.
- Content/signature checks, DOCX ZIP limits, isolated UUID storage, server-generated filenames, MIME consistency checks, terminal-state protection, and stale orphan cleanup.
- PostgreSQL tests require `TEST_DATABASE_URL`; live tests require `LIVE_API_URL`; SQLite is not a substitute.
- Dictionary resources are compliance-owned and not yet integrated.
- Follow-on work: DOCX/TXT parsing and precise export, proofreading engines, PDF/OCR workflow, dictionary management and production hardening.

Link:

```markdown
- [平台架构设计](docs/architecture/document-verification-platform.md)
- [仓库重组设计](docs/architecture/repository-layout-and-documentation.md)
- [平台基础实施记录](docs/development/platform-foundation-plan.md)
```

- [ ] **Step 6: Add stop/reset commands without data-loss ambiguity**

Document:

```powershell
docker compose -f infra/compose.yaml down
docker compose -f infra/compose.yaml down --volumes
```

State that the first command preserves `postgres-data` and `job-data`; the second permanently deletes development database and uploaded-job data.

- [ ] **Step 7: Verify every README path and command anchor**

Run:

```powershell
$required = @(
  'apps\api\pyproject.toml',
  'apps\web\package.json',
  'infra\compose.yaml',
  'resources\dictionaries\README.md',
  'docs\architecture\document-verification-platform.md',
  'docs\architecture\repository-layout-and-documentation.md',
  'docs\development\platform-foundation-plan.md'
)
$missing = $required | Where-Object { -not (Test-Path $_) }
if ($missing) { throw "README targets missing: $missing" }
rg -n "backend/|frontend/|wordlists-backup|docs/superpowers" README.md
```

Expected: every target exists and the final `rg` returns no matches.

- [ ] **Step 8: Run complete verification**

Run:

```powershell
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -q
& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api
& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src
Set-Location apps\web
npm test -- --run
npm run build
Set-Location ..\..
git diff --check
git status --short
```

Expected: backend and frontend results match the pre-move baselines, no whitespace errors, and only intended README changes remain uncommitted.

Attempt:

```powershell
docker compose -f infra/compose.yaml config
```

Expected on a Docker-capable host: exit 0. On the current host: explicitly report Docker unavailable, PostgreSQL integration tests skipped without `TEST_DATABASE_URL`, and live E2E skipped without `LIVE_API_URL`.

- [ ] **Step 9: Commit the README**

```powershell
git add README.md
git commit -m "docs: document the text verification monorepo" `
  -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>" `
  -m "Copilot-Session: dc70da84-4b3a-45f3-8709-b22c5f7f49e1"
```

- [ ] **Step 10: Verify final repository state**

Run:

```powershell
git status --short
git --no-pager log -5 --oneline
```

Expected: clean working tree and four focused implementation commits after the design and plan commits.
