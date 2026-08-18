import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { analysisApiKey, type AnalysisApi } from '../src/api/analysis'
import { exportsApiKey, type ExportsApi } from '../src/api/exports'
import type {
  AnalysisSummaryResponse,
  DecisionBatchResponse,
  DocumentBlock,
  DocumentPageResponse,
  Issue,
  IssuePageResponse
} from '../src/types/analysis'
import type { ExportCreateResponse, ExportResponse } from '../src/types/exports'
import ReviewWorkspaceView from '../src/views/ReviewWorkspaceView.vue'
import AppSource from '../src/App.vue?raw'
import DocumentViewerSource from '../src/components/review/DocumentViewer.vue?raw'
import ReviewNavigationSource from '../src/components/review/ReviewNavigation.vue?raw'
import IssuePanelSource from '../src/components/review/IssuePanel.vue?raw'
import ReviewWorkspaceViewSource from '../src/views/ReviewWorkspaceView.vue?raw'

const jobId = 'job-1'

function buildBlock(overrides: Partial<DocumentBlock> = {}): DocumentBlock {
  return {
    block_id: 'block-1',
    kind: 'paragraph',
    text: '第一段文字',
    page: null,
    paragraph_index: 0,
    parent_id: null,
    style: {},
    source_locator: {},
    ...overrides
  }
}

function buildIssue(overrides: Partial<Issue> = {}): Issue {
  return {
    issue_id: 'issue-1',
    document_id: 'document-1',
    document_version: 1,
    block_id: 'block-1',
    page: null,
    start: 0,
    end: 2,
    original: '第一',
    suggestion: '首段',
    alternatives: [],
    type: 'character',
    severity: 'warning',
    layer: 'character',
    message: '建议调整措辞',
    rule_id: 'character-1',
    source: 'local',
    source_version: '1',
    confidence: 0.9,
    auto_fixable: true,
    context: '第一段文字',
    decision: null,
    ...overrides
  }
}

function buildSummary(
  overrides: Partial<AnalysisSummaryResponse> = {}
): AnalysisSummaryResponse {
  return {
    job_id: jobId,
    status: 'completed',
    total_issues: 2,
    by_category: {
      character: 2,
      vocabulary: 0,
      sentence: 0,
      format: 0,
      discourse: 0,
      security: 0
    },
    by_severity: { error: 0, warning: 2, info: 0 },
    by_decision: { accepted: 0, ignored: 0, custom: 0, unreviewed: 2 },
    checker_failures: {},
    ...overrides
  }
}

function buildDocumentPage(
  overrides: Partial<DocumentPageResponse> = {}
): DocumentPageResponse {
  return {
    job_id: jobId,
    status: 'completed',
    document_id: 'document-1',
    file_type: 'txt',
    source_name: 'sample.txt',
    version: 1,
    metadata: {},
    blocks: [
      buildBlock(),
      buildBlock({
        block_id: 'block-2',
        text: '第二段文字',
        paragraph_index: 1
      })
    ],
    total_blocks: 2,
    next_cursor: null,
    checker_failures: {},
    ...overrides
  }
}

function buildIssuePage(overrides: Partial<IssuePageResponse> = {}): IssuePageResponse {
  return {
    job_id: jobId,
    status: 'completed',
    total: 2,
    items: [
      buildIssue(),
      buildIssue({
        issue_id: 'issue-2',
        block_id: 'block-2',
        original: '第二',
        message: '发现错词',
        severity: 'error',
        context: '第二段文字'
      })
    ],
    next_cursor: null,
    checker_failures: {},
    ...overrides
  }
}

function createAnalysisApiMock(overrides: Partial<AnalysisApi> = {}): AnalysisApi {
  return {
    getSummary: vi.fn().mockResolvedValue(buildSummary()),
    getDocumentPage: vi.fn().mockResolvedValue(buildDocumentPage()),
    getIssues: vi.fn().mockResolvedValue(buildIssuePage()),
    putDecisions: vi.fn().mockResolvedValue({ outcomes: [] } as DecisionBatchResponse),
    ...overrides
  }
}

function createExportsApiMock(overrides: Partial<ExportsApi> = {}): ExportsApi {
  return {
    create: vi.fn().mockResolvedValue({
      export_id: 'export-1',
      job_id: jobId,
      export_type: 'html_report',
      status: 'completed',
      file_name: 'report.html',
      warnings: [],
      error_code: null,
      error_message: null,
      created_at: '2026-08-18T00:00:00Z',
      updated_at: '2026-08-18T00:00:00Z',
      expires_at: '2026-08-19T00:00:00Z',
      dispatch_status: 'dispatched'
    } as ExportCreateResponse),
    get: vi.fn().mockResolvedValue({
      export_id: 'export-1',
      job_id: jobId,
      export_type: 'html_report',
      status: 'completed',
      file_name: 'report.html',
      warnings: [],
      error_code: null,
      error_message: null,
      created_at: '2026-08-18T00:00:00Z',
      updated_at: '2026-08-18T00:00:00Z',
      expires_at: '2026-08-19T00:00:00Z'
    } as ExportResponse),
    downloadUrl: vi.fn().mockReturnValue('/api/v1/jobs/job-1/exports/export-1/download'),
    ...overrides
  }
}

function mountReviewWorkspace() {
  return mount(ReviewWorkspaceView, {
    props: {
      jobId,
      sourceName: 'sample.txt',
      fileType: 'txt'
    },
    global: {
      provide: {
        [analysisApiKey as symbol]: createAnalysisApiMock(),
        [exportsApiKey as symbol]: createExportsApiMock()
      }
    }
  })
}

describe('review workspace accessibility', () => {
  function sourceRuleBody(source: string, selector: string) {
    return source.match(new RegExp(`${selector}\\s*\\{([\\s\\S]*?)\\}`))?.[1] ?? ''
  }

  it('keeps desktop document-centered DOM order and exposes icon-plus-text severity labels', async () => {
    const wrapper = mountReviewWorkspace()
    await flushPromises()

    const labeledLandmarks = wrapper
      .get('.review-workspace__columns')
      .findAll(':scope > [aria-label]')
      .map((node) => node.attributes('aria-label'))

    expect(labeledLandmarks).toEqual(['问题筛选', '文档内容', '问题详情'])
    expect(wrapper.get('[data-issue-id="issue-1"]').text()).toContain('⚠ 警告')
    expect(wrapper.get('aside[aria-label="问题详情"]').text()).toContain('⚠ 警告')
  })

  it('ships visible focus, 44px touch targets, and reduced-motion styles', () => {
    expect(AppSource).toContain('@media (prefers-reduced-motion: reduce)')
    expect(AppSource).toContain(':focus-visible')
    expect(ReviewWorkspaceViewSource).toContain('min-height: 44px')
    expect(ReviewWorkspaceViewSource).toContain('[role="tab"]')
    expect(ReviewNavigationSource).toContain('min-height: 44px')
    expect(ReviewNavigationSource).toContain(':focus-visible')
    expect(IssuePanelSource).toContain('min-height: 44px')
    expect(IssuePanelSource).toContain(':focus-visible')
  })

  it('gives document highlight controls their own 44px touch-target contract', () => {
    const highlightControlRule = sourceRuleBody(
      DocumentViewerSource,
      '\\.document-highlight-control'
    )

    expect(ReviewWorkspaceViewSource).toContain('button:not(.document-highlight-control)')
    expect(highlightControlRule).toContain('min-width: 44px')
    expect(highlightControlRule).toContain('min-height: 44px')
    expect(highlightControlRule).not.toMatch(/\bwidth:\s*(?:0?\.\d+em|[0-3]?\dpx)\b/)
    expect(highlightControlRule).not.toMatch(/\bheight:\s*(?:0?\.\d+em|[0-3]?\dpx)\b/)
  })
})
