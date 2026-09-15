# Text Verification · 啄木鸟

## 项目说明

面向企业内网的中英文文档预检工具，提供文件上传、文字检查、在线审阅和结果导出。
可以仅使用本地规则，也可以配置 OpenAI 兼容接口进行语义复核。

| 能力 | 说明 |
| --- | --- |
| 输入 | DOCX、DOC、PDF、TXT、RTF、Markdown、CSV、PNG、JPG/JPEG，以及直接粘贴文本 |
| 文字检查 | 错别字、英文拼写、异形词、全半角、标点、语法、表达、数字格式和术语一致性 |
| 可选检查 | 中英文间距、空格/空行、长句提示、离线英文词典与主谓一致、个人信息与凭证、敏感表述、广告极限词 |
| 自定义设置 | 六种文档场景、自定义术语、禁用词及批量导入 |
| OCR | 图片和扫描 PDF 的中英文、英文或日文识别；日文仅识别，不提供日文纠错 |
| 在线审阅 | 查找替换、问题定位、逐条接受/忽略/撤销、正文编辑、亮暗主题及会话恢复 |
| 原版式预览 | Word、RTF、PDF 和图片的统一分页视图，使用 SVG 矢量页面展示文字与定位标记 |
| 导出 | 支持的文档原格式、HTML 检查报告，以及图片/扫描件的可编辑 DOCX 重建稿 |

**使用边界**

- 单文件最大 25 MiB；任务和上传文件默认保留 24 小时。
- 版式预览最多 80 页、20 万字符、25 MiB 输出。
- 原版式预览保留可渲染的图片、表格和页眉页脚，但不承诺任意 Word 文档像素级一致；未被解析器提取的对象内容不一定参与检查。
- 图片和扫描件的原始像素不会被文字修订覆盖；DOCX 重建稿也不保证完整还原原版式。
- 定位不可靠或修改无法安全应用时明确提示，不猜测位置、不静默改成纯文本导出。
- 检查结果是辅助提示，仍需人工审阅。共享词库管理和完整的服务端审阅决策持久化仍属后续演进方向。

## 使用说明

### 本地调试：一条命令启动

完成下面的首次配置并打开 Docker Desktop 后，在仓库根目录运行：

```bash
./start-local.sh
```

| 地址 | 用途 |
| --- | --- |
| `http://localhost:5173` | 前端页面 |
| `http://127.0.0.1:8000/docs` | API 文档 |
| `http://127.0.0.1:8000/api/v1/health` | API 存活检查 |
| `http://127.0.0.1:8000/api/v1/ready` | 数据库、Redis、消息代理、兼容检查 Worker 和渲染服务的就绪状态 |
| `http://127.0.0.1:8010` | 仅供本机 API 使用的渲染网关，不是前端页面 |

脚本启动 PostgreSQL、Redis 和 Docker 渲染服务，执行数据库迁移，并管理本机 API、
检查 Worker、维护 Worker、Beat 和前端进程。缺少渲染镜像时构建，已有镜像时复用。
所有进程启动后，脚本等待 `/ready` 成功再提示可用；依赖未就绪时返回 503，并列出未就绪项。
API 热更新只监听 `apps/api/src`，不因测试文件变化而重启；关闭旧连接最多等待 5 秒，
避免长连接使热更新无限等待。启动参数修改后，需重新运行启动脚本才能生效。

保留启动终端，按 `Ctrl+C` 停止本次启动的应用进程；数据库、Redis 和渲染容器继续运行，
数据不会被删除。日志位于 `var/local/`，每次启动覆盖：

```bash
tail -f var/local/api.log var/local/worker.log
```

不要同时启动另一套 Worker 或 Beat。若 8000/5173 端口被占用，或完整 Docker 应用仍在运行，
先停止冲突服务。若异常退出留下 `var/local/run.lock`，确认旧进程已经停止后再执行
`rmdir var/local/run.lock`。

### 首次配置（macOS）

准备 Python 3.12、uv、npm 和 Docker Desktop，然后在仓库根目录执行：

```bash
uv sync --project apps/api --locked --extra dev
npm --prefix apps/web ci
test -f .env || cp .env.example .env
mkdir -p var/jobs
```

本机运行应用时需要调整 `.env`，**不要覆盖已有配置**：

| 配置项 | 本地开发设置 |
| --- | --- |
| `APP_ENV` | `development` |
| `DATABASE_URL` | 保留 `.env.example` 中的数据库用户名、密码和库名，将主机 `postgres` 改为 `127.0.0.1`，端口为 `5432` |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` |
| `CELERY_BROKER_URL` | 留空，使用 `REDIS_URL` |
| `STORAGE_ROOT` | 当前仓库下 `var/jobs` 的绝对路径 |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` |
| `PREVIEW_RENDERER_URL` | `http://127.0.0.1:8010` |
| `RECHECK_GRANT_SECRET` | 至少 32 个 UTF-8 字节的随机密钥，文件重新检查需要使用 |
| `LLM_API_KEY` | 留空使用本地规则；启用语义复核时再配置 |

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

`.env` 已被 Git 忽略，不要提交密钥。修改后端环境配置后需重启 API；只刷新浏览器不会生效。

图片和扫描 PDF 检查还需安装 OCR 可选依赖：

```bash
uv sync --project apps/api --locked --extra dev --extra ocr
```

后端直接和间接依赖锁定在 `apps/api/uv.lock`，前端使用 `apps/web/package-lock.json`。
日常安装使用 `--locked` / `npm ci`，不要通过无约束安装绕过锁文件。
有意调整后端依赖时修改 `pyproject.toml`，执行 `uv lock --project apps/api` 并一起提交锁文件。

首次 OCR 可能下载对应语言的模型，内网环境应提前准备模型及缓存。
Word/RTF 预览转换由 Docker 内的 LibreOffice 完成，本机无需为预览单独安装 Office。
部分原生 `.doc` 导出转换仍依赖本机 `textutil` 或 `soffice`。

### 完整 Docker 启动

此方式与本地原生启动二选一，不要同时运行两套应用。
首次创建 `.env` 后配置 `RECHECK_GRANT_SECRET`；生产、预发布等部署环境会拒绝空密钥或过短密钥。

```bash
test -f .env || cp .env.example .env
docker compose --env-file .env -f infra/compose.yaml up --build -d
```

打开 `http://localhost:8080`。Compose 自动使用容器内的数据库、Redis 和存储地址，
无需把原生开发 `.env` 中的本机地址手动改回容器服务名。
若 Docker Hub 基础镜像无法拉取，可参考 `.env.example` 中的
`PYTHON_IMAGE`、`NODE_IMAGE`、`NGINX_IMAGE` 镜像源配置。

查看日志或停止容器：

```bash
docker compose --env-file .env -f infra/compose.yaml logs -f api worker renderer
docker compose --env-file .env -f infra/compose.yaml down
```

停止本地调试留下的基础服务时，使用相同命令并追加
`-f infra/compose.local-services.yaml`，放在 `down` 之前。
**不要添加 `-v` 或 `--volumes`，否则会删除数据库和上传任务数据。**

### 页面操作

1. 上传文件或粘贴文本，选择文档场景、检查项、术语和禁用词，再点击“开始检查”。选中文件不会自动提交。
2. 在双栏工作区审阅结果：正文占主要区域，右侧为问题列表或检查摘要。拖动两栏间的分隔线调整宽度，双击恢复默认；分隔线聚焦后也可用左右方向键调整、Enter 恢复。查找替换从正文工具栏按需展开，宽面板使用单行、中等面板使用两行紧凑布局，窄面板自动换行；手机端在文档与问题之间切换。
3. 点击问题，将对应高亮定位到正文阅读区域中部（文档首尾受滚动边界限制），不带动整个页面滚动。在问题卡片内选择建议并接受、忽略或撤销；顶部显示待处理、已接受和已忽略计数。“编辑正文”用于自由修改，“撤销修改”位于查找替换面板。
4. 手工编辑或替换后按提示重新检查。修改检查设置不会清空文档，但需要点击“重新检查”才会应用新设置。

输入框和选择框聚焦时仅改变原有细边框的颜色，不叠加外围光圈；无边框控件保留内侧细线，便于键盘操作时识别焦点。
所有选择菜单贴着选择框下方向下展开，随容器滚动保持对齐，不遮盖当前字段；可使用方向键浏览、Enter 确认、Escape 取消本次选择。菜单展开时，Escape 仅关闭菜单，不关闭设置弹窗。
5. 从顶部导出菜单下载文件或报告。“保留修订”在打开、恢复或新建工作区时默认关闭，需要时手动勾选。
6. 更换文件前先导出需要保留的结果，再点击左上角“啄木鸟”返回新建检查；该操作会清空当前工作区。

纯空白修改以“3 个空格 → 1 个空格”等可读形式展示，接受建议时仍使用原始字符。
原版式中带下划线或混合字体产生的重叠空格，使用可靠相邻文字之间的实际空白区域定位；
无法区分单个空格坐标时标记整段空白，不借用相邻正文或其他行的位置。
短标题、表格字段和换行字段会结合完整行边界补齐定位；重复金额需由已定位的前后内容确认，
复选框等符号字体标记不影响其后文字的定位。只有非空白正文仍有无法可靠匹配的内容时，
才显示整篇文档的定位提示；重复页眉、缺失文字等真正有歧义的情况仍保留提示。

**设置入口**：上传页在输入卡片内，审阅页在右上角，每页只有一个入口。
检查过程中可以查看设置，但不能修改。重新检查使用当前修订文字，不重新执行 OCR；
更换 OCR 语言后需要重新上传文件。

**检查精度与覆盖范围**

- 六种文档类型加载各自独立规则包，不再共用全部规则后筛选显示。
  基础校对算法可复用；专业规则、触发条件、例外和模型审阅策略分别定义。
  设置面板显示运行中服务端的真实规则清单及适用条件。
  新建检查页将场景选择和检查设置集中在同一行；规则摘要位于下方，
  详细规则默认折叠，展开后可查看触发条件与例外。
- 本地规则共用技术区域识别，避免改动 URL、邮箱、代码块、行内代码、下划线标识符、
  Windows/Unix 路径和常见文件名。
  个人信息、敏感内容和用户强制约束仍可检查这些区域，不因代码保护而被跳过。
- 英文自定义术语按完整标识符边界匹配，`AI` 不会命中 `MAIL`、`AI2` 或 `AI_name`。
  自定义标准词形保护词典检查，且不修改其他任务使用的共享词库。
- 同位置、同修改意图的标点或词形提示合并，并保留其他规则的说明；不同建议及独立约束保留。
  用户术语和禁用词在同位置优先显示，但不会静默丢弃其他冲突建议，需要逐项审阅。
- 数字混写在每个出现位置提示；编号按列表原顺序、缩进层级检查缺号、重复和倒序，
  空行或新段落分隔列表。编号问题只给人工建议，不自动重编号。
- “扩展检查”还启用随依赖安装的离线英文词典候选和保守的主谓一致规则，无需下载模型或调用外部服务。
  词典候选限制为编辑距离 1；大小写混合的名称、缩写、部分英式词形及常用技术词受到保护。
  不确定候选只供核对，复杂语法、未收录专业词和真实单词的语境误用仍需人工判断。
- `confidence` 是独立于严重程度的规则启发式分数，不是经过真实业务语料校准的正确概率。
  有修改建议不代表允许自动应用；描述性建议、编号和缺失关联词提示不可直接替换。

**独立规则包的专业范围**

| 类型 | 当前已实现的本地检查 |
| --- | --- |
| 通用文档 | 基础文字、标点、重复词与明确语法检查；不强制专业结构，不纠正日常口吻 |
| 学术论文 | 明确编号引文与文末参考文献对应、本文图表引用与题注对应、连续显式缩写定义冲突 |
| 商务文档 | 明确金额明细与合计、同项目起止日期倒置、明确行动清单中的模糊期限或缺少负责人 |
| 法律文书 | 单份合同的当事方简称、明确本合同条款引用、相邻阿拉伯数与人民币大写整数金额不一致 |
| 新闻稿 | 明确标题/导语的同事件同指标数量矛盾、以发布日期为基准的相对日期矛盾、笼统数据来源提示 |
| 技术文档 | 参数定义与 JSON 示例键名大小写/下划线差异、显式支持版本区间与当前版本矛盾、完整单流程步骤引用 |

这些是**证据受限的文本检查，不是全行业自动审计**。参考文献要求明确的终末参考文献区及唯一编号；
图表要求可识别题注；缩写检查只比对连续显式定义，不宣称覆盖全部首次定义。
支持研究陈述句末的普通 `[2]` 引文和空格分隔题注；不把数组下标或链接当作引文。
显式缩写声明不再触发内置展开替换，中英双语释义不因语言组合不同判为冲突；用户自定义术语仍优先。
金额合计要求同币种、金额明细行和明确合计，不推测税额、折扣、单价与数量；
支持普通“金额明细”标题，但要求至少两条金额行及空行或文末结束；项目日期允许独立负责人字段，
不跨项目或含重复日期的模糊区块比较，已完成待办不阻断后续未完成事项检查。
人民币大小写核对目前限紧邻的 0–9999 元整数，不处理小数或跨段金额。
合同条款支持空格、冒号及独立标题；仅实际定义构成当事方声明，普通提及不算定义。
新闻数量核对限相同完整事件措辞中的单一整数指标（伤亡失踪人数及特定企业、学校、医院、桥梁计数），
不核验外部事实；相对日期必须同时有发布日期和括注的绝对日期，不使用系统日期猜测。
存在另一明确叙述时间基准时保守跳过日期比较；来源提示要求归属关系，不因正文出现“公司”等词而免检。
技术参数检查限唯一参数定义区与平面 JSON 示例的已知名称，不把未知扩展键当作错误；
含转义的键保守跳过，嵌套数组/对象在解码前排除，不因此中断其他本地检查。
版本检查限相邻且唯一的闭区间/当前版本字段，不解析预发布版本；步骤检查不跨多个流程比较。
引文、图表引用、完整金额清单、行动清单、合同缺失目标和步骤引用检查仅适用于完整 TXT/Markdown
或完整粘贴文本；其他提取格式跳过这些规则，结果页列出具体“未检查”项目及提取不完整的原因。
保存、恢复和重新检查保留来源格式，避免将文件提取文本误当成完整原文。详细触发格式和例外以界面中的每条规则说明为准。
专业提示均须人工确认，不自动替换；语义发现仍需显式开启，不代表补齐上述所有未支持的能力。
否定表达仅在有限模式下提示人工核对，不自动删除否定词。基础空格清理不会删除合同条款标题分隔符。
专业规则兼容 LF/CRLF（包括浏览器表单换行），不改写输入文本，问题位置仍指向原始字符区间。
专业规则保护成对的跨行引号和 Markdown 块引文及其续行，避免用转载日期校对被引用原文的相对日期。

**Word 检查范围**：正文及嵌套表格按文档 XML 中的顺序读取，再读取各节引用的页眉页脚。
合并单元格和共享页眉页脚只计一次；页眉页脚位于检查文本的正文之后，不代表其物理页面位置。
提取、导出和分页预览使用相同遍历顺序，API 与渲染服务应一起更新。
旧任务若采用了不同的提取顺序，需要重新上传检查；重复文本使新旧位置无法区分时，
拒绝按旧偏移自动修改。不能可靠映射到 Word 文本运行片段的修改、破坏提取文本一致性的修改
会明确报错；正文和页眉页脚的同文定位有歧义时不猜测坐标。
脚注、尾注、文本框、内容控件及修订容器仍不保证完整提取，不应视为已覆盖整份 Word 文件。

**可选语义发现**：不同于仅复核规则命中项的语义复核，它可以从局部片段发现新问题。
默认关闭，必须同时满足：管理员配置获准的 `LLM_API_BASE`、`LLM_API_KEY`、`LLM_MODEL`，
在服务端设置 `LLM_SEMANTIC_DISCOVERY_ALLOWED=1`，用户再在检查设置中开启“语义发现”。
不要将保密文档发送给未经批准的供应商；该功能会发送抽样的局部上下文及相关术语，
增加调用费用和等待时间。没有配置或未获服务端允许时，不能将结果视为已完成语义发现。

默认最多选取 6 个片段，每段正文 800 字符、上下文半径 100 字符，最多保留 24 个新候选；
`.env.example` 的 `LLM_SEMANTIC_*` 设置控制相应预算。长文采用分散抽样而不是只检查开头，
抽样不能代表全文覆盖，应查看界面中的覆盖/降级提示。
新候选必须能锚定原文并通过结构校验；语义建议仅供人工审阅，不自动改写正文。
配置或调用失败时保留本地检查结果并提示降级，不伪装成“没有问题”。

**检查进度**：在检查设置下方、开始检查按钮上方显示细进度条，不再展示任务详情区。
文件任务使用实际进度；尚未收到任务进度或直接文本检查时使用不定进度条。失败和连接异常仍会提示。

**任务恢复**：文件上传成功并取得任务编号后，同一标签页刷新会重新连接任务，不会重复上传。
浏览器只保存有界的任务编号、文件信息和设置，不保存上传文件内容；服务端任务过期后需重新选择文件。
连接等待超时可点击重试连接，停止等待不等于取消后台任务。尚未取得任务编号的上传和直接文本请求不能自动续接。

**查找快捷键**：Ctrl/Cmd+F 展开正文内的查找替换并聚焦查找框，Enter 定位下一项，Shift+Enter 定位上一项。
Escape 收起查找并将焦点交回工具栏；保留本次查询，收起时不显示查找高亮。手机端会先切换到文档面板。
设置等弹窗打开时，不拦截弹窗内的快捷键；定位只滚动对应阅读区域。

**界面层级**：新建页保留单一输入卡片，类型与设置同排，规则摘要无边框显示、详情按需展开。
审阅页使用中性背景、蓝色强调和问题选中侧线；文件名统一显示在顶栏。
审阅区使用可用屏幕宽度，宽屏下统计与状态同排，正文及版式工具栏保持紧凑，优先保留文档显示空间。
检查范围限制、未检查项及语义抽样合并为一个状态区，限制摘要始终可见，详细原因可展开。
任务失败、部分完成和导出错误不隐藏；视觉简化不改变人工确认、修订或导出权限。

**分页缩放**：支持适合宽度及 25%、50%、75%、100%、125%、150%、200%。
当前百分比以适合宽度为基准，100% 与当前容器的适合宽度等效，并非打印尺寸的 1:1 比例。
缩小时页面居中，缩放不会改变原文和导出文件。

**定位提示**：“部分文字无法精确定位”表示预览文字与页面坐标未完全匹配，
不代表文件损坏或检查失败，也不表示所有问题都无法定位。
空格使用页面中实际测量的坐标定位；连续空格被排版合并时，高亮对应的整体区域。
连字的共享字形和表格/正文提取顺序差异不会直接使整篇定位失效；
能够唯一匹配的完整段落仍可独立定位。
正常的标题/正文重复不会仅因重复出现而被误判；真正存在额外重复或无法可靠对齐时，
仍需结合右侧原文和上下文审阅。

## 项目架构

### 运行结构

```text
浏览器（Vue 3）
    |
    | /api：开发时由 Vite 代理，Docker 部署时由 nginx 代理
    v
FastAPI
    +-- PostgreSQL：任务、事件、结果及检查参数
    +-- Redis / Celery：检查任务队列
    |       +-- 检查 Worker：文档解析、OCR、规则检查、可选语义复核
    |       +-- 维护 Worker：过期清理、租约救援
    |       +-- Beat：定时发布维护任务，同一环境仅运行一个实例
    +-- Job Storage：每个任务独立目录保存源文件和产物
    +-- renderer：LibreOffice 转换、SVG 分页图像及文字坐标
```

Worker 使用 `text-verification-worker` 入口：检查角色为 `TEXT_VERIFICATION_WORKER_ROLE=verification`，
消费 `celery,verification-v2`；维护角色为 `TEXT_VERIFICATION_WORKER_ROLE=maintenance`，
只消费 `maintenance-v2`，避免维护任务占用检查并发。
旧版 Worker 命令必须限定 `--queues=celery`，只排空遗留任务，不接入新参数任务队列。

文本检查走同步 `POST /api/v1/analyze`；文件上传走异步 `POST /api/v1/jobs`，
通过 SSE 获取进度，再读取任务结果。设置以任务参数快照传递，不通过修改全局变量影响其他任务。

浏览器将文档快照与轻量界面偏好分开保存，切换问题、筛选和视图不重复序列化整个文档。
文件任务的恢复记录独立于完成后的审阅快照；存储不可用、记录无效或过期时明确提示。

分页预览走 `POST /api/v1/jobs/{job_id}/preview/layout`，请求包含源版本
`source_version` 和当前修订全文 `text`。API 校验源文件身份后，在临时副本上应用修订并渲染；
预览不覆盖原文件，也不保存审阅决策。

分页结果在每个 API 进程内使用有界缓存：最多 4 份、合计 32 MiB，命中有效期 60 秒。
缓存键区分任务、源版本和修订内容；即使命中，也重新核对源文件身份，不绕过过期或篡改检查。
浏览器按可视区域构建问题和搜索定位层，页面图像延迟加载、异步解码；跨页选择仍可直接定位。

渲染服务使用只读根文件系统、受限临时目录、内部网络和单转换并发，不读取 `.env`、
数据库或任务存储；容器 init 回收 Office 辅助进程。
本地 API 通过仅绑定 `127.0.0.1:8010` 的网关访问它，完整 Docker 部署由 API 直接访问 renderer。

### 依赖与交付

后端镜像默认构建 `runtime` 目标，保留 OCR、字体和 LibreOffice，但不包含测试目录及
pytest、Ruff、mypy 等开发工具；需要开发工具时显式使用 Dockerfile 的 `development` 目标。
仓库级集成检查在完整代码检出目录中运行。

`.github/workflows/ci.yaml` 包含前端单元测试、构建与浏览器流程，以及后端静态检查和真实
PostgreSQL 隔离模式测试。另一条独立服务流程构建生产镜像，启动临时应用栈，
预热真实 OCR 模型后运行上传、OCR 和渲染流程。
CI 通过同时连接默认网络与渲染网络的网关访问 `127.0.0.1:8010`；
渲染容器仍留在内部网络，不直接发布宿主机端口。
`apps/api/scripts/ci_pytest.py` 要求相应服务配置齐全，遇到跳过的测试会让该流程失败，
不会把缺少数据库或 OCR 环境算作成功。

### 代码目录

| 路径 | 职责 |
| --- | --- |
| `apps/web/src/components/workspace/` | 上传、检查设置、文档预览、问题列表、导出等界面 |
| `apps/web/src/views/WorkspaceView.vue` | 工作区状态与交互编排 |
| `apps/web/src/api/`、`composables/` | 请求转换、审阅状态、查找替换和会话恢复 |
| `apps/api/src/text_verification/api/` | API 路由和输入处理 |
| `apps/api/src/text_verification/domain/` | 文档、问题、检查参数及接口约定 |
| `apps/api/src/text_verification/application/` | 检查流水线、任务与预览业务流程 |
| `apps/api/src/text_verification/parsers/`、`document_processing/` | 文档解析与 OCR |
| `apps/api/src/text_verification/checkers/`、`compatibility/analyzer.py` | 检查器及现有规则实现 |
| `apps/api/src/text_verification/scenarios/` | 六种独立规则包、专业规则、目录和语义策略 |
| `apps/api/src/text_verification/resources/dictionaries/` | 实际运行时使用的内置词库 |
| `apps/api/src/text_verification/exporters/`、`infrastructure/` | 导出、数据库和文件存储实现 |
| `infra/` | Docker Compose 和渲染网关配置 |
| `apps/web/tests/`、`apps/api/tests/` | 前后端测试 |

架构背景见 [平台架构设计](docs/architecture/document-verification-platform.md)；
目录约定见 [仓库组织说明](docs/architecture/repository-layout-and-documentation.md)。
`docs/development/` 和 `docs/superpowers/` 保留历史实施记录，具体运行行为以当前代码为准。

## 扩展检查设置

### 先确定要改哪一层

| 目标 | 操作入口 |
| --- | --- |
| 仅为当前工作区添加术语或禁用词 | 直接使用“检查设置 → 术语 / 禁用词”，无需修改代码 |
| 修改内置敏感词或广告极限词 | 修改后端运行时词库 JSON，保持现有结构 |
| 修改选项文案、布局或默认勾选状态 | 修改前端组件和状态默认值，并核对后端默认值 |
| 调整已有文档场景的检查范围 | 修改 `scenarios/<场景>.py` 的独立规则包及对应测试 |
| 新增独立检查开关或规则 | 接通界面、请求、参数模型、任务上下文和规则执行链 |

以下前端路径以 `apps/web/src/` 为前缀，后端路径以
`apps/api/src/text_verification/` 为前缀。

| 内容 | 主要文件 |
| --- | --- |
| 检查设置抽屉和分类 | 前端 `components/workspace/WorkspaceSettingsDialog.vue` |
| 场景、OCR 语言及检查开关 | 前端 `components/workspace/VerificationSettings.vue` |
| 术语与禁用词编辑 | 前端 `components/workspace/TerminologyEditor.vue`、`composables/useTerminology.ts` |
| 设置类型 | 前端 `types/verification.ts` 的 `AnalyzeOptions` |
| 页面状态、应用设置、重置和恢复 | 前端 `views/WorkspaceView.vue` |
| 共享默认值、场景列表、设置复制、参数校验及请求转换 | 前端 `api/analyzeOptions.ts` |
| 会话保存与旧版本兼容 | 前端 `composables/useWorkspaceSession.ts` |
| 后端参数与默认值 | 后端 `domain/verification.py` 的 `VerificationOptions` |
| 独立场景包、专业规则和语义策略 | 后端 `scenarios/` |
| 可复用的基础文字检查 | 后端 `compatibility/analyzer.py` |
| 服务端规则清单的获取与校验 | 前端 `api/scenarioCatalog.ts` |

当前有效默认值：

| 设置 | 前端字段 / 后端字段 | 默认值 |
| --- | --- | --- |
| 文档场景 | `scenario` / `scenario` | `general`，通用文档 |
| 扩展检查 | `enableExtendedRules` / `enable_extended_rules` | 关闭 |
| 语义发现 | `enableSemanticDiscovery` / `enable_semantic_discovery` | 关闭；还需服务端允许 |
| OCR 语言 | `ocrLanguage` / `ocr_language` | `zh`，中英文 |
| 个人信息与凭证 | `enableSecurity` / `enable_security` | 开启 |
| 敏感表述 | `enableSensitive` / `enable_sensitive` | 开启 |
| 广告极限词 | `enableAdExtreme` / `enable_ad_extreme` | 关闭 |

注意：主页面的 OCR 和扩展检查初始值允许为 `undefined`，由界面和请求转换采用默认值。
默认值集中在 `api/analyzeOptions.ts` 的 `createDefaultAnalyzeOptions()`、
`DEFAULT_OCR_LANGUAGE` 和 `DEFAULT_EXTENDED_RULES`，页面与术语编辑复用这些定义。
修改默认行为时仍需核对后端接口默认参数和旧会话恢复逻辑，不能只修改复选框外观。

### 修改词库或文档场景

运行时默认读取：

```text
apps/api/src/text_verification/resources/dictionaries/sensitive_rules.json
apps/api/src/text_verification/resources/dictionaries/ad_extreme_words.json
```

根目录 `resources/dictionaries/` 中的同类资源不是运行时默认读取路径。
词库由 `infrastructure/dictionary_loader.py` 加载，结构由 `domain/dictionaries.py` 校验；
请沿用现有字段与条目结构，不随意增加未知字段。词库版本根据内容哈希计算，
读取时会识别内容变化。部署为镜像时仍需把更新后的资源构建并部署进去。

六种场景分别定义在 `scenarios/general.py`、`academic.py`、`business.py`、
`legal.py`、`news.py`、`technical.py`。每个 `PROFILE` 显式选择基础检查、
可选扩展检查，定义专业规则及其条件、例外和语义审阅策略。
`TextAnalyzer` 只调用所选包声明的基础算法；
`scenarios/checker.py` 只执行该包的专业规则，使用剩余问题预算。
不再先执行所有规则，再通过 `skip_types` / `downgrade_types` 隐藏结果。
自定义术语、禁用词及显式开启的安全检查是独立约束，不受规则包切换影响。

`GET /api/v1/scenarios` 返回运行中规则包的版本、基础/扩展检查清单、专业规则说明和语义策略。
设置界面直接读取该清单；读取失败时明确提示并允许重试，不使用前端编造的规则说明。
专业规则使用 `scenario.<类型>.<规则>` 标识，保留精确原文位置与证据说明，均不可自动替换。
修改包的规则行为时同步更新 `PROFILE.version` 和正反例；问题中保存规则包来源及版本。
涉及“目标不存在”的检查只对 TXT/Markdown 完整提取文本执行，并需要规则规定的明确结构；
粘贴节选也只能判断提交的文本，不能证明原始全文缺失内容。
DOCX、PDF、OCR 等格式不保证所有引用目标都已提取，因此跳过这些缺失目标判断。
跳过项目通过 `degradation.reasons` 的 `scenario_rule_skipped:<规则 ID>:<规则名称>` 返回并在界面显示。
任务重查使用原任务格式；同步文本重查可通过 `/analyze` 的 `source_file_type` 传递原格式（默认 `txt`）。
此字段仅声明提取来源，不授予原文件导出权限；上传文件仍以实际上传格式为准。
显式存在的金额、日期、参数等矛盾仍可按各规则的证据条件检查。

两种模型路径均使用所选包的语义策略，但抽样片段不能用于断言全文缺少引用、定义、
附件或步骤，也不能进行事实核验或法律合规认证；模型不可用时仍保留本地结果。
新增场景还需同步后端 `domain/verification.py` 的 `Scenario`，
以及前端 `types/verification.ts`、`api/analyzeOptions.ts` 的 `SCENARIO_OPTIONS`
和 `useVerificationWorkspace.ts` 的 `isScenario()` 校验；设置组件复用共享场景列表。

### 新增检查开关：完整操作顺序

可以参照现有 `enableExtendedRules` / `enable_extended_rules` 的实现。
下面以 `enableCustomCheck` / `enable_custom_check` 为示例字段名，**该字段目前并不存在**。

1. **定义参数和默认值。** 在前端 `AnalyzeOptions`、后端 `VerificationOptions` 中增加字段，
   为新增检查选择明确且兼容旧任务的默认值，通常默认关闭。后端参数模型拒绝未知字段，
   不能只让前端发送一个新参数。
2. **增加界面并接通状态。** 在 `VerificationSettings.vue` 增加开关，通过
   `update:options` 更新。在 `api/analyzeOptions.ts` 定义兼容默认值；
   `WorkspaceView.vue` 和 `useTerminology.ts` 通过共享的 `copyAnalyzeOptions()` 保留设置。
   仍需覆盖初始化、重置、恢复及编辑术语的路径，避免丢失新字段。
3. **接通请求和会话。** 更新 `api/analyzeOptions.ts` 的
   `createAnalyzeOptionsSnapshot()`、`appendAnalyzeOptions()` 和序列化大小计算，
   将前端 camelCase 字段转换为后端 snake_case 字段。
   同步 `useWorkspaceSession.ts` 的字段白名单、校验及旧会话兼容，并覆盖 `usePendingJob.ts` 的任务恢复。
   不能因旧会话缺少新字段而直接丢弃会话。
4. **覆盖所有后端入口。** 更新 `api/routes/compatibility.py` 的同步检查、
   `api/routes/jobs.py` 的文件上传及重新检查参数，并更新
   `compatibility/service.py` 的 `build_verification_options()`。
   三条路径必须得到一致的设置，不能只让“粘贴文本”生效而文件上传不生效。
5. **传入规则执行链。** 更新 `domain/ports.py` 的 `CheckContext` 和
   `CheckContext.from_options()`，再更新 `checkers/compatibility_checker.py`
   中的参数协议与调用分支，将开关传给 `TextAnalyzer`。
   扩展检查开启、无进度观察者、有进度观察者这三个分支都要覆盖，避免不同执行路径丢失参数。
   不要用模块级全局变量保存用户开关。
6. **实现检查规则。** 在 `compatibility/analyzer.py` 中实现并按开关调用规则；
   同步相关的同步/异步调用参数。返回稳定的 `rule_id`、问题类型、原文、建议和位置。
   若新增问题类型，还需更新 `TYPE_TO_LAYER`、规则包声明和前端 `WorkspaceView.vue` 的 `typeLabels`。
   问题位置应基于 `DocumentModel.text` 的 Unicode 码点偏移，不要使用前端 UTF-16 长度代替。
7. **验证快照、恢复和生效时机。** 确认任务保存并重新读取参数后开关仍然有效，
   老任务缺少该字段时采用兼容默认值；刷新会话不丢失设置。
   审阅期间修改设置仍应在“重新检查”后生效，不修改当前检查结果。

参数流转可概括为：

```text
VerificationSettings.vue
  → WorkspaceView.vue / AnalyzeOptions
  → api/analyzeOptions.ts
  → API 路由 / VerificationOptions
  → CheckContext.from_options()
  → CompatibilityChecker
  → TextAnalyzer（所选包的基础检查）+ scenarios/checker.py（所选包的专业检查）
```

任务参数通过 `encode_verification_options()` / `decode_verification_options()` 编解码。
新增有默认值的字段不应让历史任务无法读取；如果还要改变持久化结构或历史语义，
应另外评估迁移，而不是覆盖旧任务参数。

较大的独立检查模块可以实现 `domain/ports.py` 的 `Checker` 接口，
在 `application/factory.py` 的 `CheckerRegistry` 中注册，不必把所有逻辑继续堆进 `TextAnalyzer`。
它同样需要通过任务上下文接收设置。

### 检测效果评估

内置小型人工构造集位于 `apps/api/tests/quality/detection_cases.json`，
按中文、英文、技术文本和编号结构分组，分为 `regression` 与 `holdout`。
评估器只运行本地检查，不使用 `.env` 中的模型密钥、不发送文本。
项目根目录下运行：

```bash
apps/api/.venv/bin/python -m text_verification.evaluation \
  apps/api/tests/quality/detection_cases.json --split holdout
apps/api/.venv/bin/python -m pytest apps/api/tests/quality -q
```

数据中的 `expected` 标注 Unicode 码点起止位置、问题类型和期望建议；
默认开启扩展检查、关闭敏感信息检查，可通过每例的 `options` 明确指定完整配置。
同位置的不同类型问题需要分别标注。评估按位置和类型一对一匹配，输出精准率、召回率、
建议正确率、源文位置有效率及每千字误报数，并分别汇总各组；分母为零时返回 `null`，不伪装成满分。
测试门槛只适用于该小型构造集，不代表生产文档的效果。
Word 提取、导出回写和 OCR 由各自的集成测试覆盖，不计入纯文本构造集的覆盖率。
真实上线评估应另外准备经授权、人工标注且未参与调规则的业务文档，
固定测试集后再比较不同版本，不能用新增提示数量代替质量提升。

**扩展 OCR 语言**还需同步前后端语言白名单、`VerificationOptions` 与 API 参数校验、
`application/verification_pipeline.py`、`parsers/image_parser.py`、
`parsers/pdf_parser.py` 和 `document_processing/ocr_provider.py`，
并准备对应 OCR 模型。只增加下拉选项不会自动获得新语言识别或纠错能力。

### 验证与让修改生效

优先覆盖：默认关闭、开启后命中、关闭后不命中、独立规则包执行隔离、Unicode 偏移、
文件与直接文本的一致性、重新检查、会话恢复，以及接受/撤销后的导出行为。
已有测试可作为新增用例的起点，在仓库根目录运行：

```bash
npm --prefix apps/web run test -- \
  tests/VerificationSettings.spec.ts tests/analyzeOptions.spec.ts \
  tests/WorkspaceView.spec.ts tests/WorkspaceSession.spec.ts \
  tests/TerminologyEditor.spec.ts tests/useTerminology.spec.ts
npm --prefix apps/web run build
apps/api/.venv/bin/python -m pytest \
  apps/api/tests/unit/domain/test_verification_options.py \
  apps/api/tests/unit/compatibility/test_extended_rules.py \
  apps/api/tests/unit/application/test_verification_pipeline.py \
  apps/api/tests/unit/infrastructure/test_dictionary_loader.py -q
```

涉及 API 参数或任务持久化时，再覆盖 `apps/api/tests/integration/` 中的
`test_create_job.py`、`test_compatibility_api.py` 和 `test_job_recheck_routes.py`。
数据库集成测试需要配置独立的 `TEST_DATABASE_URL` 并连接真实 PostgreSQL，
不要指向业务数据库，也不要用 SQLite 代替。
涉及浏览器交互时运行 `apps/web/tests/e2e/workspace-lifecycle.spec.ts`。

本地前端、API 和渲染服务支持热重载；**检查 Worker 不会自动重载规则代码**，
修改检查逻辑或依赖后应停止并重新运行 `./start-local.sh`。
修改后端依赖或 Dockerfile 后，先重建渲染服务：

```bash
docker compose --env-file .env -f infra/compose.yaml -f infra/compose.local-services.yaml \
  up -d --build --wait renderer renderer-gateway
```

完整 Docker 部署不挂载本地源代码，修改后需要重新构建并部署对应服务。
