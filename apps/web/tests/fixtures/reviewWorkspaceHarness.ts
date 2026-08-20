import { createApp } from 'vue'

import { analysisApiKey, type AnalysisApi } from '../../src/api/analysis'
import { exportsApiKey, type ExportsApi } from '../../src/api/exports'
import type {
  AnalysisSummaryResponse,
  DecisionBatchResponse,
  DecisionCommand,
  DocumentBlock,
  DocumentPageResponse,
  Issue,
  IssuePageResponse
} from '../../src/types/analysis'
import type { ExportCreateRequest, ExportCreateResponse, ExportResponse } from '../../src/types/exports'
import ReviewWorkspaceView from '../../src/views/ReviewWorkspaceView.vue'

const jobId = 'layout-job'
const sourceName = '翻译服务合同.docx'
const fileType = 'docx'

const blocks = buildBlocks()
const issues = buildIssues()
const summary = buildSummary(issues)

const analysisApi: AnalysisApi = {
  async getSummary(): Promise<AnalysisSummaryResponse> {
    return summary
  },
  async getDocumentPage(): Promise<DocumentPageResponse> {
    return {
      job_id: jobId,
      status: 'completed',
      document_id: 'document-1',
      file_type: fileType,
      source_name: sourceName,
      version: 1,
      metadata: {},
      blocks,
      total_blocks: blocks.length,
      next_cursor: null,
      checker_failures: {}
    }
  },
  async getIssues(): Promise<IssuePageResponse> {
    return {
      job_id: jobId,
      status: 'completed',
      total: issues.length,
      items: issues,
      next_cursor: null,
      checker_failures: {}
    }
  },
  async putDecisions(_requestedJobId: string, decisions: DecisionCommand[]): Promise<DecisionBatchResponse> {
    const updatedAt = new Date('2026-08-20T00:00:00.000Z').toISOString()

    return {
      outcomes: decisions.map((decision) => {
        const baseDecision = {
          issue_id: decision.issue_id,
          issue_version: decision.issue_version,
          updated_at: updatedAt
        }

        if (decision.action === 'custom') {
          return {
            issue_id: decision.issue_id,
            status: 'applied',
            code: null,
            decision: {
              ...baseDecision,
              action: 'custom' as const,
              replacement: decision.replacement
            }
          }
        }

        return {
          issue_id: decision.issue_id,
          status: 'applied',
          code: null,
          decision: {
            ...baseDecision,
            action: decision.action,
            replacement: null
          }
        }
      })
    }
  }
}

const exportsApi: ExportsApi = {
  async create(
    _requestedJobId: string,
    _request: ExportCreateRequest
  ): Promise<ExportCreateResponse> {
    throw new Error('Layout fixture does not execute exports.')
  },
  async get(_requestedJobId: string, _exportId: string): Promise<ExportResponse> {
    throw new Error('Layout fixture does not query exports.')
  },
  downloadUrl(): string {
    return ''
  }
}

const app = createApp(ReviewWorkspaceView, {
  jobId,
  sourceName,
  fileType
})

app.provide(analysisApiKey, analysisApi)
app.provide(exportsApiKey, exportsApi)
app.mount('#app')

function buildBlocks(): DocumentBlock[] {
  return Array.from({ length: 30 }, (_, index) => ({
    block_id: `block-${index + 1}`,
    kind: 'paragraph',
    text: `第 ${index + 1} 段合同内容包含交付标准、服务边界与审批说明，用于稳定布局回归测试。`,
    page: null,
    paragraph_index: index,
    parent_id: null,
    style: {},
    source_locator: {}
  }))
}

function buildIssues(): Issue[] {
  const categories = ['character', 'vocabulary', 'sentence', 'format', 'discourse', 'security'] as const
  const severities = ['warning', 'warning', 'info', 'error'] as const

  return Array.from({ length: 12 }, (_, index) => {
    const blockIndex = (index * 2) % blocks.length
    const block = blocks[blockIndex]
    const category = categories[index % categories.length]
    const severity = severities[index % severities.length]
    const original = `第 ${blockIndex + 1}`

    return {
      issue_id: `issue-${index + 1}`,
      document_id: 'document-1',
      document_version: 1,
      block_id: block.block_id,
      page: null,
      start: 0,
      end: original.length,
      original,
      suggestion: `建议修改 ${index + 1}`,
      alternatives: [],
      type: category,
      severity,
      layer: category,
      message: `问题 ${index + 1}：请检查${block.text.slice(0, 12)}`,
      rule_id: `${category}-${index + 1}`,
      source: 'fixture',
      source_version: '1',
      confidence: 0.95,
      auto_fixable: severity !== 'error',
      context: block.text,
      decision: null
    }
  })
}

function buildSummary(seedIssues: Issue[]): AnalysisSummaryResponse {
  return {
    job_id: jobId,
    status: 'completed',
    total_issues: seedIssues.length,
    by_category: {
      character: countBy(seedIssues, (issue) => issue.type === 'character'),
      vocabulary: countBy(seedIssues, (issue) => issue.type === 'vocabulary'),
      sentence: countBy(seedIssues, (issue) => issue.type === 'sentence'),
      format: countBy(seedIssues, (issue) => issue.type === 'format'),
      discourse: countBy(seedIssues, (issue) => issue.type === 'discourse'),
      security: countBy(seedIssues, (issue) => issue.type === 'security')
    },
    by_severity: {
      error: countBy(seedIssues, (issue) => issue.severity === 'error'),
      warning: countBy(seedIssues, (issue) => issue.severity === 'warning'),
      info: countBy(seedIssues, (issue) => issue.severity === 'info')
    },
    by_decision: {
      accepted: 0,
      ignored: 0,
      custom: 0,
      unreviewed: seedIssues.length
    },
    checker_failures: {}
  }
}

function countBy<TItem>(items: TItem[], matches: (item: TItem) => boolean): number {
  return items.reduce((count, item) => count + Number(matches(item)), 0)
}
