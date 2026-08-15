# 文档核验闭环与审阅工作台设计

## 目标

在现有 Text Verification 平台基础上实现第一阶段业务闭环：

1. 解析 TXT、DOCX 和 PDF。
2. 通过本地规则与词库执行六类检查。
3. 在三栏工作台中定位、筛选和审阅问题。
4. 对 TXT、DOCX 应用已接受的修改。
5. 导出修改版文件以及 HTML/PDF 问题报告。

第一阶段不包含 OCR、自定义词库管理、暗色模式或 AI 复核。PDF 仅支持只读检查和报告导出，不生成修改版 PDF。

## 设计原则

- 沿用现有 FastAPI、Celery、PostgreSQL、Redis 和任务存储架构，不引入新服务。
- 迁移参考项目中有价值的规则和交互，不复制其单体状态、临时文件导出和硬编码架构。
- 解析、检查、审阅和导出使用独立接口和统一领域模型。
- 所有失败显式记录；检查器允许部分失败，但不得伪装为完整成功。
- 本地规则和共享词库优先，通过接口预留后续 AI 复核能力。

## 范围

### 第一阶段包含

- TXT、DOCX 正文解析和可编辑导出。
- PDF 文本解析、只读预览和问题报告导出。
- 通用、学术、商务、法律、新闻、技术六种使用场景。
- 文字、词汇、句子、格式、篇章、安全六类检查。
- 问题分页、筛选、定位、高亮和统计。
- 单条接受、忽略、自定义替换和批量决策。
- 修改版 TXT/DOCX 导出。
- HTML/PDF 问题报告导出。
- 上传、解析、检查、审阅和导出的完整错误状态。

### 第一阶段不包含

- 扫描型 PDF OCR。
- PDF 原文替换或修改版 PDF。
- 用户自定义词库管理。
- AI 语义复核和解释。
- 暗色主题。
- 多用户权限与长期文档归档。

## 后端架构

后端保持单体分层架构，新增以下边界：

### Parser

`DocumentParser` 根据文件类型生成统一 `DocumentModel`。实现包括：

- `TxtParser`
- `DocxParser`
- `PdfParser`

解析结果由稳定文档块组成。每个块包含块 ID、块类型、纯文本、文档顺序、源文件定位信息和格式元数据。DOCX 额外记录段落、表格单元格及 run 映射；PDF 记录页码与可用文本位置。

### Checker

`DocumentChecker` 只接收 `DocumentModel`、场景配置和规则上下文，返回统一 `Issue` 列表。通过注册表组织六类检查器：

- character
- vocabulary
- sentence
- format
- discourse
- security

每个类别可包含多个规则实现。单个检查器失败时记录失败类别和错误码，流水线继续执行其他检查器，并将任务结果标记为 `partial`。

### Review

问题和用户决策持久化到 PostgreSQL。决策操作使用问题版本号进行乐观并发控制，防止旧页面覆盖重新检查后的结果。

### Export

`DocumentExporter` 读取原始文件、已接受决策和解析映射：

- TXT：按倒序偏移应用替换并生成新文件。
- DOCX：按块与 run 映射应用安全替换，尽量保留格式。
- HTML：通过服务端模板生成完整问题报告。
- PDF：由同一 HTML 报告渲染，保证两种报告内容一致。

跨越不可安全修改 run 边界的 DOCX 替换不得静默应用。导出结果应标记该问题为“不可自动应用”，并在报告中说明原因。

### 规则与词库

现有 `resources/dictionaries` 是共享词库的唯一运行时来源。参考项目中的错词、场景和安全规则经整理后进入独立配置文件，不复制到 Python 源码中。

预留 `ReviewProvider` 接口供未来 AI 复核实现使用；第一阶段不配置或调用该接口。

## 数据模型

### DocumentModel

- `document_id`
- `file_type`
- `source_name`
- `version`
- `blocks`
- `metadata`

### TextBlock

- `block_id`
- `block_type`
- `order`
- `text`
- `source_locator`
- `format_metadata`

### Issue

- `issue_id`
- `job_id`
- `document_version`
- `category`
- `severity`
- `rule_id`
- `block_id`
- `start_offset`
- `end_offset`
- `original`
- `suggestion`
- `context`
- `description`
- `confidence`
- `created_at`

偏移以对应块的 Unicode 代码点位置为准；API 与前端不得自行按 UTF-16 重新计算。服务端返回高亮范围时同时返回块 ID 和规范化偏移。

### Decision

- `issue_id`
- `issue_version`
- `action`: `accepted | ignored | custom`
- `replacement`
- `updated_at`

### Export

- `export_id`
- `job_id`
- `export_type`
- `status`
- `file_name`
- `warnings`
- `created_at`
- `expires_at`

## 任务流水线

Celery 流水线状态如下：

```text
queued
  -> upload_validated
  -> parsing
  -> checking_format
  -> checking_sensitive
  -> checking_chinese
  -> checking_english
  -> completed | partial | failed
```

内部六类检查器可映射到现有对外状态，SSE 事件额外携带当前类别、已完成类别和问题计数。SSE 只传进度、统计和控制信息，不传正文或完整问题列表。

任务完成后，前端通过 REST 分页获取文档块、问题和统计。重新检查会创建新的文档版本和问题版本，旧决策不会自动应用到新版本。

## API 设计

保留现有端点：

- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/events`

扩展上传请求字段：

- `scenario`
- `enabled_categories`

新增端点：

- `GET /api/v1/jobs/{job_id}/document`
- `GET /api/v1/jobs/{job_id}/issues`
- `GET /api/v1/jobs/{job_id}/summary`
- `PUT /api/v1/jobs/{job_id}/decisions`
- `POST /api/v1/jobs/{job_id}/exports`
- `GET /api/v1/jobs/{job_id}/exports/{export_id}`
- `GET /api/v1/jobs/{job_id}/exports/{export_id}/download`

问题端点支持类别、严重级别、决策状态、关键词和分页筛选。批量决策请求必须逐项返回成功、冲突或无效原因，不得用单一成功响应隐藏部分失败。

导出是异步任务。创建接口返回 export ID，前端通过查询或任务事件获取状态，完成后使用短期下载端点获取文件。

## 前端体验

### 上传与处理中

保留当前视觉语言并增加：

- 使用场景选择。
- 六类检查开关，默认全部开启。
- 当前共享规则版本提示。
- 处理阶段和每类问题计数。

### 结果审阅工作台

采用文档中心三栏布局：

- 左栏：总览、六类筛选、严重级别和处理状态统计。
- 中栏：分块文档视图、问题高亮、当前问题定位与文档导航。
- 右栏：问题详情、原文、建议、规则说明、接受、忽略和自定义替换。

顶部工具栏提供文件信息、查找替换、批量接受/忽略和导出。底部显示已处理、未处理和高风险问题计数。

点击问题卡片时定位中栏对应块并高亮；点击文档高亮时选中对应问题。接受或自定义替换仅更新决策视图，不立即修改服务器上的原始文件。

窄屏使用“文档 / 问题”标签切换，不压缩三栏。状态不能仅通过颜色表达，同时显示图标和文本。问题导航、决策和标签切换均可使用键盘操作。

长文档使用块级按需加载或虚拟化。前端不一次性请求和渲染完整长文档。

## 错误处理

以下情况必须提供结构化错误码和中文可操作提示：

- 文件加密、损坏或类型不一致。
- DOCX 解压结构不安全。
- PDF 无可提取文本。
- 规则或词库格式无效。
- 单个检查器失败。
- 决策版本冲突。
- DOCX 替换跨越不可安全修改的 run 边界。
- 报告渲染或文件导出失败。
- 下载文件已过期。

任务为 `partial` 时，结果页必须明确列出缺失的检查类别。存在不可自动应用项时，导出前显示确认提示，导出报告保留这些项目及原因。

## 测试策略

所有实现遵循分层 TDD。

### Parser

- 使用固定 TXT、DOCX、PDF fixture。
- 验证块顺序、文本、Unicode 偏移、表格和 run 映射。
- 覆盖加密、损坏、无文本和不安全文档。

### Checker

- 每条规则使用表驱动测试。
- 验证场景、开关、严重级别、边界和误报排除。
- 验证单个检查器失败不影响其他类别。

### Persistence and API

- 使用真实 PostgreSQL 验证问题分页、决策版本冲突和导出状态。
- 验证 SSE 不包含正文或完整问题。
- 验证批量决策的逐项结果。

### Export

- 执行“解析 -> 决策 -> 导出 -> 重新解析”的往返测试。
- 验证 TXT 替换结果。
- 验证 DOCX 文本、段落、表格和未修改格式保持。
- 验证 HTML/PDF 报告内容一致。
- 验证不可安全应用替换进入 warnings。

### Frontend

- 覆盖上传配置、进度、筛选、定位、高亮和分页。
- 覆盖单条/批量决策、自定义替换和版本冲突。
- 覆盖导出状态、错误提示和下载。
- 覆盖 SSE 断线恢复及移动端标签切换。

### End-to-end

- TXT 上传到修改稿和报告下载。
- DOCX 上传到格式保持导出。
- PDF 上传到只读检查和报告下载。
- 检查器部分失败时仍可审阅完整的可用结果。

## 验收标准

- TXT 和 DOCX 可以完成上传、解析、六类检查、问题审阅和修改版导出。
- PDF 可以完成文本检查、问题审阅和 HTML/PDF 报告导出。
- 六类问题可按类别、严重级别和决策状态筛选。
- 问题定位和替换使用稳定块 ID 与规范化偏移。
- 单个检查器失败时任务进入 `partial`，可用结果不丢失。
- 所有不可自动应用修改和缺失检查类别均明确展示并进入报告。
- 完整自动化测试覆盖三种文件类型的核心闭环。

## 后续阶段

第一阶段完成后再评估：

1. 自定义词库和禁用词管理。
2. AI 低置信度复核。
3. 扫描型 PDF OCR。
4. 暗色模式。
5. 多用户权限、审阅历史和长期归档。
