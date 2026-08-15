# text-verification 中英文文档校验 Web 重构设计

> Related design: `docs/architecture/repository-layout-and-documentation.md`

## 1. 背景与目标

`text-verification` 当前采用 Monorepo 布局：`apps/api` 提供 FastAPI + Celery Stub 平台接口，`apps/web` 提供 Vue 3 前端，`infra/compose.yaml` 提供容器编排入口。早期位于 `translation-pre-checker/` 的 Flask Demo 已作为历史实现移除，本设计仅保留其需求背景，不将其视为当前受支持运行路径。

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
