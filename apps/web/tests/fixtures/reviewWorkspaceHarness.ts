import { createApp } from 'vue'

import { analysisApiKey, type AnalysisApi } from '../../src/api/analysis'
import { exportsApiKey, type ExportsApi } from '../../src/api/exports'
import { revisionsApiKey, type RevisionsApi } from '../../src/api/revisions'
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
import type {
  DocumentVersion,
  EditDraft,
  OperationBatch,
  OperationBatchPage,
  ReanalyzeRequest,
  UpdateDraftRequest
} from '../../src/types/revisions'
import ReviewWorkspaceView from '../../src/views/ReviewWorkspaceView.vue'

const jobId = 'layout-job'
const sourceName = '翻译服务合同.docx'
const fileType = 'docx'

const blocks = buildBlocks()
const issues = buildIssues()
const summary = buildSummary(issues)
const versions = buildVersions()
const activeVersionId = 'version-2'
let activeDraft: EditDraft | null = null

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
      batch_id: 'batch-1',
      outcomes: decisions.map((decision) => {
        const baseDecision = {
          issue_id: decision.issue_id,
          issue_version: decision.issue_version,
          revision: decision.expected_revision + 1,
          updated_at: updatedAt
        }

        if (decision.action === 'accepted') {
          return {
            issue_id: decision.issue_id,
            status: 'applied',
            code: null,
            decision: {
              ...baseDecision,
              action: 'accepted' as const,
              replacement: decision.replacement,
              suggestion_id: decision.suggestion_id
            }
          }
        }

        if (decision.action === 'unreviewed') {
          return {
            issue_id: decision.issue_id,
            status: 'applied' as const,
            code: null,
            decision: null
          }
        }

        return {
          issue_id: decision.issue_id,
          status: 'applied' as const,
          code: null,
          decision: {
            ...baseDecision,
            action: 'ignored' as const,
            replacement: null,
            suggestion_id: null
          }
        }
      })
    }
  }
}

const revisionsApi: RevisionsApi = {
  async listVersions() {
    return {
      job_id: jobId,
      active_version_id: activeVersionId,
      versions
    }
  },
  async createDraft(_requestedJobId: string, baseVersionId: string): Promise<EditDraft> {
    activeDraft = {
      draft_id: 'draft-layout-1',
      job_id: jobId,
      base_version_id: baseVersionId,
      revision: 1,
      blocks: blocks.map((block) => ({ block_id: block.block_id, text: block.text })),
      content_sha256: 'layout-draft-sha',
      created_at: '2026-08-20T00:00:00.000Z',
      updated_at: '2026-08-20T00:00:00.000Z',
      consumed_at: null
    }
    return activeDraft
  },
  async getDraft(): Promise<EditDraft> {
    if (!activeDraft) {
      throw new Error('Layout fixture draft has not been created.')
    }
    return activeDraft
  },
  async updateDraft(
    _requestedJobId: string,
    _draftId: string,
    request: UpdateDraftRequest
  ): Promise<EditDraft> {
    if (!activeDraft) {
      throw new Error('Layout fixture draft has not been created.')
    }
    activeDraft = {
      ...activeDraft,
      revision: request.expected_revision + 1,
      blocks: request.blocks,
      updated_at: '2026-08-20T00:00:01.000Z'
    }
    return activeDraft
  },
  async deleteDraft(): Promise<void> {
    activeDraft = null
  },
  async reanalyze(
    _requestedJobId: string,
    _draftId: string,
    _request: ReanalyzeRequest
  ) {
    return {
      version: versions[0],
      events_url: `/api/v1/jobs/${jobId}/versions/${versions[0].version_id}/events`
    }
  },
  async getDerived(_requestedJobId: string, versionId: string) {
    return {
      job_id: jobId,
      version_id: versionId,
      decision_snapshot_sha256: 'layout-derived-sha',
      blocks
    }
  },
  subscribeVersionEvents() {
    return () => {}
  },
  async listHistory(_requestedJobId: string, versionId: string): Promise<OperationBatchPage> {
    return {
      job_id: jobId,
      version_id: versionId,
      total: 1,
      items: [buildOperationBatch(versionId)],
      next_cursor: null
    }
  },
  async undoBatch(_requestedJobId: string, batchId: string): Promise<OperationBatch> {
    return buildOperationBatch(activeVersionId, batchId, 'undo')
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
app.provide(revisionsApiKey, revisionsApi)
app.provide(exportsApiKey, exportsApi)
app.mount('#app')

function buildVersions(): DocumentVersion[] {
  return [
    {
      version_id: 'version-2',
      job_id: jobId,
      parent_version_id: 'version-1',
      revision_number: 2,
      status: 'succeeded',
      source_kind: 'edit',
      created_reason: 'edited',
      content_sha256: 'layout-version-2-sha',
      created_at: '2026-08-20T00:10:00.000Z',
      started_at: '2026-08-20T00:10:01.000Z',
      completed_at: '2026-08-20T00:10:02.000Z',
      failure_code: null,
      failure_message: null
    },
    {
      version_id: 'version-1',
      job_id: jobId,
      parent_version_id: null,
      revision_number: 1,
      status: 'succeeded',
      source_kind: 'upload',
      created_reason: 'upload',
      content_sha256: 'layout-version-1-sha',
      created_at: '2026-08-20T00:00:00.000Z',
      started_at: '2026-08-20T00:00:01.000Z',
      completed_at: '2026-08-20T00:00:02.000Z',
      failure_code: null,
      failure_message: null
    }
  ]
}

function buildOperationBatch(
  versionId: string,
  batchId = 'batch-layout-1',
  operationType: OperationBatch['operation_type'] = 'decision'
): OperationBatch {
  return {
    batch_id: batchId,
    job_id: jobId,
    version_id: versionId,
    operation_type: operationType,
    affected_count: 2,
    undoes_batch_id: operationType === 'undo' ? 'batch-layout-1' : null,
    created_at: '2026-08-20T00:12:00.000Z'
  }
}

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
