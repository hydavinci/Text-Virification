# Text Verification

面向企业内网的中英文文档预检平台，目标是统一提供错别字检查、格式检查、行业敏感词检测与替换、文件上传、在线审阅和结果导出。

> 当前状态：平台基础版本。已经实现 DOCX/PDF/TXT 安全上传、PostgreSQL 任务持久化、Redis/Celery 异步调度、SSE 进度推送、24 小时清理和 Vue 上传界面。Worker 目前仍是 Stub 流水线，尚未实现正文解析、校对引擎、问题审阅和文件导出。

## 已实现与未实现

### 已实现

- DOCX、PDF、TXT 文件上传。
- FastAPI API、PostgreSQL 任务与事件持久化。
- Redis + Celery 异步任务调度。
- SSE 进度事件推送。
- 每个任务使用独立 UUID 目录存储上传文件。
- 24 小时过期清理。
- Vue 3 上传与任务状态界面。

### 明确未实现

- DOCX/TXT 正文解析与精确导出。
- 错别字、语法、格式、敏感词实际校对引擎。
- 在线问题审阅、逐条接受/忽略。
- 修改版文档与问题报告导出。
- 扫描型 PDF OCR 工作流。
- 词库资源在运行时接线。

## 技术架构与请求数据流

```text
Browser → nginx → FastAPI → PostgreSQL
                      ↓
                 Redis/Celery → Job Storage
```

- `apps/web` 提供 Vue 3 前端和 nginx 静态站点/反向代理。
- `apps/api` 提供 FastAPI API、Celery Worker、Alembic 迁移和后端测试。
- PostgreSQL 是任务与事件的持久化来源；Redis 负责队列；Worker 当前执行 Stub 流水线。
- 浏览器通过 REST 提交任务，通过 SSE 订阅任务进度。

## Monorepo 目录说明

| 路径 | 说明 |
| --- | --- |
| `apps/api` | FastAPI、Celery、Alembic、backend tests |
| `apps/web` | Vue 3、SSE client、nginx、frontend tests |
| `infra` | Docker Compose development stack |
| `resources/dictionaries` | compliance-owned dictionary resources not yet wired into the Stub |
| `docs/architecture` | product and architecture decisions |
| `docs/development` | implementation plans and engineering history |

## Docker Compose 快速启动

在仓库根目录执行：

```powershell
Copy-Item .env.example .env
docker compose -f infra/compose.yaml up --build -d
docker compose -f infra/compose.yaml exec api pytest
docker compose -f infra/compose.yaml logs -f api worker
docker compose -f infra/compose.yaml down
```

- 应用地址：`http://localhost:8080`
- 健康检查：`http://localhost:8080/api/v1/health`
- `migrate` 服务只负责执行 Alembic，成功后退出；其余六个长运行服务继续保持运行。

## 本地后端与前端开发、测试、构建

### Backend

```powershell
py -3.12 -m venv apps\api\.venv
& .\apps\api\.venv\Scripts\python.exe -m pip install -e "apps\api[dev]"
& .\apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests -v
& .\apps\api\.venv\Scripts\python.exe -m ruff check apps\api
& .\apps\api\.venv\Scripts\python.exe -m mypy apps\api\src
```

### Frontend

```powershell
Set-Location apps\web
npm ci
npm test
npm run build
Set-Location ..\..
```

## API 与 SSE 端点

- `POST /api/v1/jobs`（支持 `scenario` 与重复 `enabled_categories` 表单字段）
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/events`
- `GET /api/v1/jobs/{job_id}/document`
- `GET /api/v1/jobs/{job_id}/issues`
- `GET /api/v1/jobs/{job_id}/summary`
- `GET /api/v1/health`

## 文件限制、保留与安全边界

- 支持文件类型：`.docx`、`.pdf`、`.txt`
- 上传大小上限：精确为 25 MiB
- 保留策略：任务和上传文件保留 24 小时
- 校验边界：内容类型与文件签名双重检查，MIME 一致性检查
- DOCX 安全：限制 ZIP 结构与解压风险
- 存储策略：每个任务使用独立 UUID 目录，服务端生成文件名，不暴露服务器文件系统路径
- 状态保护：终态任务不会被后续事件回退覆盖
- 清理策略：后台会清理过期任务与陈旧孤儿文件

## Alembic 数据库迁移

```powershell
docker compose -f infra/compose.yaml run --rm migrate alembic upgrade head
docker compose -f infra/compose.yaml run --rm migrate alembic downgrade -1
```

PostgreSQL 集成测试要求设置 `TEST_DATABASE_URL`；Live 测试要求设置 `LIVE_API_URL`；SQLite 不是替代方案。

```powershell
$env:LIVE_API_URL='http://localhost:8080'
& .\apps\api\.venv\Scripts\python.exe -m pytest `
  apps\api\tests\e2e\test_upload_lifecycle.py -v
```

## 词库资源及维护说明

`resources/dictionaries` 中的词库资源由合规或法务团队维护：

- `advertising-extreme-terms.zh-cn.json`
- `compliance-sensitive-rules.zh-cn.json`

这些资源当前尚未接入 Stub 流水线；后续敏感词引擎应通过配置读取，而不是复制覆盖到应用源码目录。

## 环境限制与后续路线图

### 当前环境限制

- Docker / Compose 验证依赖宿主机可用 Docker。
- PostgreSQL 相关集成测试必须连接真实 PostgreSQL。
- 不允许使用 SQLite 代替 PostgreSQL 合约验证。

### 后续路线图

- DOCX/TXT 解析与精确导出
- 校对引擎与问题模型
- PDF/OCR 工作流
- 词库管理能力
- 生产加固与可观测性完善

## 停止与重置

```powershell
docker compose -f infra/compose.yaml down
docker compose -f infra/compose.yaml down --volumes
```

第一条命令保留 `postgres-data` 与 `job-data`；第二条命令会永久删除开发数据库和上传任务数据。

## 文档链接

- [平台架构设计](docs/architecture/document-verification-platform.md)
- [仓库重组设计](docs/architecture/repository-layout-and-documentation.md)
- [平台基础实施记录](docs/development/platform-foundation-plan.md)
