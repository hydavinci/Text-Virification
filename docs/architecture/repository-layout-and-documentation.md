# 仓库目录与项目文档重组设计

日期：2026-08-15

## 背景

当前仓库同时包含新的 Vue 3 + FastAPI 平台、旧 Flask Demo、独立词库备份和
Superpowers 过程文档。新平台的 `backend/`、`frontend/` 能正常工作，但仓库顶层
缺少统一的 Monorepo 语义；旧目录名称仍引用已废弃的
`translation-pre-checker`，根 README 也主要描述基础设施，未完整说明产品定位、
当前能力、目录结构和后续路线。

本次重组只改变仓库布局、文件名称和文档，不改变 API、任务状态、数据库模型、
运行时行为或包名。

## 目标

1. 使用 `apps/` 表达所有可部署应用。
2. 删除不再维护的旧 Flask Demo。
3. 将词库资源集中到名称明确的目录，并使用可读、带 locale 的文件名。
4. 将架构文档和开发过程文档分开。
5. 提供以中文为主、命令和技术名称保留英文的项目 README。
6. 更新所有构建、测试、Docker 和文档引用，确保重组后现有行为不变。

## 非目标

- 不实现文档解析、错别字检查、敏感词引擎、在线审阅或导出。
- 不修改现有词库内容。
- 不重命名 Python 包 `text_verification`、npm 包或 HTTP API 路径。
- 不改变 PostgreSQL、Redis、Celery、SSE 或文件保留策略。
- 不引入新的运行时依赖。

## 目标目录

```text
text-verification/
├─ apps/
│  ├─ api/
│  │  ├─ alembic/
│  │  ├─ src/text_verification/
│  │  ├─ tests/
│  │  ├─ Dockerfile
│  │  ├─ alembic.ini
│  │  └─ pyproject.toml
│  └─ web/
│     ├─ src/
│     ├─ tests/
│     ├─ Dockerfile
│     ├─ nginx.conf
│     └─ package.json
├─ resources/
│  └─ dictionaries/
│     ├─ README.md
│     ├─ advertising-extreme-terms.zh-cn.json
│     └─ compliance-sensitive-rules.zh-cn.json
├─ infra/
│  └─ compose.yaml
├─ docs/
│  ├─ architecture/
│  │  ├─ document-verification-platform.md
│  │  └─ repository-layout-and-documentation.md
│  └─ development/
│     └─ platform-foundation-plan.md
├─ .env.example
├─ .gitignore
└─ README.md
```

## 迁移映射

| 当前路径 | 目标路径 | 处理 |
| --- | --- | --- |
| `backend/` | `apps/api/` | 保留全部代码、测试、迁移和镜像配置 |
| `frontend/` | `apps/web/` | 保留全部代码、测试和 nginx 配置 |
| `translation-pre-checker/` | 无 | 删除旧 Flask Demo |
| `wordlists-backup/` | `resources/dictionaries/` | 保留并更新说明 |
| `wordlists-backup/ad_extreme_words.json` | `resources/dictionaries/advertising-extreme-terms.zh-cn.json` | 仅重命名 |
| `wordlists-backup/sensitive_rules.json` | `resources/dictionaries/compliance-sensitive-rules.zh-cn.json` | 仅重命名 |
| `docs/superpowers/specs/2026-08-14-document-proofreading-web-design.md` | `docs/architecture/document-verification-platform.md` | 移动并更新交叉引用 |
| `docs/superpowers/plans/2026-08-14-platform-foundation.md` | `docs/development/platform-foundation-plan.md` | 移动并更新交叉引用 |
| `compose.yaml` | `infra/compose.yaml` | 移动并修正相对路径 |

所有移动操作应保留 Git 历史。旧 Demo 的删除是明确的产品决定，不迁移其中代码。

## 构建与部署路径

`infra/compose.yaml` 从仓库根目录通过以下命令调用：

```powershell
docker compose -f infra/compose.yaml up --build -d
```

Compose 中的 build context 以仓库根目录为基准，Dockerfile 分别位于
`apps/api/Dockerfile` 和 `apps/web/Dockerfile`。后端镜像继续安装
`text-verification` wheel；前端镜像继续构建 Vue 静态资源并通过 nginx 代理
`/api/`。服务名、环境变量、命名卷、健康检查和端口保持不变。

Alembic、pytest、Ruff 和 mypy 命令全部切换到 `apps/api`；npm 测试和构建命令
切换到 `apps/web`。`.dockerignore` 和 `.gitignore` 同步使用新路径，并删除旧
Flask Demo 的忽略规则。

## 词库说明

词库 JSON 内容保持原样。`resources/dictionaries/README.md` 说明：

- 两个文件的用途、结构和维护责任；
- 内容必须由合规或法务团队审定；
- 当前平台基础版本尚未加载这些词库；
- 后续敏感词引擎应通过配置读取资源，而不是复制覆盖应用目录；
- 不再引用旧 Flask Demo、5088 端口或 mtime 热加载行为。

## 根 README 信息架构

根 README 使用中文，技术名称、路径和命令保持英文。内容顺序如下：

1. 项目定位和当前状态；
2. 已实现能力与明确未实现能力；
3. 技术架构和请求数据流；
4. Monorepo 目录说明；
5. Docker Compose 快速启动；
6. 本地后端和前端开发、测试、构建命令；
7. API 与 SSE 端点；
8. 文件类型、25 MiB 限制、24 小时保留和安全边界；
9. Alembic 数据库迁移；
10. 词库资源及维护说明；
11. 环境限制和后续路线图；
12. 架构与开发文档链接。

README 必须明确当前 Worker 是 Stub 流水线，不得宣称错别字检查、格式检查、
敏感词检查、替换、审阅或导出已完成。

## 错误处理与兼容性

本次不新增运行时错误类型。路径迁移后，任何失效引用都视为迁移缺陷，不使用兼容
软链接、重复目录或静默回退。Compose、Docker、测试和文档必须一次性切换到新路径。

Python 导入路径、API URL、数据库表、Celery task name、前端 REST/SSE 合约保持
不变，因此调用方不需要迁移。开发者唯一需要调整的是仓库内命令路径和 Compose
命令的 `-f infra/compose.yaml` 参数。

## 验证

1. 搜索旧路径和旧文件名，除迁移历史说明外不得存在运行时或命令引用。
2. 从 `apps/api` 新路径运行完整 pytest、Ruff 和 mypy。
3. 从 `apps/web` 新路径运行 Vitest 和生产构建。
4. 检查 `infra/compose.yaml` 的 build context、Dockerfile 和挂载路径。
5. 检查 README 中所有路径、命令和文档链接均存在。
6. 运行 `git diff --check` 并确认工作区干净。

当前机器没有 Docker 和 PostgreSQL，因此 Compose config、镜像构建、容器迁移、
PostgreSQL 集成测试及 live E2E 只能记录为环境未验证；不得使用 SQLite 代替，也
不得将静态检查描述为容器验证通过。

## 完成标准

- 目标目录结构完整，旧 Flask Demo 不再存在。
- 代码、测试、Compose、Docker 和文档没有失效路径。
- 词库内容与迁移前一致，说明与当前平台状态一致。
- 根 README 完整且不夸大已实现功能。
- 可在当前环境执行的后端与前端验证全部通过。
