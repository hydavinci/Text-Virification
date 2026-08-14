# text-verification 中英文文档校验 Web 重构设计

## 1. 背景与目标

`text-verification` 当前包含位于 `translation-pre-checker` 子目录的 Flask + 原生 JavaScript Demo，已经具备文本/文件上传、规则检查、问题审阅和多格式导出的基础能力，但存在单体文件过大、位置映射未贯通、导出使用全局字符串替换、临时文件无生命周期、OCR 模块未接入、无任务队列和无测试等问题。

本项目将重构为面向企业内网约 20 人并发使用的 Vue 3 + FastAPI Web 应用，单文件上限为 25MB。首版支持 DOCX、文本型/扫描型 PDF 和 TXT，提供：

- 中文错别字及基础语病检查；
- 英文拼写、语法及风格检查；
- 文档结构和基本格式检查；
- 共享行业词库与浏览器个人词库；
- 敏感词检测、解释、精确替换和白名单；
- 原文预览、问题定位、逐条接受或忽略；
- DOCX、PDF、TXT 修改版及问题报告导出。

首版不依赖大模型，但检查插件接口必须允许后续接入内网或外部模型。

## 2. 范围与边界

### 2.1 首版范围

- Vue 3 + TypeScript + Vite 前端。
- FastAPI 模块化单体 API。
- PostgreSQL 保存共享词库、规则版本和任务元数据。
- Redis + Celery 执行解析、检查和导出任务。
- DOCX、PDF、TXT 的上传、解析、预览、检查和导出。
- 内网所有用户均可维护共享行业词库。
- 个人词库仅保存在当前浏览器 IndexedDB，检查时随请求提交，服务端不持久化。
- 文本型 PDF 支持直接替换；扫描型 PDF 只支持高亮批注和问题报告。
- 任务级临时目录和自动过期清理。

### 2.2 非目标

- 公网 SaaS、多租户计费和组织隔离。
- 用户登录、企业 SSO 和细粒度权限。
- DOC、RTF、Markdown、CSV 的完整预览与保真导出。
- 扫描型 PDF 的版式保真文字替换。
- 大模型语义校对。
- 实时多人协同编辑。

## 3. 总体架构

```text
Vue 3 Web
  |- 上传与任务进度
  |- docx-preview / PDF.js / TXT 预览
  |- 问题列表、定位、接受/忽略
  |- IndexedDB 个人词库
  `- 共享词库管理
          |
          | REST + SSE
          v
FastAPI
  |- Upload API
  |- Job API / SSE
  |- Dictionary API
  |- Review Decision API
  `- Export API
          |
          +--> PostgreSQL
          |      |- jobs
          |      |- shared_dictionaries
          |      |- dictionary_entries
          |      `- rule_versions
          |
          +--> Redis Queue --> Worker
          |                    |- Parser Registry
          |                    |- Checker Registry
          |                    `- Exporter Registry
          |
          +--> LanguageTool Service
          `--> Per-job Temporary Storage
```

FastAPI 负责快速请求、参数校验和状态查询，不直接执行 CPU 密集型解析或校对。Worker 按任务串联解析器和检查插件。每个上传文件使用独立目录，所有中间产物均属于同一任务并按过期时间清理。

## 4. 后端组件

### 4.1 Parser Registry

解析器统一输出 `DocumentModel`，不得只返回拼接后的纯文本。

```python
DocumentModel:
  document_id: UUID
  file_type: "docx" | "pdf" | "txt"
  source_name: str
  blocks: list[TextBlock]

TextBlock:
  block_id: str
  kind: "paragraph" | "heading" | "table_cell" | "header" | "footer"
  text: str
  page: int | None
  paragraph_index: int | None
  parent_id: str | None
  style: dict
  source_locator: dict
```

- DOCX：使用 `python-docx` 和必要的 OOXML 辅助代码，保留段落、run、表格、页眉页脚及样式定位信息。
- PDF：使用 PyMuPDF 提取页面、文本 span、坐标、字体和字号；无法提取有效文本时标记为扫描型并进入 OCR。
- TXT：检测编码并生成按段落划分的文本块。
- OCR：复用并重构现有 RapidOCR/PyMuPDF 模块，只作为扫描型 PDF 的解析回退。

### 4.2 Checker Registry

所有检查器实现统一接口：

```python
class Checker:
    name: str
    version: str
    supported_languages: set[str]

    def check(
        self,
        document: DocumentModel,
        context: CheckContext,
    ) -> list[Issue]:
        ...
```

首版检查器：

1. `FormatChecker`
   - 中英文标点混用；
   - 全角/半角规范；
   - 数字与单位空格；
   - 日期、编号和大小写一致性；
   - 标题层级连续性及标题末尾句号；
   - 段落空行；
   - 表格/图片标题格式。
2. `SensitiveWordChecker`
   - 共享行业词库；
   - 请求携带的个人词库；
   - 白名单；
   - 风险等级和替换策略；
   - 变体标准化匹配。
3. `ChineseCorrectionChecker`
   - 通过适配器集成 pycorrector；
   - 将第三方结果转换为统一 Issue；
   - 对无法稳定映射回原文位置的结果不自动替换。
4. `EnglishLanguageChecker`
   - 通过 HTTP 调用内网自托管 LanguageTool；
   - 只发送必要文本块；
   - 将 LanguageTool offset 映射回块内位置。
5. `LegacyRuleChecker`
   - 迁移现有 Demo 中经过验证的错别字、术语一致性、标点和格式规则；
   - 规则数据与执行代码分离。

Vale 和 textlint 仅用于借鉴 YAML 规则、规则包和插件设计，首版不引入额外 Go/Node 服务。houbb/sensitive-word 和 ToolGood.Words 仅用于借鉴变体与词库能力，不引入 Java/.NET 运行时。

### 4.3 统一 Issue Schema

```json
{
  "issue_id": "uuid",
  "document_id": "uuid",
  "block_id": "p-42",
  "page": 3,
  "start": 12,
  "end": 15,
  "original": "错误文本",
  "suggestion": "正确文本",
  "alternatives": [],
  "type": "typo",
  "severity": "warning",
  "layer": "vocabulary",
  "message": "问题说明",
  "rule_id": "pycorrector.word_error",
  "source": "pycorrector",
  "source_version": "x.y.z",
  "confidence": 0.91,
  "auto_fixable": true,
  "context": "命中上下文"
}
```

`start` 和 `end` 始终是 `block_id` 对应原始文本中的 Unicode 字符偏移。导出时必须同时验证 `block_id`、区间和 `original`，不允许仅按字符串执行全局替换。

### 4.4 词库服务

共享行业词库模型：

```text
Dictionary
- id
- name
- industry
- description
- enabled
- version
- updated_at

DictionaryEntry
- id
- dictionary_id
- term
- replacement
- category
- risk_level
- action: prompt | replace | block
- match_modes
- enabled
- note
```

`match_modes` 可包含：

- 大小写不敏感；
- 繁简体归一化；
- 全半角归一化；
- 忽略词中符号；
- 拼音或首字母变体。

敏感词匹配使用 Python Aho-Corasick 实现多模式批量扫描。标准化管线必须保留“标准化字符位置到原文位置”的反向映射，确保命中区间和替换位置准确。白名单在敏感词匹配后、Issue 生成前应用。

个人词库使用版本化 JSON Schema 保存到 IndexedDB。前端发起检查时只提交本次启用的个人条目，后端完成校验后放入任务上下文，不写入数据库或日志。

## 5. 前端组件

- `UploadWorkspace`：拖拽上传、文件限制提示和行业选择。
- `JobProgress`：通过 SSE 展示上传、解析、规则检查、中文检查、英文检查和结果生成进度。
- `DocumentViewer`：
  - DOCX 使用 `docx-preview`；
  - PDF 使用固定版本的 PDF.js；
  - TXT 使用虚拟化文本视图；
  - 维护预览 DOM 文本节点与 `block_id/start/end` 的映射。
- `IssuePanel`：筛选、定位、接受、忽略、替换候选和批量操作。
- `DictionaryManager`：共享行业词库的查询、导入、编辑和版本展示。
- `PersonalDictionary`：IndexedDB 本地维护、导入、导出和清空。
- `ExportPanel`：选择修改版、批注版或问题报告。

所有来自文档和词库的内容必须通过文本节点渲染或统一 HTML 清洗，不允许直接拼接到 `innerHTML`。

## 6. 任务与 API

### 6.1 核心 API

```text
POST   /api/v1/jobs
GET    /api/v1/jobs/{job_id}
GET    /api/v1/jobs/{job_id}/events
GET    /api/v1/jobs/{job_id}/document
GET    /api/v1/jobs/{job_id}/issues
PUT    /api/v1/jobs/{job_id}/decisions
POST   /api/v1/jobs/{job_id}/exports
GET    /api/v1/exports/{export_id}

GET    /api/v1/dictionaries
POST   /api/v1/dictionaries
PUT    /api/v1/dictionaries/{dictionary_id}
POST   /api/v1/dictionaries/{dictionary_id}/entries:import
```

### 6.2 任务状态

```text
queued
upload_validated
parsing
checking_format
checking_sensitive
checking_chinese
checking_english
completed
partial
failed
expired
```

检查插件失败时任务进入 `partial`，保留其他插件结果，并在响应中列出失败插件和可读错误。解析失败时任务进入 `failed`，不运行后续检查。

## 7. 导出设计

### 7.1 修改决策

前端提交：

```json
{
  "issue_id": "uuid",
  "decision": "accepted",
  "selected_suggestion": "替换文本",
  "expected_original": "原文"
}
```

后端只允许操作当前任务产生的 Issue。应用修改时按照同一块内偏移降序执行，并验证当前位置文本等于 `expected_original`；不一致时拒绝该修改并在导出结果中报告冲突。

### 7.2 DOCX

- 修改版：按 source locator 定位段落和 run，必要时拆分 run，保留未修改内容的格式。
- 批注版：使用 `python-docx` 1.2+ 原生 comment API；跨 run 命中先拆分为完整 run 范围。
- 修订痕迹：在固定 OOXML fixture 测试通过后保留现有自定义实现，不依赖未验证的段落整体重建。

### 7.3 PDF

- 文本型 PDF：
  - 根据解析阶段保存的坐标定位文本；
  - 使用 redaction 删除原文；
  - 按原字体、字号和基线写入建议文本；
  - 替换文本超出原区域时标记版式风险并要求用户确认，不能静默截断。
- 扫描型 PDF：
  - 不直接替换；
  - 导出高亮/注释 PDF 和问题报告。
- 所有 PDF 均可导出问题报告。

### 7.4 TXT 与报告

- TXT 修改版保持原始编码；无法可靠编码建议文本时统一导出 UTF-8 并在下载信息中说明。
- 报告首版支持 CSV 和 XLSX，字段包含页/段、问题类型、严重度、原文、建议、说明、规则来源和用户决策。

## 8. 文件与数据生命周期

- 文件扩展名、MIME 和实际文件签名必须一致。
- DOCX 解压前检查压缩条目数量、单项大小和总展开大小，防止压缩炸弹。
- 每个任务使用不可猜测 UUID 和独立目录。
- 默认任务和文件保留 24 小时，之后由定时清理任务删除。
- API 不暴露服务器路径。
- 日志不记录文档正文、个人词库或完整敏感词命中上下文。
- 上传和下载接口只允许访问数据库中未过期的任务资源。
- 内网所有用户均可修改共享词库是明确的产品决策；每次变更仍需记录时间、来源 IP、变更摘要和版本，以支持回滚。

## 9. 错误处理与可观测性

- 每个任务生成关联 ID，并贯穿 API、Worker、LanguageTool 和导出日志。
- 外部进程、OCR 和 LanguageTool 调用设置明确超时。
- Worker 失败采用有限重试；确定性解析错误不重试。
- 用户可见错误必须区分文件无效、解析失败、插件超时、部分检查失败、导出冲突和任务过期。
- 指标至少包括任务数量、各阶段耗时、队列长度、失败率、文档大小、Issue 数量和导出冲突数。

## 10. 测试策略

### 10.1 单元测试

- 标准化字符到原文位置的反向映射；
- Aho-Corasick 多词、重叠词、白名单和变体匹配；
- Issue Schema 校验；
- 同块多修改的倒序应用与冲突检测；
- LanguageTool 和 pycorrector 结果转换；
- 文件类型和压缩包安全校验。

### 10.2 Fixture 集成测试

- DOCX：跨 run、表格、页眉页脚、标题样式、重复短语和批注。
- PDF：多页、嵌入字体、中文字体、跨行文本、替换文本变长及扫描页。
- TXT：UTF-8、GBK、UTF-16 和不可表示字符。
- 重复文本只修改用户接受的指定位置。

### 10.3 端到端测试

- 上传到结果定位；
- 接受/忽略后导出；
- 个人词库仅存在浏览器；
- 共享词库修改后新任务使用新版本；
- 插件超时产生部分结果；
- 过期任务不可继续下载。

## 11. 迁移计划

### 阶段 1：基础架构

- 建立 Vue 3、FastAPI、PostgreSQL、Redis 和 Celery Worker 项目结构。
- 定义 DocumentModel、Issue、Checker、Parser 和 Exporter 接口。
- 建立任务、临时目录和清理机制。

### 阶段 2：DOCX/TXT 闭环

- 完成 DOCX/TXT 解析与预览。
- 迁移稳定的现有规则。
- 完成精确位置审阅、修改版和报告导出。

### 阶段 3：检查插件

- 接入敏感词标准化及 Aho-Corasick。
- 接入 pycorrector。
- 部署并接入 LanguageTool。
- 完成共享行业词库和 IndexedDB 个人词库。

### 阶段 4：PDF

- 接入 PDF.js。
- 完成文本型 PDF 精确定位、直接替换和版式风险提示。
- 接入扫描型 PDF OCR、批注及报告。

### 阶段 5：管理与加固

- 完成共享词库导入、版本和回滚。
- 完成指标、日志、压力测试、安全测试和部署文档。
- 达到验收条件后替换旧 Demo。

## 12. 验收条件

- 20 个并发检查任务下，API 可持续响应，任务由队列稳定消费。
- 25MB 合法文件可上传，非法类型和压缩炸弹被拒绝。
- DOCX/PDF/TXT 问题可从列表准确定位到预览原文。
- 同一短语出现多次时，只修改用户接受的指定位置。
- 中文、英文、格式和敏感词插件结果均符合统一 Issue Schema。
- 共享行业词库支持分类、风险等级、替换词、白名单、导入和版本记录。
- 个人词库刷新页面后仍存在于当前浏览器，但数据库和服务端日志中不存在。
- DOCX 可导出修改版和批注版。
- 文本型 PDF 可直接替换并报告版式风险；扫描型 PDF 只提供批注和报告。
- 任一检查插件失败不会丢失其他插件结果。
- 临时文件按策略自动清理，过期任务无法下载。

## 13. 参考项目的使用方式

| 项目 | 决策 |
|---|---|
| TextGuard | 借鉴任务、审阅、插件和产品流程，不直接合并代码 |
| AI-DocProof | 仅参考“分段—校对—批注”概念，不集成 |
| pycorrector | 通过 Checker 适配器集成 |
| LanguageTool | 作为内网独立 HTTP 服务集成 |
| Vale / textlint | 借鉴规则包和 YAML 配置，不引入运行时 |
| houbb/sensitive-word / ToolGood.Words | 借鉴标准化、变体和词库设计，不引入 Java/.NET 服务 |
| docx-preview | 作为前端 DOCX 预览组件集成 |
| PDF.js | 作为前端 PDF 预览组件集成 |
| python-docx | 继续作为 DOCX 解析、批注和导出核心库 |
| LibreOffice | 仅保留为后续旧 DOC 转换适配器，不进入首版格式范围 |
| Pandoc | 首版不集成，后续扩展 RTF/Markdown 时再评估 |

## 14. 已确认的关键决策

- 重写为 Vue 3 + FastAPI，而不是继续扩展 Flask Demo。
- 面向企业内网约 20 人并发，文件上限 25MB。
- 首版支持 DOCX、PDF 和 TXT。
- 首版不接大模型，但保留插件接口。
- 共享词库由内网所有用户维护。
- 个人词库只保存在浏览器。
- 使用 PostgreSQL、Redis 和 Celery 任务队列。
- 中文使用 pycorrector，英文使用自托管 LanguageTool。
- 敏感词采用 Python Aho-Corasick 和可逆标准化管线。
- 文本型 PDF 支持直接替换；扫描型 PDF 只批注和报告。
