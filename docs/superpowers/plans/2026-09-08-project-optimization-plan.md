# Text Verification 全面审查与优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本轮仅输出审查与计划；实施须另行获得用户批准。

**Goal:** 在保留现有功能与数据完整性的前提下，将中英文文档预检整理为单屏优先、状态可信、任务可恢复、部署可重复的工作台。

**Architecture:** 保留 Vue 3、FastAPI、PostgreSQL、Redis/Celery 和统一 VerificationPipeline，不另建 Flask 应用，不拆微服务。优先修复用户可见的布局、执行状态与版本兼容问题，再处理性能和模块边界。

**Tech Stack:** Python 3.12、Vue 3、TypeScript、PyMuPDF、RapidOCR、PostgreSQL、Redis/Celery、pytest、Vitest、Playwright。

**Spec:** 用户于 2026-09-08 提出的“全面审查这个项目，给出优化 plan”“不需要日文”“整个显示尽量在一个页面，尽量不要滚动页面”；产品基础见 `README.md`，本文件第 1、3 节将这些要求转化为实施约束与验收标准。

## Global Constraints

- 只针对 `Text-Virification` 当前工作树；保留已有未提交修改，不把 HEAD 差异全部归因于本轮。
- 当前阶段不改业务代码、不提交代码、不重启服务、不变更数据库或 `.env`。
- 此前已停止本会话托管的两个 Worker 命令；审查收尾仍发现运行中的 Worker 进程，不能据此前操作断言环境已停机。本轮不接管、重启或终止这些进程。
- 产品聚焦中英文；不继续扩展日文功能，但移除时不得使已有任务、审阅结果或会话不可读。
- 保留九类输入、纯文本检查、六层规则、场景、词库、合规开关、审阅、撤销、查找替换、重新检查和导出。
- 保留源文件哈希、代码点偏移、修订身份、重新检查授权、导出校验、资源上限和任务过期机制。
- 默认本地处理；审查与回归只使用合成文档，不向外部服务发送用户文档。
- 尽量单屏不是禁止所有滚动：桌面正常字号减少整页滚动，长内容允许面板内滚动；小屏、缩放和辅助技术场景不得裁切功能。
- 不新增框架、状态管理库、任务系统或虚拟列表依赖来代替问题定位；先用现有工具和结构。
- 后续实施按任务独立评审；是否提交、合并和发布由用户决定。

---

## 1. 总体判断与审查边界

项目已有较完整的功能底座，当前最值得优化的不是继续增加检查种类，而是：

1. 上传、排队、检查、结果之间的体验和状态一致性。
2. API、Worker、持久化选项之间的升级兼容与可观测性。
3. 刷新、断线和长文档情况下的恢复能力及交互成本。
4. 文档还原质量、可重复交付和真实链路回归。

本次覆盖源码关键链路、现有自动化、部署配置和浏览器布局，不等于渗透测试、生产压测或所有文档格式的视觉一致性认证。优先级表示本项目实施顺序，不是漏洞严重等级。

### 应保留的基础

- 已有统一规范模型和 Pipeline，不应再平行维护一套业务引擎。
- 已有严格输入、来源身份、修订与导出保护，不能为“兼容”而整体放宽校验。
- 审阅页已经使用视口高度和独立内容面板；应把相同原则延伸到上传/执行页，而不是重写全部界面。
- 已有大量规则、状态机、会话、OCR、导出回归；应增加缺失的真实链路和布局断言，而不是替换测试框架。
- 租约 fencing、单调进度、先保存结果再完成、失败重试复用已保存结果，以及 Pipeline 执行期间不持有数据库 Session，均是已存在且应保留的可靠性设计。

## 2. 已确认的问题与证据

| 编号 | 优先级 | 结论与性质 | 证据 | 用户影响 |
| --- | --- | --- | --- | --- |
| U1 | P0 | 上传/执行页没有视口高度预算，已复现 | `WorkspaceSetup.vue:83,119-125`；`SourceInputPanel.vue` 的 220px 上传区；`WorkspaceView.vue:1380-1398` | 文件就绪后仍保留大上传框，再追加进度，操作被推到屏幕下方 |
| U2 | P0 | 执行状态展示像调试输出，且相互矛盾，已确认 | `JobProgress.vue:29-52`；`SourceInputPanel.vue:211-215,247-249` | `queued` 时按钮写“正在检查”，文件写“等待开始”，进度又重复文件名与英文内部状态 |
| R1 | P0 | API/Worker 升级兼容存在实际失败案例，尚无持久预防措施 | 本次旧 Worker 在 `decode_verification_options` 拒绝新增字段；当前严格模型 `domain/verification.py:97-153` | 任务领取前失败，数据库仍 queued/0%，仅重启进程只能解决当次问题 |
| R2 | P0 | 存活检查与处理就绪未分离，已确认 | `api/routes/health.py:6-12` 固定返回 ok；`infra/compose.yaml` 的 API healthcheck 只访问该接口 | API 看起来健康，用户无法知道是否有能处理当前协议的 Worker |
| R3 | P1 | 执行中的任务刷新后不能续接，已复现 | `WorkspaceView.vue:1157-1159` 无结果则不保存；`useVerificationExecution.ts:431-449` 只恢复已有结果的身份 | 浏览器刷新后丢失队列进度入口，用户可能重复上传 |
| R4 | P1 | 请求与订阅缺少完整的等待/取消/恢复策略，源码确认 | `api/jobs.ts:25-31,75-115,119-229`；`useVerificationExecution.ts:398-429` | 断线时持续等待；请求代次可防旧响应污染，但不能中断底层请求或恢复处理进度 |
| R5 | P0 | 单个不可读选项可阻断整个救援批次，源码确认 | `infrastructure/repositories.py:242-274` 在批次内逐条 `_to_job_read`；`workers/tasks.py:482-500` 整批提交/回滚 | 同批正常任务也可能得不到重投递；行锁隔离不能替代错误隔离 |
| R6 | P0 | 救援消息发布后、领取前失败的恢复闭环不完整，条件性风险 | `infrastructure/repositories.py:249,279-305` 只选择 published 标记为空的行；清空标记依赖成功领取 | 已确认发布后丢失或领取前失败的消息，可能不再进入救援；不能把 broker 接收入队等同于执行成功 |
| R7 | P1 | 异步路由直接调用同步数据库/复检，源码确认 | `api/routes/jobs.py:243,659,683-695` | 同步工作期间占用事件循环；实际并发影响需测量，不能仅凭单次成功判断可靠 |
| P1 | P1 | 日文仍在当前代码中，不符合最新产品范围 | `types/verification.ts:7`；`VerificationSettings.vue:64,105,108`；`WorkspaceSetup.vue:78` | “不需要日文”此前只讨论，尚未实施移除 |
| Q1 | P1 | 仓库内缺少 CI 发布门禁，真实服务回归可被跳过 | `.github` 不存在；`tests/conftest.py:41-48`；`tests/e2e/test_upload_lifecycle.py:12-16` | 大量本地通过不等于 API/Worker/数据库组合可用 |
| O1 | P1 | 后端依赖与镜像交付缺少固定版本产物 | `apps/api/pyproject.toml` 使用范围；无后端锁定文件；`apps/api/Dockerfile` 将 dev 与 OCR 安装到同一运行镜像 | 重建产物可能漂移，普通运行镜像包含测试工具与测试代码 |
| L1 | P1，启用云复核前 | 云复核状态与数据边界没有形成清晰的用户控制面 | `compatibility/llm_review.py:62-76,200-246`；`PrivacyDialog.vue:28-31`；工作台未展示 `analysis_mode/degradation` | 配置密钥即可启用，用户看不到本次是否用了模型/是否降级；局部上下文不等于已脱敏 |
| F1 | P2 | 大结果的 DOM 与会话存储成本需要测量和限制 | `IssueList.vue:64-70,147` 全量渲染并扫描节点；`WorkspaceView.vue:1237-1261` 深度监听；`useWorkspaceSession.ts:236-248` 全量同步序列化 | 问题多或频繁选择时可能占用主线程；目前是结构风险，不把单元测试耗时当作浏览器性能结论 |
| M1 | P2 | 大模块与兼容层类型豁免提高维护成本 | `pdf_parser.py` 3116 行，`useVerificationWorkspace.ts` 2712 行，`WorkspaceView.vue` 1686 行；多个 `compatibility/*.py` 顶部有 `mypy: ignore-errors` | 一次小变更跨越较多职责；“mypy 通过”不能证明这些豁免内部有同等类型保障 |
| D1 | P1 | 格线表格内的中文片段可能加空格或逆序，已用内存样本复现 | `document_processing/image_tables.py:99-105` 直接按 y/x 排序并用空格拼接；普通路径 `layout.py:950-952` 的语言连接不同 | “测试”可能变成“测 试”，轻微 y 抖动时可能变成“试 测”；规范偏移校验无法发现内容已被错误组合 |
| D2 | P1 | 有效 CMYK JPEG 会漏图片区域或导出失败，已复现 | `image_validation.py:75-95` 保留 CMYK；`image_regions.py:49-55` 只取前三通道；`exporters/docx_reconstruction.py:364-372` 保留原颜色空间转 PNG | 只在 K 通道出现的黑图形漏检；裁切导出可报 unsupported colorspace |
| D3 | P1 | 独立图片 OCR 未复用 PDF 的输出规范化，已复现 | `image_parser.py:105-117` 对比 `pdf_parser.py:383-461` | 0 置信度、越界框、重复框仍可进入正文；偏移自洽不等于来源可信 |
| D4 | P1 | 区域检测中间内存显著超过解码预算，已测量，未证明生产 OOM | `image_regions.py:49-56` 的 median 使减法提升为 float64 | 1000×600 RGB 的已解码数据 1.8MB，检测阶段 traced peak 约 35.4MB；15MP 单个 RGB float64 中间数组即 360MB |
| D5 | P1 | 损坏/替换后的超大产物在拒绝前被完整散列，已用模拟 FD 复现 | `infrastructure/artifact_storage.py:383-384,1025-1050` | 预期/上限 4B 的产物被替换为 3MiB 后，读取全文件才拒绝；完整性未失守，但 I/O 预算未提前生效 |
| D6 | P1，旧功能对齐 | 扫描 PDF 与独立图片能力仍不等价，源码确认 | `pdf_parser.py:227-231,2427-2437`；旧 `pdf_processor.py:284-300` | 扫描 PDF 未接入新格线/区域检测，整页扫描图可能与可编辑 OCR 正文同时输出 |
| D7 | P2 | DOCX 保留结构不等于保留表格外观/物理尺寸，部分已复现 | `exporters/docx_reconstruction.py:1005-1034,1391-1395`；旧 `word_builder.py:117-119` | 新表格没有 Table Grid 边框；图像使用 pixels/96，单独修复字号 DPI 并未还原图像尺寸或页面几何 |

上述路径未写完整前缀时：Python 文件位于 `apps/api/src/text_verification`，Vue/TS 文件位于 `apps/web/src`。

### 浏览器布局实测

测量使用全新 Chromium 页面、合成文件以及拦截的 API/SSE，不创建真实任务。单位为 CSS 像素，不等同于截图的物理像素。

| 场景 | 视口 | 页面内容高度 | 超出视口 | 开始按钮底部 |
| --- | --- | --- | --- | --- |
| 文件已选 | 1366×768 | 904 | 136 | 804，未完整在首屏 |
| 文件已选 | 1280×720 | 904 | 184 | 804，未完整在首屏 |
| 文件已选 | 1920×1080 | 1080 | 0 | 804 |
| 排队/执行布局 | 1366×768 | 1204 | 436 | 进度区继续追加在按钮后 |
| 排队/执行布局 | 1920×1080 | 1204 | 124 | 仍产生整页滚动 |

当前进度区自身约 264px 高；单纯把整页设置成 `overflow: hidden` 会隐藏信息，不是修复。

执行中刷新复现：刷新前存在进度区、`sessionStorage` 无任务记录；刷新后进度区和已选文件均消失。

### 本轮代码基线

- 后端：1202 passed、86 skipped；跳过项依赖真实 PostgreSQL 或运行中的 API/Worker。本轮明确不启动 Worker。
- 前端：568 passed；现有构建通过。后端 Ruff/mypy 通过，但兼容层存在显式检查豁免。
- 这些基线说明回归保护已有基础，不代表完成生产容量、安全或真实多进程升级验收。
- 文档审查另以合成/内存样本确认了 D1–D5。D4 使用 `tracemalloc`，不等于进程 RSS，也不应把它线性外推成已发生的生产 OOM。
- 前次增量整合已有可用能力，但不能据此宣称与旧项目的全部扫描 PDF/版式行为等价；D6/D7 是需要补齐或明确解释的实际边界。

### 服务状态快照

收尾时的只读进程检查发现 verification Worker（PID 13436）与 maintenance Worker（PID 13435/13445），启动时间均显示为 2026-09-08 14:58:12（主机时间）。本轮没有启动或停止它们，也没有据此向真实服务提交测试任务。进程存在不代表处理就绪；其托管来源和是否应停止需独立确认，不能沿用此前“两个会话命令已停止”作为当前停机结论。

## 3. 单屏工作台设计与量化验收

### 状态分层

| 状态 | 主区域 | 常驻操作 | 滚动策略 |
| --- | --- | --- | --- |
| 尚未选文件 | 紧凑标题 + 上传/文本切换 + 中等上传区域 | 场景、设置、开始检查 | 常见桌面视口无整页滚动 |
| 文件已选 | 文件摘要行替代大上传区域；保留更换/移除 | 场景与开始按钮同一操作区 | 长文件名截断展示，完整名称可访问 |
| 排队/检查 | 文件摘要 + 1 条紧凑进度 + 当前阶段/耗时 | 服务状态、重新连接；不伪装提供后端尚无的取消功能 | 不再追加完整调试面板 |
| 审阅 | 左侧文档、右侧问题；顶部精简摘要与导出 | 当前选中项操作、筛选、查找 | 正文/问题各自滚动，页面框架不随定位跳动 |
| 设置/错误 | 设置沿用抽屉；长错误详情按需展开 | 关闭、返回、复制诊断编号 | 抽屉内部滚动；低高度允许页面回流 |

### 桌面验收目标

- 1280×720、1366×768、1440×900、1920×1080，100% 字号/缩放。
- 空闲、已选文件、排队、检查、简短错误、结果六种状态：`documentElement.scrollHeight <= innerHeight + 1`。
- 主操作按钮完整位于视口内，不依赖点击时浏览器自动滚动。
- 文件已选/处理状态的上传占位高度目标 64–96px；进度摘要目标 56–88px。数值是初始设计预算，不用来裁切长错误。
- 正文和问题定位保持 `window.scrollY` 不变，目标项在其面板内可见。
- 200% 字体/浏览器缩放、320px 窄视口和手机横屏：允许垂直回流，不隐藏按钮、不出现非必要的水平整页滚动。
- 不使用 `transform: scale()` 缩小整页，不靠减小可读字号凑单屏。

建议框架：头部使用自然高度，主体使用 `minmax(0, 1fr)`；固定高度预算只用于可容纳内容的桌面布局。保留现有段落阅读样式、焦点与 `revealWithinPane`。

## 4. 实施顺序与依赖

| 阶段 | 任务 | 交付物 | 依赖 | 初步工作量 |
| --- | --- | --- | --- | --- |
| A：先解决日常使用 | T1 单屏布局与进度；T2 执行恢复；T3 Worker 协议/就绪；T8 救援闭环 | 不用下拉找按钮；状态可信；刷新可续接；异常任务不会阻断救援 | T1 可先做；T2/T3 接口需对齐，T8 可独立修复 | 6–10 工程日 |
| B：范围与交付可控 | T4 中英文范围；T5 CI/部署；T6 云复核边界；T9 异步路由阻塞隔离 | 去掉多余语言、升级有门禁、云处理显式可见、慢操作不阻塞其他请求 | T4/T6 的协议变化依赖 T3；T5 跨阶段提供回归 | 4–7 工程日 |
| C：文档正确性与资源边界 | T10 CMYK；T11 OCR/表格文本；T12 内存；T13 产物 I/O；T15 扫描 PDF | 合法图片可处理，正文不因分组改错，资源预算覆盖实际工作，旧扫描能力补齐 | 可与 A/B 并行；T12 的预算接口先于 T10，T15 依赖 T10–T12 | 4–8 工程日 |
| D：表现与长期维护 | T7 前端性能/模块；T14 DOCX 外观 | 有测量的交互优化和可解释的重建样式 | 按样本与性能基线决定深度 | 测量后分批估算 |

工作量是假设熟悉仓库的一名工程师的初估，不是交付承诺，不包含全新多租户体系或像素级排版引擎。T1 优先交付，A/C 的可靠性与正确性修复分批推进；C 不是可忽略的长期重构，宣称旧功能已全部覆盖前必须补齐。D 的优化深度再由测量决定。

## 5. 可独立验收的实施任务

### T1：单屏布局、紧凑进度与一致中文状态

**Files**
- Modify: `apps/web/src/components/workspace/WorkspaceSetup.vue`
- Modify: `apps/web/src/components/workspace/SourceInputPanel.vue`
- Modify: `apps/web/src/components/JobProgress.vue`
- Modify: `apps/web/src/views/WorkspaceView.vue`
- Create: `apps/web/src/utils/jobPresentation.ts`
- Test: `apps/web/tests/JobProgress.spec.ts`（新）、`tests/SourceInputPanel.spec.ts`、`tests/e2e/workspace-lifecycle.spec.ts`

**Interfaces**
- 消费现有 `JobStatus`、`JobProgressStage`，服务端状态枚举不改。
- 提供 `jobStatusLabel(status: JobStatus): string`、`jobStageLabel(stage: JobProgressStage): string`。
- `WorkspaceSetup`/`SourceInputPanel` 新增可选 `jobStatus?: JobStatus`；`busy` 仍作为禁止重复提交的依据，不再用它推断具体阶段。

- [ ] 在现有 E2E 中增加 720/768 高度的空闲、选文件、排队和错误用例；沿用合成结果与 route fixture。

```typescript
await expect(page.locator('[data-submit-source]')).toBeInViewport({ ratio: 1 })
expect(await page.evaluate(
  () => document.documentElement.scrollHeight - window.innerHeight
)).toBeLessThanOrEqual(1)
```

- [ ] 先运行 `npm --prefix apps/web run test:e2e -- --grep "single-screen"`，确认当前布局失败。
- [ ] 以选中文件和执行状态切换紧凑区域，不同时显示完整拖放区、文件详情和完整进度清单。使用状态映射替换英文，排队显示“等待处理”，识别显示“OCR 识别中”，完成显示“检查完成”。
- [ ] 将场景、设置入口、主要按钮组合为操作区；错误详情可展开。保留手机端文档/问题切换、键盘焦点、可访问文件名及抽屉滚动。
- [ ] 运行 `npm --prefix apps/web test -- tests/SourceInputPanel.spec.ts tests/JobProgress.spec.ts tests/WorkspaceView.spec.ts tests/WorkspaceAccessibility.spec.ts`，再运行对应 E2E 与 `npm --prefix apps/web run build`。

**Acceptance:** 达到第 3 节布局标准；排队和“正在检查”不再互相矛盾；UI 不展示 `Terminal state retained` 等内部调试文本。

### T2：执行中的任务续接、断线恢复与请求生命周期

**Files**
- Modify: `apps/web/src/api/jobs.ts`、`apps/web/src/api/verification.ts`
- Modify: `apps/web/src/composables/useVerificationExecution.ts`
- Modify: `apps/web/src/views/WorkspaceView.vue`
- Create: `apps/web/src/composables/usePendingJobSession.ts`
- Test: `apps/web/tests/useVerificationExecution.spec.ts`、`tests/jobsApi.spec.ts`、`tests/WorkspaceSession.spec.ts`、`tests/e2e/workspace-lifecycle.spec.ts`

**Interfaces**
- `JobsApi.getJob(jobId: string, signal?: AbortSignal): Promise<JobRead>` 对接现有 GET job 接口。
- `useVerificationExecution.resumeJob(jobId: string): Promise<void>` 只恢复已有任务，不重新 POST 文件。
- 独立、版本化的 pending 记录只保存 `{version: 1, jobId, sourceName, createdAt, expiresAt}`；不保存文件字节或文档全文。记录键与已完成审阅会话分开。

- [ ] 在 `useVerificationExecution.spec.ts` 复用现有 `buildJob`/`buildResult`/deferred harness：排队中刷新后 GET 原 job；完成则取结果，未完成则订阅 SSE，410 则明确过期；断言 POST job 仅调用一次。

新增接口的起始回归用例（放在现有测试文件内，使用其 imports 和 `buildJob`）：

```typescript
it('resumes an accepted job without uploading again', async () => {
  const job = buildJob({
    created_at: new Date(Date.now() - 60_000).toISOString(),
    expires_at: new Date(Date.now() + 86_400_000).toISOString()
  })
  const api: JobsApi = {
    createJob: vi.fn(),
    getJob: vi.fn().mockResolvedValue(job),
    getResult: vi.fn(),
    subscribe: vi.fn(() => () => {})
  }
  const execution = useVerificationExecution({ jobsApi: api, fileExecutionMode: 'jobs' })
  await execution.resumeJob(job.job_id)
  expect(api.getJob).toHaveBeenCalled()
  expect(api.createJob).not.toHaveBeenCalled()
  expect(execution.jobId.value).toBe(job.job_id)
  expect(api.subscribe).toHaveBeenCalled()
  execution.dispose()
})
```

- [ ] 增加请求 abort 与代次隔离用例：本地停止等待或卸载时中止请求；迟到响应不能覆盖下一次请求。
- [ ] 为 pending 元数据加入严格 UUID/日期/大小校验，成功接回、过期和用户明确放弃后清理；结果会话仍使用既有原子恢复与字节预算校验。
- [ ] 短暂 SSE 断线保留状态；连续无进展后先 GET 当前状态再提示恢复入口。退避轮询只作为短期回退，最多 30 秒一次，切回 SSE/隐藏页面时停止无意义的高频请求。
- [ ] 将上传、结果获取、导出等待分别设定可解释的期限；不能给所有操作套同一个极短超时。客户端“停止等待”不宣称已取消服务端任务。
- [ ] 运行 `npm --prefix apps/web test -- tests/useVerificationExecution.spec.ts tests/jobsApi.spec.ts tests/WorkspaceSession.spec.ts tests/WorkspaceTask6.spec.ts`；增加浏览器刷新与断线用例。

**Acceptance:** 刷新不丢任务入口、不重复上传；终态只加载一次；已有接受/忽略、撤销和导出授权不被 pending 记录覆盖。

### T3：Worker 协议兼容、处理就绪与停滞诊断

**Files**
- Modify: `apps/api/src/text_verification/domain/verification.py`
- Modify: `apps/api/src/text_verification/workers/celery_app.py`、`workers/worker_cli.py`、`workers/tasks.py`
- Modify: `apps/api/src/text_verification/api/routes/health.py`、`api/routes/jobs.py`
- Create: `apps/api/src/text_verification/application/processing_readiness.py`
- Test: `apps/api/tests/integration/test_health.py`、`tests/integration/test_pipeline_task.py`、`tests/integration/test_create_job.py`、`tests/unit/domain/test_verification_options.py`

**Interfaces**
- `/health` 保留轻量存活语义；新增 `/api/v1/readiness`。
- readiness 响应仅包含 `{ready, protocol_version, checks, reason_code}`，不暴露密钥、连接字符串和用户文档。
- 协议能力通过 Worker 注册/后台采样缓存获得；禁止在每个 HTTP 请求里串行广播 inspect。
- 版本号不能直接塞入旧 `extra="forbid"` 的选项 JSON；使用独立的任务协议元数据或版本化消息封套，并保留旧 payload 读取入口。
- 新模块提供 `get_processing_readiness() -> ProcessingReadiness`；`ProcessingReadiness` 包含 `ready: bool`、`protocol_version: int`、`checks: dict[str, bool]`、`reason_code: str | None`。HTTP handler 的响应状态由 `ready` 决定。

- [ ] 固化本次失败路径：新选项 + 旧读取器，在领取租约前失败；断言兼容性失败可被识别，不能只有 Celery FAILURE 而 job 永久 queued。

无消费者的接口回归应使用缓存结果替身，不依赖真实广播：

```python
def test_readiness_reports_missing_consumer(client, monkeypatch):
    from text_verification.api.routes import health as health_routes
    from text_verification.application.processing_readiness import ProcessingReadiness

    state = ProcessingReadiness(
        ready=False,
        protocol_version=1,
        checks={"database": True, "broker": True, "consumer": False},
        reason_code="worker_unavailable",
    )
    monkeypatch.setattr(health_routes, "get_processing_readiness", lambda: state)
    response = client.get("/api/v1/readiness")
    assert response.status_code == 503
    assert response.json()["reason_code"] == "worker_unavailable"
    assert client.get("/api/v1/health").status_code == 200
```

- [ ] 定义受支持协议与能力集合，覆盖默认选项、扩展规则、OCR 语言、图片输入。先部署兼容 Worker，再部署生产者；不兼容消息不能进入旧消费者。
- [ ] readiness 区分数据库/Redis不可达、没有消费者、协议不匹配、OCR模型缺失。运行中的长任务不等于 Worker 离线；缓存/心跳超时必须覆盖实际执行模型，特别是本地 solo 调试模式。
- [ ] 对新请求返回可解释、可重试的 unavailable 状态；若选择允许离线排队，必须在 UI 明示，并设置最长排队告警，而不是把它标成检查中。已接受任务保留现有租约与救援语义。
- [ ] 最小诊断包含 job_id、阶段、排队时长、最近事件、协议版本和错误代码；不记录原文、词库内容或授权 token。
- [ ] 运行相关 pytest；在隔离服务栈增加旧 Worker/新 API、零 Worker、正常 Worker 三种协议组合。运行服务需实施阶段明确批准。

**Acceptance:** “API 健康但没有可用处理能力”不再误导用户；版本不兼容产生可诊断结果；本次 queued/0% 事故能被自动化复现与防止。

### T4：收敛到中英文，并安全退役日文选项

**Files**
- Modify: `apps/web/src/types/verification.ts`、`src/api/analyzeOptions.ts`
- Modify: `apps/web/src/components/workspace/VerificationSettings.vue`、`WorkspaceSetup.vue`、`HelpDialog.vue`
- Modify: `apps/web/src/composables/useWorkspaceSession.ts`
- Modify: `apps/api/src/text_verification/domain/verification.py`、`document_processing/ocr_provider.py`、相关请求解析
- Modify: `README.md`
- Test: `apps/web/tests/analyzeOptions.spec.ts`、`tests/VerificationSettings.spec.ts`、`tests/WorkspaceSession.spec.ts`；后端 options/provider/request tests

**Interfaces**
- 新请求 OCR 语言仅 `zh | en`；默认中英文识别。
- 既有 `ja` 数据作为旧版本只读数据处理：查看/导出不需要重新 OCR；重新检查前要求明确改选。
- 不把 `ja` 静默替换为 `zh`，不因此删除已保存会话或使旧任务 GET 报错。

- [ ] 增加新请求拒绝 `ja`、UI 没有日文选项、旧结果仍可查看/导出、旧会话提示改选的用例。

首先替换当前 `VerificationSettings.spec.ts` 的日文选择用例：

```typescript
it('offers only bilingual and English OCR for new checks', () => {
  const wrapper = mount(VerificationSettings, { props: { options: buildOptions() } })
  expect(wrapper.findAll('select[aria-label="OCR 识别语言"] option').map(
    option => option.attributes('value')
  )).toEqual(['zh', 'en'])
})
```

- [ ] 分开“新请求允许值”和“历史数据读取兼容”；与 T3 协议版本一起发布。
- [ ] 删除日文 UI、模型初始化分支与对应文案；保留有解释的旧数据迁移入口。
- [ ] 重新覆盖 65,536 字节边界；新增字段与默认值不得再次使旧会话失效。
- [ ] 运行对应前后端测试及前端构建。

**Acceptance:** 用户只看到中英文 OCR；已有审阅和导出不因范围收缩丢失。

### T5：真实链路 CI、可重复部署与服务所有权

**Files**
- Create: `.github/workflows/verification.yml`
- Create: `apps/api/constraints-linux-py312.txt`（由受控 Linux 构建环境生成）
- Modify: `apps/api/Dockerfile`、`infra/compose.yaml`、`README.md`
- Test: `apps/api/tests/integration/test_docker_configuration.py`、`tests/e2e/test_upload_lifecycle.py`、`tests/e2e/test_scanned_pdf_lifecycle.py`
- Test: `apps/web/tests/e2e/workspace-lifecycle.spec.ts`

**Interfaces**
- CI 使用独立 Compose 项目名、数据库、存储卷；不连接开发者现有数据库。
- runtime/verification test 镜像分层；同一发布版本的 API、普通 Worker、维护 Worker 使用同一后端镜像标识。
- CLI 不作为业务服务托管器。服务启停通过明确的终端/Compose 生命周期管理，不借助广泛的 `pkill`/`killall`。

- [ ] 保留单元任务，增加 PostgreSQL 迁移/事务任务、真实 API+Worker 任务、前端 mock E2E 和真实入口冒烟任务；发布所需任务缺环境时失败，不“跳过后视为通过”。
- [ ] 将端到端最小矩阵固定为 TXT/DOCX/PNG、扫描 PDF、修订导出、任务刷新恢复、失效/过期处理；只使用合成内容。
- [ ] 在受控 Linux/Python 3.12 中固定依赖和基础镜像标识，区分生产与 dev 依赖；不要把 macOS 本地 `pip freeze` 直接当 Linux 发布锁。
- [ ] 把 OCR 模型预取/缓存校验加入镜像或部署准备，运行阶段缺模型返回明确错误；首个用户任务不应承担不可控的下载等待。
- [ ] CI 固定调用现有命令，并使 live 环境变量只存在于测试进程：

```bash
python3.12 -m venv apps/api/.venv
apps/api/.venv/bin/python -m pip install \
  -c apps/api/constraints-linux-py312.txt -e "apps/api[dev,ocr]"
cd apps/api
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src/text_verification
cd ../..
npm --prefix apps/web ci
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/web run test:e2e
```

- [ ] 发布文档写明：先启动兼容 Worker/维护 Worker，再发布 API；检测队列/协议能力，最后切换流量。停止检查服务时 UI 必须体现 unavailable，不自动拉起用户已停止的服务。

**Acceptance:** 空白受控环境可重建同一版本；真实链路门禁不能以 skips 通过；服务不依附 AI 会话生命周期。

### T6：云复核显式控制、降级展示与原始规则证据

**Files**
- Modify: `apps/api/src/text_verification/compatibility/llm_review.py`
- Modify: `apps/api/src/text_verification/config.py`、`application/factory.py`、`domain/verification.py`
- Modify: `apps/web/src/components/workspace/VerificationSettings.vue`、`PrivacyDialog.vue`、`WorkspaceView.vue`
- Test: `apps/api/tests/unit/compatibility/test_llm_review.py`、`apps/web/tests/VerificationSettings.spec.ts`、`tests/WorkspaceView.spec.ts`

**Interfaces**
- 新的每任务复核策略必须依赖 T3 的协议兼容发布；默认本地规则。
- 工作台展示现有 `analysis_mode`、`degradation`，不新增一套与后端相冲突的推断状态。
- 提供策略控制、上下文脱敏/截断和总请求预算；不把“截取局部”表述为“已经脱敏”。
- 后端新请求字段 `cloud_review_enabled: bool = False`，前端选项 `enableCloudReview?: boolean`；`review_issues` 增加 keyword-only `allow_cloud: bool = False`，由 factory 同时检查任务授权与管理员供应商配置。历史请求不因环境中有密钥就被视为已授权。

- [ ] 使用 mock 模型增加用例：未授权不调用；上下文内模拟邮箱/凭证不外发；供应商超时/异常保留本地问题；模型返回不能改写偏移/自动接受修订。

在现有 `test_llm_review.py` 使用其 `_review_candidate`：

```python
def test_configured_provider_is_not_called_without_task_consent(monkeypatch):
    def unexpected_client(**kwargs):
        raise AssertionError("cloud client must not be constructed")

    monkeypatch.setattr(llm_review, "OpenAI", unexpected_client)
    original = [_review_candidate()]
    actual, stats = llm_review.review_issues(
        Settings(llm_api_key="synthetic-test-only"),
        "中文，，文本",
        original,
        allow_cloud=False,
    )
    assert actual == original
    assert stats["performed"] is False
    assert stats["failed"] is False
```

- [ ] 在 UI 显式显示“本地规则 / 已启用语义复核 / 已降级”，并提供面向本次任务的选择与说明。
- [ ] 把模型判为误报的规则证据保留为可审计信息，而不是只有删除后的问题列表；复核不能替代人的最终判断。
- [ ] 设置总耗时、输入/输出大小和重试预算；校验模型 verdict 的索引、重复条目、缺失结果和原因长度。
- [ ] 运行 `cd apps/api && .venv/bin/pytest -q tests/unit/compatibility/test_llm_review.py`，再运行对应 UI 测试；禁止通过真实外部模型处理用户样本来验证。

**Acceptance:** 用户知道本次处理模式；未授权不会外发；故障降级可见且不丢规则证据。

### T7：先测量，再优化长结果与模块边界

**Files**
- Modify: `apps/web/src/components/workspace/IssueList.vue`
- Modify: `apps/web/src/composables/useWorkspaceSession.ts`、`useVerificationWorkspace.ts`
- Modify: `apps/web/src/views/WorkspaceView.vue`
- Test: `apps/web/tests/IssueNavigation.spec.ts`、`WorkspaceSession.spec.ts`、`useVerificationWorkspace.spec.ts`
- Test: `apps/web/tests/e2e/workspace-lifecycle.spec.ts`
- 后端拆分范围由 T10–T15 和具体变更确定，不按行数一次性重构。

**Interfaces**
- 优化不得改变 `issue_id`、代码点偏移、接受/忽略语义、撤销顺序或导出身份。
- 只在量化证据支持时采用窗口化列表；定位函数必须先确保目标条目已挂载，再滚动/聚焦。
- 会话保存区分轻量 UI 状态与正文/修订；保留显式 flush，避免 debounce 导致关闭页面丢最后一次操作。

- [ ] 使用 1千、1万问题及长正文建立 Chromium 基线：渲染节点数、选择/筛选/撤销 p95、序列化耗时、长任务和内存峰值；记录设备与模式。
- [ ] 优先消除每次选择对全部节点的扫描，批量保存同一轮状态；不要先换框架或大改全局状态。
- [ ] 若 1万问题交互 p95 超过 200ms，则引入有界窗口/分页策略，保留定位、筛选、当前项、无障碍和批量操作全量语义。

在生成 1万问题的 browser fixture 后，窗口化方案至少增加以下结构验收；若选择分页，相同断言针对当前页执行：

```typescript
expect(await page.locator('.issue-card').count()).toBeLessThanOrEqual(200)
const pageScroll = await page.evaluate(() => window.scrollY)
await page.locator('[data-issue-role="list"]').first().click()
await expect(page.locator('.issue-select[aria-current="true"]')).toBeInViewport()
expect(await page.evaluate(() => window.scrollY)).toBe(pageScroll)
```

- [ ] 未识别版本/异常会话先隔离并提示，不静默丢弃用户编辑；隔离机制同样受存储上限约束，不复制无限大坏载荷。
- [ ] 按现有职责逐步提取导出控制、会话迁移和选项校验；每次仅抽取一条可独立回归的路径。逐模块收紧兼容层类型豁免。
- [ ] 运行对应单元和浏览器用例；将新性能数据与第一步基线比较，不用“文件变短”作为成功标准。

**Acceptance:** 交互达到已记录目标且没有撤销/恢复/定位退化；未证明的后端热点保留为测量工作，不伪报性能缺陷。

### T8：救援批次错误隔离与发布后确认闭环

**Files**
- Modify: `apps/api/src/text_verification/domain/jobs.py`
- Modify: `apps/api/src/text_verification/infrastructure/repositories.py`
- Modify: `apps/api/src/text_verification/workers/tasks.py`
- Test: `apps/api/tests/integration/test_job_leases.py`
- Test: `apps/api/tests/integration/test_pipeline_task.py`

**Interfaces**
- `JobRecoveryClaim` 改为只携带 `job_id: UUID`、`kind: JobRecoveryKind`、`attempt: int`、`publication_due_at: datetime`；不要求先读取 `VerificationOptions` 才能调度救援。
- 处理领取也区分租约元数据与完整业务选项。选项无法解码时，有独立且同样受租约约束的失败记录路径；不能为了写失败状态再走同一个会失败的完整解码。
- `rescue_last_published_at` 表示“已发布”，不是“已领取”。引入有界的领取确认等待，例如初始 120 秒；过期重投递仍需满足无有效租约、非终态、未过保留期和次数预算。

- [ ] 在现有 PostgreSQL 隔离 schema 测试中构造正常 A 与不可读 B 两条记录；断言 B 不阻断 A 的救援/发布，不允许整批因业务选项反序列化而回滚。
- [ ] 扩展当前 `test_job_leases.py:815-862` 的“一小时后仍抑制发布”用例，将预期改为经过确认窗口后有界恢复；确认窗口内不重复投递。

```python
# 接续既有测试完成 mark_recovery_published 后、尚未 acquire_lease 的状态。
after_ack_window = publication_due_at + timedelta(seconds=1)
claims = repository.claim_due_recoveries(
    now=after_ack_window,
    publication_due_at=after_ack_window + timedelta(seconds=120),
    limit=100,
)
assert [claim.job_id for claim in claims] == [job_id]
```

- [ ] 增加发布成功后消息丢失、Worker 领取前失败、两维护进程并发扫描和旧 Worker 晚到确认的用例。使用 attempt/租约条件更新，避免晚到确认覆盖新的恢复轮次。
- [ ] 保留 `FOR UPDATE SKIP LOCKED`、owner token、重试退避和结果复用；限定重投递次数，超出预算时写可诊断状态并提示人工处理，不能无上限放大队列。
- [ ] 运行 `cd apps/api && .venv/bin/pytest -q tests/integration/test_job_leases.py tests/integration/test_pipeline_task.py`。真实数据库测试必须在 T5 的隔离环境执行，不指向当前用户数据库。

**Acceptance:** 一条坏记录不阻断整批；发布成功但未领取的任务有有限次、可观察的恢复机会；已领取/已完成任务不被重复执行。

### T9：把同步数据库与复检工作移出事件循环

**Files**
- Modify: `apps/api/src/text_verification/api/routes/jobs.py`
- Modify: `apps/api/src/text_verification/api/dependencies.py`（仅当需调整 Session 创建边界）
- Test: `apps/api/tests/integration/test_job_progress.py`
- Test: `apps/api/tests/integration/test_job_recheck_routes.py`

**Interfaces**
- 保留现有 HTTP/SSE 协议、序列号、终态关闭、keepalive 和重新检查授权。
- 第一批使用已有 Starlette 线程池桥接，不同时引入 async SQLAlchemy 和新任务协议。
- Session 的创建、访问、关闭在同一次同步调用内完成；不跨线程共享 request-scoped Session。

- [ ] 为慢 `_poll_job_state` 和慢复检分别增加并发响应测试：阻塞点用受控 Event 放行，另一条 health 请求须在阻塞放行前完成；不只断言最终响应内容。
- [ ] 将 SSE 单次同步操作整体桥接：

```python
from starlette.concurrency import run_in_threadpool

events, job = await run_in_threadpool(
    _poll_job_state, session_factory, job_id, after_sequence
)
```

- [ ] 对 `service.recheck` 同样检查服务/Session 的生命周期后桥接完整同步单元；不要只把中间 SQL 调用切到另一个线程。限制线程池并发和排队，长 CPU 复检是否异步化另以数据决定。
- [ ] 运行 `cd apps/api && .venv/bin/pytest -q tests/integration/test_job_progress.py tests/integration/test_job_recheck_routes.py`，确认结果授权、断线、重放和终态行为不变。

**Acceptance:** 慢数据库查询或一次复检不会直接占住 API 事件循环；取消连接不泄漏 Session；不得把桥接线程池描述为无限并发能力。

### T10：统一 CMYK/灰度/RGB 图片处理与裁切导出

**Files**
- Modify: `apps/api/src/text_verification/document_processing/image_validation.py`
- Modify: `apps/api/src/text_verification/document_processing/image_regions.py`、`image_tables.py`
- Modify: `apps/api/src/text_verification/exporters/docx_reconstruction.py`
- Test: `apps/api/tests/integration/test_image_parser.py`、`test_docx_reconstruction.py`

**Interfaces**
- 所有栅格分析消费经过明确颜色空间转换的 RGB/灰度像素，不把 CMYK 的前三通道当 RGB。
- `source_version` 始终取原上传字节；颜色空间转换产物只用于计算/重建，不能改变源文件身份。
- 裁切编码 PNG 前同样规范化颜色空间；透明背景策略显式定义并保持一致。

- [ ] 在现有 `test_docx_reconstruction.py` 复用其 resolver 和 OCR 替身加入 CMYK 回归：

```python
def test_cmyk_black_region_survives_docx_reconstruction(tmp_path):
    source = tmp_path / "cmyk.jpg"
    pixels = pymupdf.Pixmap(pymupdf.csCMYK, pymupdf.IRect(0, 0, 240, 180), False)
    pixels.clear_with(0)
    pixels.set_rect(pymupdf.IRect(130, 70, 220, 160), (0, 0, 0, 255))
    source.write_bytes(pixels.tobytes("jpeg"))
    parsed = ImageParser(
        file_type=FileType.JPG,
        ocr=_FakeOcr([_ocr_box("Heading", (10, 10, 100, 35))]),
    ).parse(source)
    assert any(block.kind == "image" for block in parsed.blocks)
    target = DocxReconstructionExporter(
        anchored_source_resolver=_StaticAnchoredSourcePathResolver(source)
    ).export(parsed, tmp_path / "cmyk.docx")
    assert len(Document(target).inline_shapes) == 1
```

- [ ] 分配 RGB/alpha 转换缓冲区前计入 T12 预算；转换后检查尺寸/stride，不绕过现有头部和解码校验。
- [ ] 增加 CMYK 青色、K-only 黑色、灰度 JPEG、RGBA PNG 用例；确认裁切并非整图，颜色/尺寸合理。
- [ ] 运行 `cd apps/api && .venv/bin/pytest -q tests/integration/test_image_parser.py tests/integration/test_docx_reconstruction.py`。

**Acceptance:** 有效 CMYK JPEG 不再漏 K 通道图形或在 PNG 裁切时崩溃；源哈希、裁切边界和导出身份保持不变。

### T11：图片 OCR 与表格片段的共同规范化

**Files**
- Modify: `apps/api/src/text_verification/parsers/image_parser.py`、`parsers/pdf_parser.py`
- Modify: `apps/api/src/text_verification/document_processing/layout.py`、`image_tables.py`
- Create: `apps/api/src/text_verification/document_processing/ocr_normalization.py`
- Test: `apps/api/tests/integration/test_image_parser.py`、`test_pdf_ocr.py`
- Test: `apps/api/tests/unit/document_processing/test_layout.py`

**Interfaces**
- 提取现有 PDF 路径中的可复用规则，而非复制第二套：边界、文本预算、置信度下限和重复框处理。
- 原始图片保持像素坐标，PDF 完成其坐标变换；不把 PDF point 和 raster pixel 混用。
- layout 提供 `join_ocr_fragments(boxes: tuple[OcrLayoutBox, ...], *, language: str) -> str`，复用已有容差行分组和语言连接；格线单元格调用同一路径。

- [ ] 对独立图片复现三例：置信度为 0、框完全在图外、完全重复框；分别要求剔除/显式错误、拒绝越界、稳定合并。沿用 PDF 已定义的规则与 typed error，不凭空放宽。
- [ ] 在 `test_layout.py` 增加微小 y 抖动与中文/英文连接用例；使用当前测试文件的 OCR box 构造 helper，期望如下：

```text
语言 zh，左框“测”、右框“试”、右框比左框高 1px：测试
语言 en，左框“hello”、右框“world”、同一行：hello world
重复框文本/范围相同、置信度不同：保留最高置信度的一份
```

- [ ] 格线表格只负责确定单元格归属，不再独立决定文字阅读顺序；多行单元格保留换行，而不是仅按精确 y 排序。
- [ ] 原文、规则位置、修改和导出使用同一规范文本；校验 `document.text[start:end] == block.text`，同时校验文本本身符合夹具预期。
- [ ] 合并运行 `cd apps/api && .venv/bin/pytest -q tests/integration/test_image_parser.py tests/integration/test_pdf_ocr.py tests/unit/document_processing/test_layout.py`。

**Acceptance:** 开启格线检测不会把“测试”改为“测 试”或“试 测”；无效/重复 OCR 框不会作为有效正文进入图片结果；原 PDF 行为不退化。

### T12：给图片检测建立真实的工作内存预算

**Files**
- Modify: `apps/api/src/text_verification/document_processing/image_regions.py`、`image_tables.py`、`image_validation.py`
- Modify: `apps/api/src/text_verification/parsers/image_parser.py`
- Modify: `apps/api/src/text_verification/config.py`、`application/factory.py`（预算配置与入口传递）
- Test: `apps/api/tests/unit/document_processing/test_image_resources.py`（新）
- Test: `apps/api/tests/integration/test_image_parser.py`

**Interfaces**
- `validate_image_file` 与检测入口新增显式 `max_working_bytes` 参数，由配置/factory 统一传递；预算覆盖颜色转换、掩码和检测中间数组，不代替现有解码上限。
- 算法使用明确整数 dtype、可复用缓冲区或分块计算。不能只在内存不足后捕获 `MemoryError` 并返回空结果。

- [ ] 固化 1000×600 RGB 的合成探针，记录 traced peak 和进程 RSS 的不同含义；另增加预算不足时在大数组分配前拒绝的测试。
- [ ] 消除大数组的隐式 float64 提升。8-bit 样本中位数可能为半整数，使用两倍整数单位而非直接四舍五入，以保留原先 `> 25` 的判定；再分块限制临时数组：

```python
background_twice = (np.median(border, axis=0) * 2).astype(np.int16)
difference_twice = np.max(
    np.abs(color.astype(np.int16) * 2 - background_twice), axis=2
)
content_mask = (difference_twice > 50).astype(np.uint8) * 255
```

- [ ] 对高分辨率输入分块计算差异/掩码；把最多同时活跃的缓冲区计入预估，限制不同检测阶段重叠占用。
- [ ] 初始优化目标：同一 1000×600 探针 traced peak 从约 35.4MB 降至不超过 12MiB；这不是全进程 RSS 上限。最大允许尺寸、两任务并发的 RSS 另在隔离环境实测并配置预算。
- [ ] 运行新资源用例与图片解析/裁切回归，确认图形边界、表格和文字遮罩没有改变。

**Acceptance:** 上限覆盖工作内存而不仅是输入；超预算明确拒绝；不得出现成功但无图形的隐式降级。

### T13：产物完整性检查先限大小，再做有界散列

**Files**
- Modify: `apps/api/src/text_verification/infrastructure/artifact_storage.py`
- Test: `apps/api/tests/unit/infrastructure/test_storage.py`
- Test: `apps/api/tests/unit/application/test_artifact_service.py`

**Interfaces**
- `_hash_stable_file(descriptor: int, *, max_bytes: int, expected_size: int | None = None)` 保留原返回值。
- 有 reservation 的读取按预期大小和配置上限取更严格的约束；所有调用点传入适当预算。
- 不删除现有 regular-file/no-follow/inode/时间戳/散列验证。

- [ ] 增加模拟 FD 测试：预期 4B、配置上限 4B、`fstat` 为 3MiB，断言 `os.read` 在拒绝前一次也未调用。
- [ ] 在 fstat 后立即拒绝超限/预期大小不符；散列过程中维护已读计数，处理检查后文件增长；最后仍做稳定性比较。
- [ ] 对短读、同大小内容替换、散列途中增长、目录/软链接替换和 reconciliation 继续回归。
- [ ] 运行 `cd apps/api && .venv/bin/pytest -q tests/unit/infrastructure/test_storage.py tests/unit/application/test_artifact_service.py`。

**Acceptance:** 异常超大文件不会在拒绝前被全量读取；完整性和 TOCTOU 防护不降低。

### T14：明确 OCR 重建的表格外观和物理尺寸

**Files**
- Modify: `apps/api/src/text_verification/exporters/docx_reconstruction.py`
- Modify: `apps/api/src/text_verification/parsers/image_parser.py`（仅增加有界来源尺寸元数据）
- Test: `apps/api/tests/integration/test_docx_reconstruction.py`
- Modify: `README.md`

**Interfaces**
- OCR 重建表格使用可见网格的标准样式；不要将该样式强行覆盖有明确原始样式的原格式导出。
- 图像来源 DPI/物理尺寸使用既有有界 `source_locator/style` 元数据承载；缺失时使用说明清晰的默认值。

- [ ] 对现有 2×2 含空单元格夹具断言边框可见；DOCX XML 中须有明确表格样式或边框定义，不能只检查单元格数量。
- [ ] 对 72/96/300 DPI 图像明确自然尺寸和页面内容宽度裁限规则；增加页宽与图像宽度断言。
- [ ] 文档描述区分“可编辑结构重建”“原格式修订导出”和“像素级还原”；本项目不承诺最后一种。
- [ ] 运行 `cd apps/api && .venv/bin/pytest -q tests/integration/test_docx_reconstruction.py tests/integration/test_job_reconstruction_export.py`。

**Acceptance:** OCR 表格不再无解释地丢网格；字号与图片缩放的单位一致可解释；不破坏原格式导出。

### T15：补齐扫描 PDF 的格线与非文字区域路径

**Files**
- Modify: `apps/api/src/text_verification/parsers/pdf_parser.py`
- Modify: `apps/api/src/text_verification/document_processing/image_tables.py`、`image_regions.py`
- Modify: `apps/api/src/text_verification/exporters/docx_reconstruction.py`
- Test: `apps/api/tests/integration/test_pdf_ocr.py`、`test_docx_reconstruction.py`
- Test: `apps/api/tests/e2e/test_scanned_pdf_lifecycle.py`

**Interfaces**
- 在已经通过像素预算检查的页面 raster 上复用 T10–T12 的检测与规范化，再统一映射到 PDF 页面坐标。
- 新区域引用只包含经过验证的页码、有限坐标、固定渲染参数及来源类型；禁止内嵌 base64、任意路径或把整页扫描图当作图形裁切替代。
- 纯扫描页与 mixed/native 页明确分支：只移除被可编辑 OCR 取代的整页扫描底图，不删除真正的原生插图。
- 重建仍使用原 PDF 的 source hash 与 anchored resolver，不以渲染后图片 hash 替代 PDF 身份。

- [ ] 使用合成扫描 PDF：文字 + 2×2 表格（含空格）+ 单独图形；断言文档正文无重复，DOCX 中表格可编辑，media 是图形区域而非含全部正文的整页扫描。
- [ ] 增加旋转页、不同 DPI、纯文本 PDF、mixed 页、低置信度和重复 OCR 夹具；明确失败时的 typed error/可解释提示。
- [ ] 统一复用检测，不复制另一套算法；导出时按同一受限渲染合同解析区域引用，验证坐标、源哈希及 aggregate image budget。
- [ ] 运行对应解析/导出用例；真实 OCR lifecycle 只在 T5 隔离环境按批准流程运行。

**Acceptance:** 独立图片与扫描 PDF 共享已实现的结构检测能力；不再把“保留整页扫描图 + 再写一遍 OCR 文字”作为等价的可编辑重建。

## 6. 发布前额外边界

- 当前本机/内网单用户形态与多人企业服务不是同一部署等级。扩大访问范围前，需明确入口认证、任务归属、角色、审计与保留策略；不能把 UUID 或 CORS 当作用户授权。
- 开发 Compose 的本机绑定、默认账号、测试环境变量不能直接成为对外发布配置。
- 不在本计划中擅自引入多租户、Kubernetes、微服务、GPU OCR 或新的 AI 引擎。没有使用规模与精度数据前，这些不是当前优化重点。

## 7. 参考依据

源码与本地复现是项目结论的主要依据。外部资料只用于方案约束：

- W3C Reflow：`https://www.w3.org/WAI/WCAG22/Understanding/reflow.html`。单屏目标不得靠裁切内容实现。
- Playwright assertions：`https://playwright.dev/docs/test-assertions`。可见不等于在视口内，需增加实际视口/滚动断言。
- Docker Compose startup order：`https://docs.docker.com/compose/how-tos/startup-order/`。启动顺序与应用处理就绪需要分别设计。
- Celery monitoring：`https://docs.celeryq.dev/en/stable/userguide/monitoring.html`。观察消费者、活动任务和事件，而不只看进程存活。
