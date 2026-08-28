# Text Verification

面向企业内网的中英文文档预检平台，目标是统一提供错别字检查、格式检查、行业敏感词检测与替换、文件上传、在线审阅和结果导出。

> 当前状态：可用的文档预检版本。已经实现七种文档格式和直接文本检查、六层规则引擎、
> 自定义术语与禁用词、合规扫描、在线审阅、查找替换、修订导出、HTML 报告和可选的大模型
> 语义复核。PostgreSQL、Redis/Celery、SSE 与 24 小时清理基础仍保留；原异步 Worker 流水线
> 继续作为后续任务化处理入口。

## 已实现与未实现

### 已实现

- DOCX、DOC、PDF、TXT、RTF、Markdown、CSV 文件上传，以及直接粘贴文本。
- FastAPI API、PostgreSQL 任务与事件持久化。
- Redis + Celery 异步任务调度。
- SSE 进度事件推送。
- 每个任务使用独立 UUID 目录存储上传文件。
- 24 小时过期清理。
- Vue 3 响应式审阅界面、亮/暗主题和会话恢复。
- 中文错别字、英文拼写、异形词、全半角、标点、语法、表达、数字格式和术语一致性检查。
- 身份证、手机号、邮箱、银行卡、密钥、敏感表述及广告法极限词检查。
- 六种文档场景、自定义术语表、禁用词库及批量导入。
- 问题接受、忽略、撤销、批量操作、修改预览、原文编辑和查找替换。
- DOCX/DOC/PDF/TXT/RTF/Markdown/CSV 原格式导出及 HTML 检查报告。
- DOCX 修订痕迹、PDF 高亮批注和文本格式修订标记。
- 可选的 OpenAI 兼容语义复核；未配置密钥时自动使用纯本地规则。

### 后续演进

- 将当前同步预检能力接入 Celery 分阶段任务流水线。
- 扫描型 PDF OCR 与版式重建。
- 共享词库数据库管理、版本及回滚。
- 基于 `DocumentModel` 精确块定位的审阅决策持久化。

## 技术架构与请求数据流

```text
Browser → nginx → FastAPI → PostgreSQL
                      ↓
                 Redis/Celery → Job Storage
```

- `apps/web` 提供 Vue 3 审阅前端和 nginx 静态站点/反向代理。
- `apps/api` 提供 FastAPI API、Celery Worker、Alembic 迁移和后端测试。
- PostgreSQL 是任务与事件的持久化来源；Redis 负责队列；Worker 当前执行 Stub 流水线。
- 浏览器可通过同步预检 REST 接口完成完整检查和导出；原任务接口继续通过 SSE 推送进度。

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

- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/events`
- `GET /api/v1/health`
- `POST /api/v1/analyze`
- `POST /api/v1/export`
- `POST /api/v1/export-original`
- `GET /api/v1/scenarios`
- `GET /api/v1/formats`

## 文件限制、保留与安全边界

- 支持文件类型：`.docx`、`.doc`、`.pdf`、`.txt`、`.rtf`、`.md`、`.csv`
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

交互式检查接口已加载包内运行时词表。合规词表变更需同步更新运行时副本并执行规则测试。

## 环境限制与后续路线图

### 当前环境限制

- Docker / Compose 验证依赖宿主机可用 Docker。
- PostgreSQL 相关集成测试必须连接真实 PostgreSQL。
- 不允许使用 SQLite 代替 PostgreSQL 合约验证。

### 后续路线图

- 异步流水线接入现有解析与规则引擎
- 扫描型 PDF OCR 工作流
- 共享词库管理能力
- 精确块级替换与审阅决策持久化
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
