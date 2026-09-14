# Text Verification

面向企业内网的中英文文档预检平台，目标是统一提供错别字检查、格式检查、行业敏感词检测与替换、文件上传、在线审阅和结果导出。

> 当前状态：可用的文档预检版本。已经实现七种文档格式、PNG/JPEG 图片和直接文本检查、六层规则引擎、
> 自定义术语与禁用词、合规扫描、三栏在线审阅、原版式矢量预览、查找替换、修订导出、HTML 报告和可选的大模型
> 语义复核。文件检查使用 PostgreSQL、Redis/Celery 与 SSE 任务流水线，保留 24 小时过期清理。

## 已实现与未实现

### 已实现

- DOCX、DOC、PDF、TXT、RTF、Markdown、CSV、PNG、JPG/JPEG 文件上传，以及直接粘贴文本。
- 图片和扫描 PDF 可选择中英文（默认）、英文或日文 OCR；日文仅提供文字识别，不包含日文纠错规则。OCR 语言按任务保存，不会改变其他任务的识别配置。
- 图片 OCR 保留段落、标题、表格和非文字图像区域；有格线的图片表格可保留空单元格，字号按图片 DPI 换算。
- FastAPI API、PostgreSQL 任务与事件持久化。
- Redis + Celery 异步任务调度。
- SSE 进度事件推送。
- 每个任务使用独立 UUID 目录存储上传文件。
- 24 小时过期清理。
- Vue 3 响应式三栏审阅界面、亮/暗主题和会话恢复；上传页、审阅页和设置面板统一控件、字号与间距。
- 中文错别字、英文拼写、异形词、全半角、标点、语法、表达、数字格式和术语一致性检查。
- “扩展检查”默认关闭，可按需启用中英文间距、多余空格/空行和长句提示；仍遵守所选场景过滤，长句只提示人工调整，不自动替换。
- 身份证、手机号、邮箱、银行卡、密钥、敏感表述及广告法极限词检查。
- 六种文档场景、自定义术语表、禁用词库及批量导入。
- 问题接受、忽略、撤销、批量操作、正文编辑和查找替换；可切换显示问题标记。
- 左侧查找替换面板中的“撤销修改”可逐步回退单次替换、全部替换和已保存的原文编辑，全部替换作为一步撤销。撤销记录随本地会话保存，刷新后仍可使用；重新检查或更换文档会开始新的记录。旧会话仅保留正文历史时，撤销后仍会提示重新检查。
- 接受建议后正文即时更新，撤销恢复原文；查找高亮当前修订中的匹配项，并支持上下项滚动定位。
- 正文仅使用文字高亮，不插入占位标记；点击高亮可联动问题列表，重叠问题可重复点击切换。
- 文件名只在顶部显示。Word（DOCX/DOC）、RTF、PDF 和图片在同一个分页审阅界面中展示图片、表格、页眉页脚及问题标记，无需切换原文与文字模式。接受、撤销或保存编辑后更新版式；纯文本使用段落视图。关闭“显示问题标记”只隐藏高亮，不改变修订。
- 分页预览提供“适合宽度”和 25%、50%、75%、100%、125%、150%、200% 缩放；缩小时页面居中，问题标记随页面同步缩放。
- DOCX/DOC/PDF/TXT/RTF/Markdown/CSV 原格式导出及 HTML 检查报告。
- 图片以及扫描/混合 PDF 可重建为可编辑 DOCX，支持审阅修订和重新检查后的导出。图片不提供修改后的 PNG/JPEG 下载，Word 重建也不承诺像素级还原原版式。
- DOCX 修订痕迹、PDF 高亮批注和文本格式修订标记。
- 可选的 OpenAI 兼容语义复核；未配置密钥时自动使用纯本地规则。

### 后续演进

- 共享词库数据库管理、版本及回滚。
- 基于 `DocumentModel` 精确块定位的审阅决策持久化。

## 技术架构与请求数据流

```text
Browser → nginx → FastAPI → PostgreSQL
                     ├── Redis/Celery → Job Storage
                     └── renderer → LibreOffice / SVG 分页预览
```

- `apps/web` 提供 Vue 3 审阅前端和 nginx 静态站点/反向代理。
- `apps/api` 提供 FastAPI API、Celery Worker、Alembic 迁移和后端测试。
- PostgreSQL 是任务与事件的持久化来源；Redis 负责队列；Worker 执行统一文档解析、OCR 与规则检查流水线。
- 浏览器文件上传通过异步任务接口检查、接收 SSE 进度并导出；文本检查保留同步预检接口。PNG/JPEG 只在异步任务接口支持，同步兼容接口不接收图片。
- 分页预览由 API 校验源文件身份后调用隔离的 Docker 渲染服务；原生开发通过本机 `renderer-gateway` 连接该服务，浏览器不直接访问渲染端口。

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
if (!(Test-Path .env)) { Copy-Item .env.example .env }
docker compose --env-file .env -f infra/compose.yaml up --build -d
docker compose --env-file .env -f infra/compose.yaml exec api pytest
docker compose --env-file .env -f infra/compose.yaml logs -f api worker maintenance-worker
docker compose --env-file .env -f infra/compose.yaml down
```

macOS/Linux 在仓库根目录执行：

```bash
test -f .env || cp .env.example .env
docker compose --env-file .env -f infra/compose.yaml up --build -d
```

Compose 为所有后端容器明确使用内置的 `postgres`、`redis` 和
`/var/lib/text-verification/jobs`，不会把原生开发 `.env` 中的 `localhost` 或
macOS 存储路径带入容器。其他设置（包括密钥）仍从 `.env` 读取；原生开发配置无需覆盖。
`CELERY_BROKER_URL` 留空时使用内置 Redis，非空时仍使用显式配置的 broker。

如果构建在 Docker Hub 基础镜像元数据阶段超时，可在 `.env` 中添加以下构建变量，
改用 Amazon ECR Public 上的 Docker 官方镜像；这不是任意第三方镜像站，也不会上传项目代码：

```dotenv
PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.12-slim
NODE_IMAGE=public.ecr.aws/docker/library/node:22-slim
NGINX_IMAGE=public.ecr.aws/docker/library/nginx:1.27-alpine
```

然后重新执行上述命令，保留 `--env-file .env`，确保根目录构建变量参与 Compose 插值；
服务的 `env_file` 仅负责容器运行时环境，不能代替该参数。
该方式仍需能访问 ECR Public 和构建所需的软件包源，
不代表离线构建。PostgreSQL/Redis 默认仍从 Docker Hub 拉取；已有本地镜像时可以复用。
删除这三个变量即可恢复 Docker Hub 默认来源。仅使用旧应用镜像启动不会包含当前代码修改。
停止项目使用 `docker compose --env-file .env -f infra/compose.yaml down`，
不要添加 `-v`，以保留数据库。

- 应用地址：`http://localhost:8080`
- 健康检查：`http://localhost:8080/api/v1/health`
- `APP_ENV` 设置为 `production`、`staging` 或 `deployed` 时，
  `RECHECK_GRANT_SECRET` 必须是至少 32 个 UTF-8 字节的部署密钥；API 与
  Worker 会在启动时拒绝空值或短值。开发/测试环境可显式使用
  `APP_ENV=development` 或 `APP_ENV=test`。
- `RECHECK_GRANT_TTL_SECONDS` 控制重新检查授权的有效期，默认 900 秒。
- `migrate` 服务只负责执行 Alembic，成功后退出；`maintenance-worker` 独占清理和租约救援队列。

### Worker 滚动升级队列

- 旧版 Worker 命令：`celery -A text_verification.workers.celery_app:celery_app worker --queues=celery`
- 新版 Worker 命令：设置 `TEXT_VERIFICATION_WORKER_ROLE=verification`、`TEXT_VERIFICATION_WORKER_QUEUES=celery,verification-v2`、`TEXT_VERIFICATION_WORKER_CONCURRENCY=2` 后运行 `text-verification-worker`。
- 维护 Worker 命令：设置 `TEXT_VERIFICATION_WORKER_ROLE=maintenance`、`TEXT_VERIFICATION_WORKER_QUEUES=maintenance-v2`、`TEXT_VERIFICATION_WORKER_CONCURRENCY=1` 后运行 `text-verification-worker`。
- 新 API 创建的文件异步任务（包括图片）、任务重试和租约救援重新投递统一进入 `verification-v2`。
- 新版 Worker 同时消费 `celery` 与 `verification-v2`，因此可排空升级前已发布的旧任务；旧版 Worker 只消费 `celery`，不会取得新版任务。
- Beat 将清理与租约救援任务发布到 `maintenance-v2`，由单并发维护 Worker 处理，避免文档队列饥饿或旧 Worker 错误重投递。
- 滚动顺序：先启动新版普通 Worker 和维护 Worker，再切换到新版 Beat，随后部署新版 API；确认旧 `celery` 队列排空后再停止旧版 Worker。滚动期间只保留一个 Beat 实例。
- 新版 Worker 的角色、队列、并发数和预取数在启动前强制校验。缺失角色、未知角色、错误队列、维护 Worker 并发不为 1、autoscale 或直接运行含糊的 `celery ... worker` 命令都会在消费任务前退出。Beat 不执行 Worker 角色校验。
- Redis broker 的“发布确认”表示 Redis 已接受入队命令，并非 AMQP publisher confirm。发布重试保持启用；如设置 `CELERY_BROKER_URL=amqp://...`，Celery 才启用 `confirm_publish`。

## 本地后端与前端开发、测试、构建

### 一条命令启动（macOS）

完成下方的首次依赖安装和根目录 `.env` 配置、打开 Docker Desktop 后，在仓库根目录运行：

```bash
./start-local.sh
```

脚本自动启动 PostgreSQL/Redis 和 Docker 文档渲染服务（缺少镜像时构建）、执行数据库迁移，并在同一个终端管理 API、
检查 Worker、维护 Worker、Beat 和前端。打开 `http://localhost:5173` 即可使用。
这是普通本地开发启动（API 自动重载），不是 VS Code 断点附加模式；
修改 Worker 代码后需要停止并重新运行脚本。

保留这个终端，按 `Ctrl+C` 会停止本次启动的应用进程及其子进程，
但保留 PostgreSQL/Redis、渲染服务容器和数据库数据。任何应用进程退出时，脚本会报错并停止其余应用进程。
各服务日志在 `var/local/`，每次启动覆盖；例如另开终端运行
`tail -f var/local/api.log var/local/worker.log`。

脚本不安装依赖、不覆盖 `.env`、不自动停止其他已运行的服务。
如果端口 8000/5173 已被占用，或本项目 Docker 应用服务仍在运行，会提示先停止冲突服务。
不要同时手动启动另一套 Worker 或 Beat。异常强制退出留下 `var/local/run.lock` 时，
确认之前的应用进程已停止后，再运行 `rmdir var/local/run.lock`。

### macOS 原生启动

需要 Python 3.12、npm 和 Docker Desktop。应用进程在 macOS 原生运行，Docker
运行 PostgreSQL、Redis 和文档渲染服务；本机无需单独安装 LibreOffice：

```bash
python3.12 -m venv apps/api/.venv
apps/api/.venv/bin/python -m pip install -e "apps/api[dev]"
npm --prefix apps/web ci
mkdir -p var/jobs
```

`infra/compose.local-services.yaml` 将 PostgreSQL、Redis 和渲染网关分别映射到
`127.0.0.1:5432`、`127.0.0.1:6379` 和 `127.0.0.1:8010`，只供本机访问。

先在仓库根目录创建 `.env`，再启动服务。该文件已被 Git 忽略；如果文件已存在，不要
覆盖，应确认相关配置使用以下本机地址和存储路径（将示例绝对路径中的用户名和仓库
位置替换为实际值）：

```dotenv
APP_ENV=development
DATABASE_URL=postgresql+psycopg://text_verification:text_verification@localhost:5432/text_verification
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=
STORAGE_ROOT=/Users/<username>/Work/Text-Virification/var/jobs
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
PREVIEW_RENDERER_URL=http://127.0.0.1:8010
LLM_API_KEY=
```

本地文件重新检查也需要 `RECHECK_GRANT_SECRET`，缺少或不足 32 个 UTF-8 字节时，
接口会返回 503。以下命令仅在密钥为空时生成随机密钥并写入已忽略的 `.env`，
不会输出密钥或覆盖已有有效值：

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

修改该配置后需重启 API；仅刷新浏览器不会重新加载后端配置。不要将密钥提交到 Git。

完整 Docker Compose 启动会覆盖容器内的数据库、Redis 和存储地址；
原生进程仍读取根目录 `.env`，应保留上述本机地址，不能使用容器服务名。

从仓库根目录启动基础服务并执行迁移，以读取同一份根目录 `.env`。
迁移脚本路径相对于 `alembic.ini`，不依赖当前工作目录：

```bash
docker compose -f infra/compose.yaml -f infra/compose.local-services.yaml \
  up -d --wait postgres redis
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.local-services.yaml \
  up -d --build --wait renderer renderer-gateway
apps/api/.venv/bin/alembic -c apps/api/alembic.ini upgrade head
```

随后从仓库根目录分别启动 API、两个 Worker 和唯一的 Beat 实例，以便它们读取根目录
`.env`：

```bash
apps/api/.venv/bin/uvicorn text_verification.main:app \
  --reload --host 127.0.0.1 --port 8000

TEXT_VERIFICATION_WORKER_ROLE=verification \
TEXT_VERIFICATION_WORKER_QUEUES=celery,verification-v2 \
TEXT_VERIFICATION_WORKER_CONCURRENCY=2 \
  apps/api/.venv/bin/text-verification-worker

TEXT_VERIFICATION_WORKER_ROLE=maintenance \
TEXT_VERIFICATION_WORKER_QUEUES=maintenance-v2 \
TEXT_VERIFICATION_WORKER_CONCURRENCY=1 \
  apps/api/.venv/bin/text-verification-worker

apps/api/.venv/bin/celery \
  -A text_verification.workers.celery_app:celery_app \
  beat --loglevel=INFO --schedule=var/celerybeat-schedule

npm --prefix apps/web run dev
```

浏览器打开 `http://localhost:5173`。

### 审阅界面与常用操作

选中文件后可先调整检查设置，再点击“开始检查”；选文件不会自动提交。
也可以切换到“粘贴文本”直接检查。上传页、审阅页和设置面板使用统一的控件与排版，
支持亮色和深色主题。正文使用独立的纸张画布，选中的问题卡片使用四边等宽的强调色边框。

| 区域 | 功能 |
| --- | --- |
| 左侧：查找替换 | 查找当前修订、替换当前或全部匹配、撤销文字修改 |
| 中间：正文 | 查看原版式或文本段落、缩放分页预览、显示问题标记、编辑正文 |
| 右侧：问题列表 / 检查摘要 | 筛选与定位问题、选择建议、接受、忽略及撤销 |
| 顶部操作区 | 检查设置、重新检查、导出；帮助、隐私说明及主题切换 |

宽屏及较窄的桌面、平板屏幕保持“查找替换 / 正文 / 问题列表”三栏，正文占最大宽度。
手机端提供“文档 / 问题 / 查找替换”三个面板入口；顶部辅助按钮保持成组排列，
导出受限等状态说明单独换行，不挤出检查设置入口。

“检查设置”在上传页保留卡片内的原入口，在审阅页显示于右上角，每页仅显示一个入口，
均可随时打开。修改设置不会清空当前文档、
检查结果或审阅记录；在审阅页修改后，关闭面板并点击“重新检查”应用新设置。
检查进行中允许查看设置和切换分类，但暂时禁用修改。重新检查仅检查当前修订文字，
不重新执行 OCR；调整 OCR 语言后需重新上传文件。
导出菜单的“保留修订”在打开、恢复或新建工作区时默认关闭，不沿用旧会话的勾选状态；需要带修订痕迹导出时，可手动勾选。
Ctrl/Cmd+F 聚焦查找框；手机端会先切换到查找替换面板，输入时不自动切走，可通过“文档”
切回正文查看匹配。查找框中 Enter 定位下一项，Shift+Enter 定位上一项。
问题和匹配定位仅滚动各自的阅读区域，已可见的内容保持位置。

需要更换文件时，先导出需要保留的结果，再点击左上角“啄木鸟”返回新建检查页面；
该操作会清空当前工作区。

### 可选组件与运行约束

同一环境只能运行一个 Beat，避免重复发布定时任务。原版式预览中的 Word/RTF 转换
由 Docker 内的 LibreOffice 处理。现有 `.doc` 原格式导出等原生后端转换仍依赖本机
`textutil` 或 `soffice`；这与预览服务独立。OCR 依赖也是可选项，可用
`apps/api/.venv/bin/python -m pip install -e "apps/api[dev,ocr]"` 安装。
缺少这些可选组件时，相应转换、图片或扫描 PDF OCR 不可用。RapidOCR 还需要对应语言的模型；
首次使用可能下载模型，内网部署应提前准备模型及缓存。模型或识别依赖不可用时会明确报错，
不会返回伪造的识别结果。上传图片上限 25 MiB，并在解码前后校验格式、尺寸和资源预算。
`LLM_API_KEY` 留空时使用纯本地规则，不调用大模型服务。

### 统一版式审阅与保留边界

- 上传 Word（DOCX/DOC）、RTF、PDF 或图片后，在同一文档视图中审阅分页版式与问题标记。
  点击右侧问题或查找结果，会定位到可映射的页面区域，不再切换到纯文本视图。
  TXT/Markdown/CSV 和直接粘贴文本继续使用段落视图。
- 接受、撤销建议及保存正文编辑后，基于**经过身份校验的原文件副本**应用当前修订并重新渲染；
  更新过程中隐藏旧位置标记，避免把过期坐标套用到新文字。连续修改按顺序处理，仅展示最新结果。
  重新检查和恢复会话后继续使用保留的任务身份及源版本；预览不写入修订历史，也不改变导出授权。
- Office 转换及分页渲染在 Docker 内完成，正文使用字体轮廓化的 SVG 矢量页面，
  不再将整页文字转换为固定分辨率 PNG 后拉伸，缩放和高分屏显示不受该位图分辨率限制。
  矢量页面通过图片元素显示，不插入内联 SVG；原文图片仍受其自身分辨率限制。
  浏览器同时显示可点击的定位标记，
  不依赖浏览器自带 PDF 工具栏，也不需要安装 Office。图片、表格、页眉页脚随文档渲染，
  但缺失字体和特殊对象可能导致显示差异，
  **不承诺任意 Word 文档像素级一致，也不保证未被文字解析器提取的对象内容参与检查**。
- 默认使用“适合宽度”，可切换到 25%、50%、75%、100%、125%、150% 或 200%。
  当前百分比以适合宽度为基准：100% 与当前容器的适合宽度等效，并非打印尺寸的 1:1 比例。
  缩小后页面居中；放大后可在文档区域滚动，问题定位同时处理横向和纵向滚动。
  缩放只影响预览，不改变原文内容或导出文件。
- DOCX 原格式导出在源文件基础上修改文字。无法安全修改的图文混排内容会报错；
  PDF 中超出原文字区域的修改也可能无法安全应用。图片、扫描件的原始图像不被文字修订覆盖，
  此时页面明确提示修订仍在右侧，导出可编辑 DOCX 重建稿仍不承诺原版式完整还原。
- 定位使用当前版式的文字坐标及完整文本对齐，不简单搜索问题词的第一次出现。
  判断重复歧义时会比较原文与渲染文本中的全部出现次数；标题在正文中再次出现等正常重复
  不会仅因超出独立段落的计数而被误判为额外页眉。
  真正存在额外重复、缺失或无法可靠对齐的文字仍会提示无法精确定位，不猜测位置。
  “部分文字无法精确定位”表示预览坐标未完全匹配，不代表文件损坏或检查失败，
  也不表示所有问题都无法定位；可继续结合右侧原文和上下文审阅。
- 预览遵守任务过期状态与源文件哈希校验；转换失败、任务过期或格式不支持时明确报错，
  不静默显示纯文本替代。失败时保留修订并提供重试，旧页面会明确标为上次成功的预览。
  文件上限为 25 MiB，版式预览限制 80 页、20 万字符和 25 MiB 输出；内部 JSON 传输上限为
  64 MiB（含 Base64 源文件），单次 Office 转换限时 45 秒，完整渲染请求限时 120 秒。
- `renderer` 使用现有后端镜像内的 LibreOffice/中文字体，不读取 `.env`、数据库或任务存储；
  使用只读根文件系统、受限临时目录、单转换并发和无外网的内部网络。
  启用容器 init 回收 Office 遗留的辅助子进程，避免连续转换耗尽进程配额。
  原生开发通过仅绑定 `127.0.0.1:8010` 的 `renderer-gateway` 访问，
  `PREVIEW_RENDERER_URL` 默认为 `http://127.0.0.1:8010`。完整 Docker 部署由 API
  直接访问 `http://renderer:8000`，不向浏览器暴露渲染端口。
- 本地调试覆盖配置只读挂载 `apps/api/src/text_verification` 并启用渲染服务热重载；
  `start-local.sh` 复用已安装依赖的镜像，不因代码修改重复下载依赖。首次缺少镜像时构建；
  修改后端依赖或 Dockerfile 后需手动以 `--build` 重建 renderer。正式部署不挂载源代码。

渲染日志和本地容器停止命令（不加 `-v`，保留数据）：

```bash
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.local-services.yaml \
  logs -f renderer renderer-gateway
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.local-services.yaml down
```

### Backend

#### VS Code 本地断点调试

仓库的 `.vscode/launch.json` 提供 `Local API (attach)`、
`Local Worker (attach)` 和组合入口 `Local API + Worker`。
先按上述步骤启动本地数据库和前端；以下调试命令替代普通 API 和检查 Worker 命令，
不要同时启动两套进程。维护 Worker 和 Beat 仍按上面的方式运行。

首次使用时，在现有虚拟环境中安装调试器：

```bash
uv pip install --python apps/api/.venv/bin/python "debugpy>=1.8,<2"
```

从仓库根目录在两个终端分别启动：

```bash
apps/api/.venv/bin/python -Xfrozen_modules=off -m debugpy \
  --listen 127.0.0.1:5678 \
  -m uvicorn text_verification.main:app \
  --reload --host 127.0.0.1 --port 8000
```

```bash
TEXT_VERIFICATION_WORKER_ROLE=verification \
TEXT_VERIFICATION_WORKER_QUEUES=celery,verification-v2 \
TEXT_VERIFICATION_WORKER_CONCURRENCY=2 \
apps/api/.venv/bin/python -Xfrozen_modules=off -m debugpy \
  --listen 127.0.0.1:5679 \
  -m celery -A text_verification.workers.celery_app:celery_app worker \
  --loglevel=INFO --queues=celery,verification-v2 --concurrency=2 \
  --prefetch-multiplier=1 --hostname=verification@%h --pool=solo
```

在 VS Code 中打开仓库根目录，安装 Python Debugger 扩展后选择对应入口并按 F5。
直接文本检查在 API 中执行，文件解析和检查在 Worker 中执行。
Worker 使用仅用于本地调试的 `solo` 池逐个执行任务，保留项目要求的角色、队列和并发参数；
断点暂停时文件任务会等待，修改 Worker 代码后需要重启该进程。
调试端口仅监听本机，未附加调试器时应用也可以正常使用。

#### 后端命令

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
- `GET /api/v1/jobs/{job_id}/result`
- `GET /api/v1/jobs/{job_id}/preview`
- `POST /api/v1/jobs/{job_id}/preview/layout`
- `POST /api/v1/jobs/{job_id}/exports`
- `GET /api/v1/jobs/{job_id}/exports/{artifact_id}`
- `GET /api/v1/health`
- `POST /api/v1/analyze`
- `POST /api/v1/export`
- `POST /api/v1/export-original`
- `GET /api/v1/scenarios`
- `GET /api/v1/formats`

`POST /api/v1/jobs` 使用 multipart 上传，并接受与同步检查相同的
`scenario`、`enable_security`、`enable_sensitive`、`enable_ad_extreme`、
`custom_glossary`（JSON 数组）和 `banned_words`（JSON 数组）字段。服务端将经过
边界和大小校验的不可变配置快照随任务持久化；任务响应、SSE、日志和错误不会回显
自定义术语或禁用词列表。

`POST /api/v1/jobs/{job_id}/preview/layout` 接收包含 `source_version` 和当前修订全文
`text` 的 JSON，返回分页图像及文字定位坐标。它不会保存审阅决策或覆盖原文件，
仍受任务生命周期、源版本校验和预览资源限制约束。

## 文件限制、保留与安全边界

- 支持文件类型：`.docx`、`.doc`、`.pdf`、`.txt`、`.rtf`、`.md`、`.csv`、`.png`、`.jpg`、`.jpeg`
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

迁移 `0009_add_job_verification_options` 为旧写入保留 `{}` JSONB 服务端默认值；
旧任务由新 Worker 映射为默认检查配置。

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
运行时 JSON 词库兼容旧项目的可选 `version`、`description` 元数据，仍严格校验类别和条目、
拒绝未知字段；实际加载版本以文件内容哈希为准，内容变化会触发热加载，不依赖手写版本号。

## 环境限制与后续路线图

### 当前环境限制

- Docker / Compose 验证依赖宿主机可用 Docker。
- PostgreSQL 相关集成测试必须连接真实 PostgreSQL。
- 不允许使用 SQLite 代替 PostgreSQL 合约验证。

### 后续路线图

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
