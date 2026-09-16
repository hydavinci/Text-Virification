# Text Verification · 啄木鸟

中英文文档预检与人工审阅工具，将文件解析、文字检查、问题定位、修订和导出整合到同一个工作区。

[项目介绍](#项目介绍) · [项目使用方法](#项目使用方法) · [项目架构](#项目架构)

## 项目介绍

啄木鸟面向企业内网的文档预检场景，帮助使用者在发布、提交或归档前发现文字与表达问题。
项目支持仅使用本地规则，也可接入经批准的 OpenAI 兼容模型服务进行语义辅助。
检查结果供人工审阅，不替代专业判断、事实核验或合规审计。

### 核心能力

| 能力 | 说明 |
| --- | --- |
| 多格式输入 | 上传 DOCX、DOC、PDF、TXT、RTF、Markdown、CSV、PNG、JPG/JPEG，或直接粘贴文本 |
| 文字检查 | 检查错别字、英文拼写、异形词、全半角、标点、语法、表达、数字格式和术语一致性 |
| 自定义规则 | 配置术语、禁用词，以及扩展检查、个人信息与凭证、敏感表述、广告极限词等检查项 |
| OCR 识别 | 识别图片和扫描 PDF；支持中英文、英文、日文，日文仅识别、不纠错 |
| 在线审阅 | 问题高亮定位、接受/忽略/撤销、查找替换、正文编辑、亮暗主题和会话恢复 |
| 原版式预览 | Word、RTF、PDF 和图片使用统一分页视图，支持 SVG 页面展示、缩放和问题定位 |
| 结果导出 | 导出支持的文档原格式、HTML 检查报告，或图片/扫描件的可编辑 DOCX 重建稿 |

### 文档场景

六种场景各自加载独立规则包；设置界面从服务端获取实际规则清单、触发条件和例外。
下表为代表性能力，不表示覆盖该领域的所有问题。

| 场景 | 检查重点 |
| --- | --- |
| 通用文档 | 基础文字、标点、重复词及明确语法问题，不强制专业结构 |
| 学术论文 | 明确编号引文与参考文献、图表引用与题注、连续显式缩写定义冲突 |
| 商务文档 | 明确金额明细与合计、同项目日期倒置、行动清单的期限和负责人 |
| 法律文书 | 合同当事方简称、明确条款引用、相邻人民币大小写整数金额不一致 |
| 新闻稿 | 标题/导语中的明确数量矛盾、带绝对日期的相对日期矛盾、笼统数据来源 |
| 技术文档 | 参数定义与 JSON 示例命名差异、显式版本区间冲突、单流程步骤引用 |

专业规则只在证据和格式满足条件时执行，提示均需人工确认，不自动替换。
依赖完整文本的引文、清单、缺失目标等检查仅适用于完整 TXT/Markdown 或完整粘贴文本；
DOCX、PDF、OCR 等提取格式会跳过相应规则，并在结果中列出“未检查”项目。

### 使用边界

- **文件与保留期**：单文件默认最大 25 MiB，任务及上传文件默认保留 24 小时，可通过服务端配置调整。
- **预览限制**：最多 80 页、20 万字符、25 MiB 输出；不保证任意 Word 文件像素级还原。
- **提取范围**：Word 支持正文、嵌套表格及各节引用的页眉页脚；脚注、尾注、文本框、内容控件和修订容器不保证完整提取。
- **修订与导出**：图片和扫描件的原始像素不会被文字修订覆盖，DOCX 重建稿不保证完整还原原版式；无法可靠定位或安全回写时明确提示，不猜测位置。
- **结果可信度**：规则置信度是启发式分数，不是校准后的正确概率；没有提示不等于全文无误，部分完成或降级也不等于通过检查。
- **审阅保存**：浏览器支持工作区恢复，但不等同于完整的服务端审阅决策持久化；需要保留的结果应及时导出。

## 项目使用方法

### 选择运行方式

所有命令均从仓库根目录执行，除非代码块中另有 `cd`。

| 方式 | 适用场景 | 应用运行位置 | 页面地址 |
| --- | --- | --- | --- |
| 本地开发 | 调试前后端、修改规则 | API、Worker 和前端在本机；数据库、Redis、renderer 在 Docker | `http://localhost:5173` |
| 完整 Docker | 容器化运行 | 全部应用服务在 Docker | `http://localhost:8080` |

两种方式二选一，不要同时启动两套应用、检查 Worker 或 Beat。

### 本地启动（macOS）

**1. 准备环境与依赖**

| 工具 | 项目要求 |
| --- | --- |
| Python | 3.12，后端声明 `>=3.12,<3.13` |
| uv | 0.12.6，与 `apps/api/pyproject.toml` 的版本约束一致 |
| Node.js / npm | 使用与 CI 和前端镜像一致的 Node.js 22，通过 npm 安装依赖 |
| Docker Desktop | 已启动，且 `docker compose` 可用 |

```bash
uv sync --project apps/api --locked --extra dev
npm --prefix apps/web ci
test -f .env || cp .env.example .env
mkdir -p var/jobs
```

若需要图片或扫描 PDF 检查，改用包含 OCR 的安装命令：

```bash
uv sync --project apps/api --locked --extra dev --extra ocr
```

首次 OCR 可能下载模型，内网环境需提前准备对应语言的模型及缓存。
Word/RTF 预览由 Docker 中的 LibreOffice 转换，本机无需为预览单独安装 Office；
部分原生 `.doc` 导出转换仍依赖本机 `textutil` 或 `soffice`。

**2. 配置 `.env`**

保留已有配置和密钥，只调整本地运行所需字段：

| 配置项 | 本地开发设置 |
| --- | --- |
| `APP_ENV` | `development` |
| `DATABASE_URL` | 保留示例中的数据库用户名、密码和库名，将主机 `postgres` 改为 `127.0.0.1`，端口为 `5432` |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` |
| `CELERY_BROKER_URL` | 留空，使用 `REDIS_URL` |
| `STORAGE_ROOT` | 当前仓库下 `var/jobs` 的绝对路径 |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` |
| `PREVIEW_RENDERER_URL` | `http://127.0.0.1:8010` |
| `RECHECK_GRANT_SECRET` | 至少 32 个 UTF-8 字节的随机密钥，用于文件重新检查 |
| `LLM_API_KEY` | 留空使用本地规则；模型配置见[可选语义辅助](#可选语义辅助) |

下面的命令仅在密钥为空时生成并写入 `.env`，不输出密钥：

```bash
apps/api/.venv/bin/python - <<'PY'
import secrets
from dotenv import dotenv_values, set_key

secret = dotenv_values(".env").get("RECHECK_GRANT_SECRET")
if not secret:
    set_key(".env", "RECHECK_GRANT_SECRET", secrets.token_urlsafe(48))
elif len(secret.encode("utf-8")) < 32:
    raise SystemExit("Existing RECHECK_GRANT_SECRET is too short; replace it in .env.")
PY
```

`.env` 已被 Git 忽略，不要提交密钥或上传文件。

**3. 启动工作区**

```bash
./start-local.sh
```

脚本启动基础容器、执行数据库迁移，再启动本机 API、检查 Worker、维护 Worker、Beat 和前端；
已有渲染镜像会被复用，缺少时构建。等待依赖就绪后，打开 `http://localhost:5173`。

| 地址 | 用途 |
| --- | --- |
| `http://127.0.0.1:8000/docs` | API 文档 |
| `http://127.0.0.1:8000/api/v1/health` | API 存活检查 |
| `http://127.0.0.1:8000/api/v1/ready` | 数据库、Redis、消息代理、兼容检查 Worker 和渲染服务就绪状态 |
| `http://127.0.0.1:8010` | 仅供本机 API 使用的渲染网关，不是前端页面 |

保留启动终端，按 `Ctrl+C` 停止本次启动的应用进程；基础容器继续运行，数据不会删除。
日志位于 `var/local/`，每次启动覆盖，可用 `tail -f var/local/api.log var/local/worker.log` 查看。

### 完整 Docker 启动

准备 Docker 和 Compose，创建配置文件：

```bash
test -f .env || cp .env.example .env
```

编辑 `.env`，将 `RECHECK_GRANT_SECRET` 设置为至少 32 个 UTF-8 字节的随机密钥。
生产或预发布部署应设置对应的 `APP_ENV`，这些环境会拒绝空密钥或过短密钥。
不使用模型辅助时保持 `LLM_API_KEY` 为空，然后启动：

```bash
docker compose --env-file .env -f infra/compose.yaml up --build -d
```

打开 `http://localhost:8080`。Compose 自动使用容器内的数据库、Redis 和存储地址，
无需把本地开发配置中的地址手动改回容器服务名；若配置过 `CELERY_BROKER_URL`，请确认容器可以访问。
基础镜像源可通过 `.env.example` 中的 `PYTHON_IMAGE`、`NODE_IMAGE`、`NGINX_IMAGE` 调整。

```bash
# 查看日志
docker compose --env-file .env -f infra/compose.yaml logs -f api worker renderer

# 停止完整 Docker 应用
docker compose --env-file .env -f infra/compose.yaml down

# 停止本地开发留下的基础容器
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.local-services.yaml down
```

**不要给 `down` 添加 `-v` 或 `--volumes`，否则会删除数据库和任务数据。**

### 检查与审阅流程

1. **导入内容**：选择文件或粘贴文本；选中文件不会自动上传检查。
2. **设置范围**：选择文档场景，在“检查设置”中配置检查项、术语和禁用词，再点击“开始检查”。默认使用通用文档、中英文 OCR，开启个人信息与凭证及敏感表述检查；扩展检查、广告极限词和语义发现默认关闭。
3. **审阅问题**：在双栏工作区查看正文和问题列表，点击问题定位原文，再接受、忽略或撤销。可拖动分隔线调整栏宽，手机端切换文档与问题面板。
4. **修改与重查**：使用正文编辑或查找替换修改内容，再点击“重新检查”。修改设置也需重查才生效；重新检查使用当前修订文字，不重新执行 OCR，更换 OCR 语言需重新上传。
5. **导出结果**：从顶部导出菜单下载检查报告或修改文件。“保留修订”默认关闭，需要时手动勾选；专业或描述性建议不一定允许直接替换。
6. **新建检查**：先导出需要保留的结果，再点击左上角“啄木鸟”返回新建页，当前工作区会被清空。

`Ctrl/Cmd+F` 展开正文查找替换，`Enter` / `Shift+Enter` 定位下一项 / 上一项，`Escape` 收起。
原版式支持适合宽度及 25%–200% 缩放，100% 以适合当前容器宽度为基准，并非打印尺寸的 1:1 比例。
“部分文字无法精确定位”表示文字与页面坐标未完全匹配，不等于文件损坏；应结合原文和上下文审阅。

取得任务编号后，同一标签页刷新可重新连接文件任务，不会重复上传。
上传尚未取得编号或直接文本请求不能自动续接；停止等待不等于取消后台任务。
任务过期后需重新上传，浏览器恢复记录不会延长服务端保留期。

### 可选语义辅助

| 模式 | 启用方式 | 范围 |
| --- | --- | --- |
| 本地规则 | `LLM_API_KEY` 留空 | 不调用模型服务；OCR 模型仍需提前准备 |
| 语义复核 | 配置获准的 `LLM_API_BASE`、`LLM_API_KEY`、`LLM_MODEL` | 复核本地规则命中项，发送命中位置附近的局部文本 |
| 语义发现 | 上述配置，加上 `LLM_SEMANTIC_DISCOVERY_ALLOWED=1`，并在界面开启“语义发现” | 从抽样片段发现新问题，会发送局部上下文及相关术语，包括未命中规则的文字 |

语义发现默认最多选取 6 个片段，每段正文 800 字符、上下文半径 100 字符，最多保留 24 个新候选；
预算由 `.env.example` 中的 `LLM_SEMANTIC_*` 设置控制。抽样不代表全文覆盖，建议不自动改写正文。
模型不可用时保留本地检查结果并提示降级，不将调用失败视为“没有问题”。

**模型辅助会增加费用和等待时间；不要将保密文档发送给未经批准的供应商。**
修改环境配置后需重启 API 和相关 Worker，不能只刷新页面或只重启 API。

### 维护与常见问题

本地前端、API 和 renderer 支持热重载，**检查 Worker 不会自动重载规则代码**。
修改检查逻辑或环境配置后，停止并重新运行 `./start-local.sh`。
修改后端依赖或 Dockerfile 后，还需重建渲染服务：

```bash
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.local-services.yaml \
  up -d --build --wait renderer renderer-gateway
```

完整 Docker 模式不挂载本地源码，修改后需重新构建并部署对应服务。
依赖安装使用 `uv sync --locked` 和 `npm ci`；有意更新后端依赖时同步修改 `pyproject.toml`，
执行 `uv lock --project apps/api` 并提交锁文件。

| 现象 | 排查方式 |
| --- | --- |
| uv 版本不匹配 | 使用 0.12.6，不删除版本约束或锁文件来绕过 |
| 启动端口冲突 | 检查 8000/5173 端口及另一套 Docker 应用，先停止冲突服务 |
| 提示已有启动器 | 若异常退出留下 `var/local/run.lock`，确认旧进程全部停止后再执行 `rmdir var/local/run.lock` |
| API 存活但任务不可用 | 查看 `/api/v1/ready`；503 响应会列出未就绪依赖，再查看 `var/local/` 对应服务日志 |
| 文本可检查，文件任务未完成 | 检查 Worker 日志及其数据库、存储和检查配置是否与 API 一致 |
| OCR 不可用 | 确认已安装 `ocr` 可选依赖及对应语言模型，安装后重启应用进程 |
| 原版式预览不可用 | 检查 `renderer`、本地 `renderer-gateway` 的状态、日志及 `PREVIEW_RENDERER_URL` |

## 项目架构

### 技术栈与运行结构

| 层次 | 主要技术与职责 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite；检查设置、正文/版式预览、问题审阅、会话恢复 |
| API | Python 3.12、FastAPI、Pydantic；输入校验、同步检查、任务与产物接口 |
| 后台任务 | Celery、Redis；异步文件检查、进度事件、任务维护 |
| 数据与存储 | PostgreSQL、SQLAlchemy、Alembic；任务、结果、参数快照与迁移，文件按任务目录隔离保存 |
| 文档处理 | python-docx、PDF 解析组件、RapidOCR；统一提取文本、结构和坐标 |
| 渲染服务 | LibreOffice、SVG；文档转换、分页图像及定位坐标 |
| 交付 | Docker Compose、nginx、GitHub Actions；容器编排、代理和持续集成 |

```text
浏览器 / Vue 工作区
    |
    | /api（开发：Vite 代理；Docker：nginx 代理）
    v
FastAPI
    +-- 同步文本检查 ------------------------+
    +-- PostgreSQL：任务、事件、结果、参数   |
    +-- 任务文件存储：源文件与导出产物       |
    +-- Redis / Celery                      |
    |     +-- 检查 Worker ------------------+--> 统一检查流水线
    |     +-- 维护 Worker：过期清理、租约救援
    |     +-- Beat：定时发布维护任务
    +-- renderer：分页预览与坐标
```

检查 Worker 使用 `text-verification-worker` 入口，角色为 `verification`，消费 `celery,verification-v2`；
维护角色为 `maintenance`，只消费 `maintenance-v2`，避免维护任务占用检查并发。
同一环境仅运行一个 Beat；旧版 Worker 只能用 `--queues=celery` 排空遗留任务。
renderer 位于内部网络，使用只读根文件系统、受限临时目录和单转换并发，不读取 `.env`、数据库或任务存储。
本地 API 通过仅绑定 `127.0.0.1:8010` 的网关访问它，完整 Docker 模式由 API 直接访问。

### 核心处理流程

```text
文本 / 上传文件
    → 解析器选择与文本提取（按需 OCR）
    → DocumentModel 统一文档模型
    → 基础检查 + 所选场景规则 + 用户术语/禁用词
    → 可选语义复核 / 语义发现
    → VerificationResult（问题、统计、来源、降级原因）
    → 前端人工审阅 → 修订预览 / 导出
```

同步文本与异步文件共用 `VerificationPipeline`，由 `application/factory.py` 装配解析器、检查器和模型复核器。
检查设置通过 `VerificationOptions` 快照进入 `CheckContext`，不通过全局变量影响其他任务。
问题位置采用统一文档文本的 Unicode 码点偏移，保留规则来源和版本。

| 入口 | 作用 |
| --- | --- |
| `POST /api/v1/analyze` | 同步文本检查 |
| `POST /api/v1/jobs` | 创建异步文件任务 |
| `GET /api/v1/jobs/{job_id}/events` | 通过 SSE 获取任务进度 |
| `GET /api/v1/jobs/{job_id}/result` | 获取检查结果 |
| `POST /api/v1/jobs/{job_id}/preview/layout` | 根据源版本和当前修订文本生成分页预览 |
| `GET /api/v1/scenarios` | 获取运行中场景规则清单 |

预览先校验源文件身份，再在临时副本上应用修订并渲染，不覆盖原文件。
每个 API 进程的预览缓存最多 4 份、合计 32 MiB，有效期 60 秒；命中缓存也重新校验源文件。
浏览器将文档快照、界面偏好和待完成任务恢复记录分开保存，避免切换视图时重复序列化全文。

### 代码组织与扩展入口

前端源码位于 `apps/web/src/`，后端源码位于 `apps/api/src/text_verification/`：

| 模块 | 职责 |
| --- | --- |
| 前端 `components/workspace/`、`views/WorkspaceView.vue` | 工作区组件及交互编排 |
| 前端 `api/`、`composables/`、`types/` | 请求转换、审阅状态、会话恢复及类型定义 |
| 后端 `api/`、`domain/` | API 路由、领域模型、检查参数及接口约定 |
| 后端 `application/` | 检查流水线、任务重查、修订预览等业务流程 |
| 后端 `parsers/`、`document_processing/` | 文档解析、OCR 及版式处理 |
| 后端 `checkers/`、`compatibility/`、`scenarios/` | 基础检查、兼容实现、独立场景规则包与语义策略 |
| 后端 `exporters/`、`infrastructure/`、`workers/` | 导出、数据与文件存储、队列任务 |
| `apps/api/alembic/`、`infra/` | 数据库迁移、Docker 编排与渲染网关 |
| `apps/web/tests/`、`apps/api/tests/` | 前后端单元、集成、浏览器及质量评估测试 |

**扩展规则**：当前工作区术语和禁用词可直接在界面配置；场景规则在后端 `scenarios/` 定义。
内置敏感词和广告极限词实际读取后端 `resources/dictionaries/`，不是仓库根目录的同名目录。
新增检查开关需同步前端设置、请求转换、后端参数模型、任务上下文及执行链，并覆盖重查与旧会话恢复；
较大的独立模块可实现 `domain/ports.py` 的 `Checker` 接口，通过注册表接入。

### 开发验证与交付

```bash
# 前端单元测试与类型检查 / 构建
npm --prefix apps/web test
npm --prefix apps/web run build

# 后端静态检查
(
  cd apps/api
  .venv/bin/ruff check src tests scripts
  .venv/bin/mypy src
)

# 本地规则质量评估
apps/api/.venv/bin/python -m text_verification.evaluation \
  apps/api/tests/quality/detection_cases.json --split holdout
apps/api/.venv/bin/python -m pytest apps/api/tests/quality -q

# 浏览器流程；首次运行需安装 Chromium
(
  cd apps/web
  npx playwright install chromium
  npm run test:e2e
)
```

Playwright 自动构建并启动 `http://127.0.0.1:4173` 的预览服务，运行前确保端口空闲。
质量评估只使用本地规则，输出精准率、召回率、建议正确率及位置有效率等指标；
内置小型构造集不代表生产文档效果，也不覆盖 Word 回写和 OCR。
数据库集成测试需要独立的 `TEST_DATABASE_URL` 和真实 PostgreSQL，不要指向业务数据库。

CI 在 `.github/workflows/ci.yaml` 中分为前端、后端及真实服务流程，分别覆盖静态检查、测试、
生产镜像构建，以及上传、OCR 和渲染链路；缺少依赖而跳过的测试不算验证通过。
后端镜像默认构建 `runtime`，包含 OCR、字体和 LibreOffice，但不包含测试与开发工具；
需要开发工具时使用 `development` 构建目标。

更多背景见[平台架构设计](docs/architecture/document-verification-platform.md)和
[仓库组织说明](docs/architecture/repository-layout-and-documentation.md)。
`docs/development/`、`docs/superpowers/` 保留历史设计与实施记录，具体运行行为以当前代码为准。
