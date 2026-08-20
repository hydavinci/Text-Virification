import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { analysisApiKey, type AnalysisApi } from '../src/api/analysis'
import { exportsApiKey, type ExportsApi } from '../src/api/exports'
import {
  reviewIntersectionObserverFactoryKey,
  type ReviewIntersectionObserverCallback,
  type ReviewIntersectionObserverFactory
} from '../src/components/review/observer'
import ReviewNavigation from '../src/components/review/ReviewNavigation.vue'
import { useReviewWorkspace } from '../src/composables/useReviewWorkspace'
import { ApiError } from '../src/types/api'
import type {
  AnalysisSummaryResponse,
  DecisionBatchResponse,
  DocumentBlock,
  DocumentPageResponse,
  Issue,
  IssueDecision,
  IssuePageResponse
} from '../src/types/analysis'
import type { ExportCreateResponse, ExportResponse, ExportWarning } from '../src/types/exports'
import type { FileType } from '../src/types/review'
import ReviewWorkspaceView from '../src/views/ReviewWorkspaceView.vue'

const jobId = 'job-1'

function createDeferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((innerResolve, innerReject) => {
    resolve = innerResolve
    reject = innerReject
  })

  return { promise, resolve, reject }
}

function mockViewportWidth(width: number) {
  const originalMatchMedia = window.matchMedia

  Object.defineProperty(window, 'innerWidth', {
    configurable: true,
    value: width
  })

  window.matchMedia = vi.fn().mockImplementation((query: string): MediaQueryList => {
    const matches =
    query === '(max-width: 1100px)'
      ? width <= 1100
        : query === '(prefers-reduced-motion: reduce)'
          ? false
          : false

    return {
      matches,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn()
    } as unknown as MediaQueryList
  })

  return () => {
    window.matchMedia = originalMatchMedia
  }
}

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
        text: '甲😀乙错误',
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
        start: 3,
        end: 5,
        original: '错误',
        message: '发现错词',
        context: '甲😀乙错误'
      })
    ],
    next_cursor: null,
    checker_failures: {},
    ...overrides
  }
}

function buildIssueSequence(start: number, end: number): Issue[] {
  return Array.from({ length: end - start + 1 }, (_, index) => {
    const issueNumber = start + index
    return buildIssue({
      issue_id: `issue-${issueNumber}`,
      original: `问题 ${issueNumber}`,
      message: `问题说明 ${issueNumber}`
    })
  })
}

function buildAppliedResponse(decision: IssueDecision): DecisionBatchResponse {
  return {
    outcomes: [
      {
        issue_id: decision.issue_id,
        status: 'applied',
        code: null,
        decision
      }
    ]
  }
}

function createAnalysisApiMock(overrides: Partial<AnalysisApi> = {}): AnalysisApi {
  return {
    getSummary: vi.fn().mockResolvedValue(buildSummary()),
    getDocumentPage: vi.fn().mockResolvedValue(buildDocumentPage()),
    getIssues: vi.fn().mockResolvedValue(buildIssuePage()),
    putDecisions: vi.fn(),
    ...overrides
  }
}

function buildExportWarning(overrides: Partial<ExportWarning> = {}): ExportWarning {
  return {
    code: 'unsafe_docx_run_boundary',
    message: '修改范围跨越多个 DOCX 文本运行，为保留格式已跳过；请在原文中手动修改后重新导出。',
    issue_id: 'issue-1',
    block_id: 'block-1',
    ...overrides
  }
}

function buildExport(overrides: Partial<ExportResponse> = {}): ExportResponse {
  const now = Date.now()

  return {
    export_id: 'export-1',
    job_id: jobId,
    export_type: 'html_report',
    status: 'queued',
    file_name: 'report.html',
    warnings: [],
    error_code: null,
    error_message: null,
    created_at: new Date(now).toISOString(),
    updated_at: new Date(now).toISOString(),
    expires_at: new Date(now + 60 * 60 * 1000).toISOString(),
    ...overrides
  }
}

function buildCreatedExport(
  overrides: Partial<ExportCreateResponse> = {}
): ExportCreateResponse {
  return {
    ...buildExport(overrides),
    dispatch_status: 'dispatched',
    ...overrides
  }
}

function createExportsApiMock(overrides: Partial<ExportsApi> = {}): ExportsApi {
  return {
    create: vi.fn().mockResolvedValue(buildCreatedExport()),
    get: vi.fn().mockResolvedValue(buildExport({ status: 'completed' })),
    downloadUrl: vi.fn().mockImplementation(
      (requestedJobId: string, exportId: string) =>
        `/api/v1/jobs/${requestedJobId}/exports/${exportId}/download`
    ),
    ...overrides
  }
}

function mountReviewWorkspaceWithConfig({
  analysisApi = createAnalysisApiMock(),
  observerFactory,
  exportsApi = createExportsApiMock(),
  props = {},
  attachTo
}: {
  analysisApi?: AnalysisApi
  observerFactory?: ReviewIntersectionObserverFactory
  exportsApi?: ExportsApi
  props?: Partial<{
    jobId: string
    sourceName: string
    fileType: FileType
  }>
  attachTo?: HTMLElement
} = {}) {
  const provide: Record<symbol, unknown> = {
    [analysisApiKey as symbol]: analysisApi,
    [exportsApiKey as symbol]: exportsApi
  }

  if (observerFactory) {
    provide[reviewIntersectionObserverFactoryKey as symbol] = observerFactory
  }

  return mount(ReviewWorkspaceView, {
    props: {
      jobId,
      sourceName: 'sample.txt',
      fileType: 'txt',
      ...props
    },
    global: { provide },
    attachTo
  })
}

function mountReviewWorkspace(
  analysisApi = createAnalysisApiMock(),
  observerFactory?: ReviewIntersectionObserverFactory,
  exportsApi = createExportsApiMock()
) {
  return mountReviewWorkspaceWithConfig({
    analysisApi,
    observerFactory,
    exportsApi
  })
}

function buildConnectedOverlapAnalysisApi(): AnalysisApi {
  return createAnalysisApiMock({
    getDocumentPage: vi.fn().mockResolvedValue(
      buildDocumentPage({
        blocks: [buildBlock({ text: '012345678' })],
        total_blocks: 1
      })
    ),
    getIssues: vi.fn().mockResolvedValue(
      buildIssuePage({
        total: 4,
        items: [
          buildIssue({
            issue_id: 'issue-outside',
            start: 0,
            end: 1,
            original: '0',
            context: '012345678'
          }),
          buildIssue({
            issue_id: 'issue-a',
            start: 1,
            end: 4,
            original: '123',
            context: '012345678'
          }),
          buildIssue({
            issue_id: 'issue-b',
            start: 3,
            end: 6,
            original: '345',
            context: '012345678'
          }),
          buildIssue({
            issue_id: 'issue-c',
            start: 5,
            end: 8,
            original: '567',
            context: '012345678'
          })
        ]
      })
    )
  })
}

function connectedClusterHighlights(wrapper: ReturnType<typeof mount>) {
  return wrapper.findAll('[data-highlight-range-issue-ids="issue-a issue-b issue-c"]')
}

const ReviewWorkspaceStateHarness = defineComponent({
  components: { ReviewNavigation },
  setup() {
    const workspace = useReviewWorkspace(jobId)

    return {
      ...workspace,
      applyErrorFilter: () => workspace.setFilters({ severity: 'error' })
    }
  },
  template: `
    <ReviewNavigation
      :summary="summary"
      :issues="issues"
      :issue-status-by-id="issueStatusById"
      :selected-issue-id="selectedIssueId"
      :loading="loading.issues"
      :error="errors.issues"
      :filters="filters"
      :next-cursor="issueCursor"
      @select="selectIssue"
      @retry="retryIssues"
      @load-next="loadNextIssues"
      @filter-change="setFilters"
    />
    <button type="button" data-testid="load-next-issues" @click="loadNextIssues">
      Load next issues
    </button>
    <button type="button" data-testid="apply-error-filter" @click="applyErrorFilter">
      Apply error filter
    </button>
  `
})

function mountReviewWorkspaceState(analysisApi: AnalysisApi) {
  return mount(ReviewWorkspaceStateHarness, {
    global: {
      provide: {
        [analysisApiKey as symbol]: analysisApi
      }
    }
  })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('ReviewWorkspaceView', () => {
  it('does not offer modified document export for PDF', async () => {
    const wrapper = mountReviewWorkspaceWithConfig({
      props: {
        sourceName: 'sample.pdf',
        fileType: 'pdf'
      }
    })
    await flushPromises()

    expect(wrapper.find('option[value="modified_document"]').exists()).toBe(false)
    expect(wrapper.find('option[value="html_report"]').exists()).toBe(true)
    expect(wrapper.find('option[value="pdf_report"]').exists()).toBe(true)
  })

  it('creates, polls, and exposes a completed export download', async () => {
    vi.useFakeTimers()

    try {
      const create = vi.fn().mockResolvedValue(
        buildCreatedExport({
          export_id: 'export-1',
          export_type: 'html_report',
          status: 'queued',
          file_name: 'report.html'
        })
      )
      const get = vi
        .fn()
        .mockResolvedValueOnce(
          buildExport({
            export_id: 'export-1',
            export_type: 'html_report',
            status: 'processing',
            file_name: 'report.html'
          })
        )
        .mockResolvedValueOnce(
          buildExport({
            export_id: 'export-1',
            export_type: 'html_report',
            status: 'completed',
            file_name: 'report.html'
          })
        )
      const downloadUrl = vi
        .fn()
        .mockReturnValue('/api/v1/jobs/job-1/exports/export-1/download')
      const wrapper = mountReviewWorkspaceWithConfig({
        exportsApi: createExportsApiMock({ create, get, downloadUrl })
      })
      await flushPromises()

      await wrapper.get('select[name="export-type"]').setValue('html_report')
      await wrapper.get('button[name="create-export"]').trigger('click')
      await flushPromises()

      expect(create).toHaveBeenCalledWith(jobId, {
        type: 'html_report',
        confirm_warnings: false
      })
      expect(wrapper.get('[data-testid="export-status"]').text()).toContain('排队')

      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()

      expect(get).toHaveBeenCalledTimes(1)
      expect(wrapper.get('[data-testid="export-status"]').text()).toContain('处理中')

      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()

      expect(get).toHaveBeenCalledTimes(2)
      expect(wrapper.get('[data-testid="export-download-link"]').attributes('href')).toBe(
        '/api/v1/jobs/job-1/exports/export-1/download'
      )
      expect(wrapper.get('[data-testid="export-download-link"]').attributes('download')).toBe(
        'report.html'
      )
    } finally {
      vi.useRealTimers()
    }
  })

  it('removes the download link once a completed export expires', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-18T00:00:00Z'))

    try {
      const create = vi.fn().mockResolvedValue(
        buildCreatedExport({
          export_id: 'export-1',
          export_type: 'html_report',
          status: 'completed',
          file_name: 'report.html',
          expires_at: '2026-08-18T00:00:02Z'
        })
      )
      const get = vi.fn()
      const downloadUrl = vi
        .fn()
        .mockReturnValue('/api/v1/jobs/job-1/exports/export-1/download')
      const wrapper = mountReviewWorkspaceWithConfig({
        exportsApi: createExportsApiMock({ create, get, downloadUrl })
      })
      await flushPromises()

      await wrapper.get('select[name="export-type"]').setValue('html_report')
      await wrapper.get('button[name="create-export"]').trigger('click')
      await flushPromises()

      expect(wrapper.get('[data-testid="export-download-link"]').attributes('href')).toBe(
        '/api/v1/jobs/job-1/exports/export-1/download'
      )
      expect(wrapper.find('[data-testid="export-error"]').exists()).toBe(false)

      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()

      expect(get).not.toHaveBeenCalled()
      expect(wrapper.find('[data-testid="export-download-link"]').exists()).toBe(false)
      expect(wrapper.get('[data-testid="export-error"]').text()).toContain(
        '导出文件已过期，请重新创建。'
      )
      expect(wrapper.get('button[name="retry-export"]').text()).toContain('重新导出')
    } finally {
      vi.useRealTimers()
    }
  })

  it('clears a completed export when the selected format changes', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-18T00:00:00Z'))

    try {
      const create = vi.fn().mockResolvedValue(
        buildCreatedExport({
          export_id: 'export-1',
          export_type: 'html_report',
          status: 'completed',
          file_name: 'report.html',
          expires_at: '2026-08-18T00:00:02Z'
        })
      )
      const wrapper = mountReviewWorkspaceWithConfig({
        exportsApi: createExportsApiMock({ create })
      })
      await flushPromises()

      await wrapper.get('select[name="export-type"]').setValue('html_report')
      await wrapper.get('button[name="create-export"]').trigger('click')
      await flushPromises()

      expect(wrapper.get('[data-testid="export-status"]').text()).toContain('已生成')
      expect(wrapper.find('[data-testid="export-download-link"]').exists()).toBe(true)

      await wrapper.get('select[name="export-type"]').setValue('pdf_report')
      await flushPromises()

      expect(wrapper.find('[data-testid="export-status"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="export-download-link"]').exists()).toBe(false)

      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()

      expect(wrapper.find('[data-testid="export-error"]').exists()).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('surfaces terminal export failures and lets the user retry', async () => {
    vi.useFakeTimers()

    try {
      const create = vi
        .fn()
        .mockResolvedValueOnce(
          buildCreatedExport({
            export_id: 'export-1',
            export_type: 'html_report',
            status: 'queued',
            file_name: 'report.html'
          })
        )
        .mockResolvedValueOnce(
          buildCreatedExport({
            export_id: 'export-2',
            export_type: 'html_report',
            status: 'completed',
            file_name: 'report-2.html'
          })
        )
      const get = vi.fn().mockResolvedValue(
        buildExport({
          export_id: 'export-1',
          export_type: 'html_report',
          status: 'failed',
          file_name: 'report.html',
          error_code: 'export_failed',
          error_message: '导出失败，请稍后重试。'
        })
      )
      const downloadUrl = vi.fn().mockImplementation(
        (_requestedJobId: string, exportId: string) =>
          `/api/v1/jobs/job-1/exports/${exportId}/download`
      )
      const wrapper = mountReviewWorkspaceWithConfig({
        exportsApi: createExportsApiMock({ create, get, downloadUrl })
      })
      await flushPromises()

      await wrapper.get('select[name="export-type"]').setValue('html_report')
      await wrapper.get('button[name="create-export"]').trigger('click')
      await flushPromises()
      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()

      expect(wrapper.get('[data-testid="export-error"]').text()).toContain(
        '导出失败，请稍后重试。'
      )
      expect(wrapper.find('[data-testid="export-download-link"]').exists()).toBe(false)

      await wrapper.get('button[name="retry-export"]').trigger('click')
      await flushPromises()

      expect(create).toHaveBeenNthCalledWith(2, jobId, {
        type: 'html_report',
        confirm_warnings: false
      })
      expect(wrapper.get('[data-testid="export-download-link"]').attributes('href')).toBe(
        '/api/v1/jobs/job-1/exports/export-2/download'
      )
    } finally {
      vi.useRealTimers()
    }
  })

  it('stops export polling when the workspace unmounts', async () => {
    vi.useFakeTimers()

    try {
      const create = vi.fn().mockResolvedValue(
        buildCreatedExport({
          export_id: 'export-1',
          export_type: 'html_report',
          status: 'queued',
          file_name: 'report.html'
        })
      )
      const get = vi.fn().mockResolvedValue(
        buildExport({
          export_id: 'export-1',
          export_type: 'html_report',
          status: 'processing',
          file_name: 'report.html'
        })
      )
      const wrapper = mountReviewWorkspaceWithConfig({
        exportsApi: createExportsApiMock({ create, get })
      })
      await flushPromises()

      await wrapper.get('select[name="export-type"]').setValue('html_report')
      await wrapper.get('button[name="create-export"]').trigger('click')
      await flushPromises()

      await vi.advanceTimersByTimeAsync(2000)
      await flushPromises()

      expect(get).toHaveBeenCalledTimes(1)

      wrapper.unmount()
      await vi.advanceTimersByTimeAsync(10000)
      await flushPromises()

      expect(get).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('requires explicit warning confirmation before retrying a structured DOCX export', async () => {
    const create = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(409, {
          code: 'export_confirmation_required',
          message: '检测到无法自动应用的 DOCX 修改，请确认警告后重试。',
          warnings: [buildExportWarning()]
        })
      )
      .mockResolvedValueOnce(
        buildCreatedExport({
          export_id: 'export-2',
          export_type: 'modified_document',
          status: 'completed',
          file_name: 'modified_document.docx',
          warnings: [buildExportWarning()]
        })
      )
    const wrapper = mountReviewWorkspaceWithConfig({
      props: {
        sourceName: 'sample.docx',
        fileType: 'docx'
      },
      exportsApi: createExportsApiMock({ create })
    })
    await flushPromises()

    await wrapper.get('button[name="create-export"]').trigger('click')
    await flushPromises()

    expect(create).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-testid="export-warnings"]').text()).toContain(
      '检测到无法自动应用的 DOCX 修改，请确认警告后重试。'
    )
    expect(wrapper.get('[data-testid="export-warnings"]').text()).toContain(
      '修改范围跨越多个 DOCX 文本运行'
    )

    await wrapper.get('button[name="confirm-export-warnings"]').trigger('click')
    await flushPromises()

    expect(create).toHaveBeenNthCalledWith(2, jobId, {
      type: 'modified_document',
      confirm_warnings: true
    })
    expect(wrapper.get('[data-testid="export-download-link"]').attributes('download')).toBe(
      'modified_document.docx'
    )
  })

  it('renders semantic columns and synchronizes issue and highlight selection', async () => {
    const wrapper = mountReviewWorkspace()
    await flushPromises()

    expect(wrapper.find('[aria-label="文档审阅工作台"]').exists()).toBe(true)
    expect(wrapper.find('nav[aria-label="问题筛选"]').exists()).toBe(true)
    expect(wrapper.find('article[aria-label="文档内容"]').exists()).toBe(true)
    expect(wrapper.find('aside[aria-label="问题详情"]').exists()).toBe(true)
    expect(wrapper.findAll('.document-highlight-control')).toHaveLength(0)
    expect(wrapper.get('[data-testid="document-header"]').text()).toContain('sample.txt')
    expect(wrapper.get('[data-testid="document-header"]').text()).toContain(
      '2 个已加载段落'
    )
    expect(wrapper.get('[data-testid="document-header"]').text()).toContain('2 个问题')

    await wrapper.get('[data-issue-id="issue-2"]').trigger('click')

    expect(wrapper.get('[data-block-id="block-2"]').classes()).toContain(
      'document-block--active'
    )
    expect(
      wrapper.get('[data-highlight-range-issue-ids~="issue-2"]').text()
    ).toBe('错误')
    expect(
      wrapper.get('[data-highlight-range-issue-ids~="issue-2"]').attributes('aria-current')
    ).toBe('true')

    await wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').trigger('click')

    expect(wrapper.get('[data-issue-id="issue-1"]').attributes('aria-current')).toBe('true')
    expect(wrapper.get('[data-block-id="block-1"]').classes()).toContain(
      'document-block--active'
    )
  })

  it('renders authoritative category and status statistics without a footer', async () => {
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getSummary: vi.fn().mockResolvedValue(
          buildSummary({
            total_issues: 21,
            by_category: {
              character: 1,
              vocabulary: 2,
              sentence: 3,
              format: 4,
              discourse: 5,
              security: 6
            },
            by_severity: { error: 7, warning: 8, info: 6 },
            by_decision: { accepted: 2, ignored: 3, custom: 4, unreviewed: 12 }
          })
        )
      })
    )
    await flushPromises()

    const categoryOverview = wrapper.get('dl[aria-label="问题类别统计"]')
    expect(categoryOverview.get('[data-summary-category="character"]').text()).toContain(
      '文字'
    )
    expect(categoryOverview.get('[data-summary-category="character"]').text()).toContain(
      '1'
    )
    expect(categoryOverview.get('[data-summary-category="security"]').text()).toContain(
      '安全'
    )
    expect(categoryOverview.get('[data-summary-category="security"]').text()).toContain(
      '6'
    )

    const decisionOverview = wrapper.get('dl[aria-label="问题处理状态统计"]')
    expect(decisionOverview.get('[data-summary-decision="accepted"]').text()).toContain(
      '已接受'
    )
    expect(decisionOverview.get('[data-summary-decision="accepted"]').text()).toContain(
      '2'
    )
    expect(decisionOverview.get('[data-summary-decision="unreviewed"]').text()).toContain(
      '未处理'
    )
    expect(decisionOverview.get('[data-summary-decision="unreviewed"]').text()).toContain(
      '12'
    )

    expect(wrapper.find('footer[aria-label="审阅统计"]').exists()).toBe(false)
  })

  it('presents API issue types and checker categories with Chinese labels', async () => {
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getSummary: vi.fn().mockResolvedValue(
          buildSummary({
            checker_failures: {
              security: {
                code: 'checker_failed',
                message: '安全检查器启动失败'
              }
            }
          })
        ),
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            total: 2,
            items: [
              buildIssue({
                issue_id: 'issue-literal',
                type: 'literal',
                layer: 'character'
              }),
              buildIssue({
                issue_id: 'issue-dictionary',
                block_id: 'block-2',
                start: 3,
                end: 5,
                original: '错误',
                type: 'dictionary_regex',
                layer: 'security'
              })
            ]
          })
        )
      })
    )
    await flushPromises()

    expect(
      wrapper.get('[data-issue-id="issue-literal"] .issue-card__type').text()
    ).toBe('规则匹配')
    expect(
      wrapper.get('[data-issue-id="issue-dictionary"] .issue-card__type').text()
    ).toBe('词典正则')

    await wrapper.get('[data-issue-id="issue-dictionary"]').trigger('click')

    expect(wrapper.get('.issue-panel__type').text()).toBe('词典正则')
    expect(wrapper.get('aside[aria-label="问题详情"]').text()).toContain('检查类别安全')
    expect(wrapper.get('aside[aria-label="问题详情"]').text()).not.toContain(
      'character-1'
    )
    expect(wrapper.get('.checker-failures__category').text()).toBe('安全')
    expect(wrapper.get('.checker-failures__category').text()).not.toContain('security')
  })

  it('uses 文档/问题 tabs on narrow screens and preserves focus after switching', async () => {
    const restoreViewport = mockViewportWidth(480)

    try {
      const wrapper = mountReviewWorkspaceWithConfig({ attachTo: document.body })
      await flushPromises()

      const issueTab = wrapper.get('[role="tab"][aria-controls="review-issues-panel"]')

      expect(wrapper.get('[role="tablist"]').attributes('aria-label')).toBe('工作台视图')
      expect(issueTab.attributes('aria-selected')).toBe('false')
      expect(wrapper.get('[role="tabpanel"][aria-label="文档"]').attributes('aria-hidden')).toBe(
        'false'
      )
      expect(wrapper.get('[role="tabpanel"][aria-label="问题"]').attributes('aria-hidden')).toBe(
        'true'
      )

      await issueTab.trigger('click')
      await flushPromises()

      expect(issueTab.attributes('aria-selected')).toBe('true')
      expect(wrapper.get('[role="tabpanel"][aria-label="问题"]').attributes('aria-hidden')).toBe(
        'false'
      )
      expect(wrapper.get('[role="tabpanel"][aria-label="文档"]').attributes('aria-hidden')).toBe(
        'true'
      )
      expect(document.activeElement).toBe(issueTab.element)
      expect(wrapper.get('nav[aria-label="问题筛选"]').isVisible()).toBe(true)
      expect(wrapper.get('aside[aria-label="问题详情"]').isVisible()).toBe(true)
      wrapper.unmount()
    } finally {
      restoreViewport()
    }
  })

  it('moves between issues with j/k shortcuts and keeps selection synchronized', async () => {
    const wrapper = mountReviewWorkspace()
    await flushPromises()

    await wrapper.get('[aria-label="文档审阅工作台"]').trigger('keydown', { key: 'j' })

    expect(wrapper.get('[data-issue-id="issue-2"]').attributes('aria-current')).toBe('true')
    expect(wrapper.get('[data-block-id="block-2"]').classes()).toContain(
      'document-block--active'
    )
    expect(
      wrapper.get('[data-highlight-range-issue-ids~="issue-2"]').attributes('aria-current')
    ).toBe('true')

    await wrapper.get('[aria-label="文档审阅工作台"]').trigger('keydown', { key: 'k' })

    expect(wrapper.get('[data-issue-id="issue-1"]').attributes('aria-current')).toBe('true')
    expect(
      wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').attributes('aria-current')
    ).toBe('true')
  })

  it('does not trigger j/k issue navigation while typing in editable controls', async () => {
    const wrapper = mountReviewWorkspace()
    await flushPromises()

    await wrapper.get('[aria-label="搜索问题"]').trigger('keydown', { key: 'j' })
    await wrapper.get('[aria-label="自定义替换"]').trigger('keydown', { key: 'k' })

    expect(wrapper.get('[data-issue-id="issue-1"]').attributes('aria-current')).toBe('true')
    expect(
      wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').attributes('aria-current')
    ).toBe('true')
  })

  it('retries localization when the selected issue resolves before its block', async () => {
    const documentPage = createDeferred<DocumentPageResponse>()
    const scrollTo = vi.fn()
    const originalDescriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'scrollTo'
    )
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: scrollTo
    })

    try {
      const wrapper = mountReviewWorkspace(
        createAnalysisApiMock({
          getDocumentPage: vi.fn().mockReturnValue(documentPage.promise),
          getIssues: vi.fn().mockResolvedValue(
            buildIssuePage({
              total: 1,
              items: [buildIssue()]
            })
          )
        })
      )
      await flushPromises()

      const viewer = wrapper.get('.document-viewer').element
      Object.defineProperty(viewer, 'clientHeight', {
        configurable: true,
        value: 600
      })
      Object.defineProperty(viewer, 'scrollHeight', {
        configurable: true,
        value: 1200
      })

      expect(wrapper.get('[data-issue-id="issue-1"]').attributes('aria-current')).toBe(
        'true'
      )
      expect(scrollTo).not.toHaveBeenCalled()

      documentPage.resolve(
        buildDocumentPage({
          blocks: [buildBlock()],
          total_blocks: 1
        })
      )
      await flushPromises()

      expect(
        wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').attributes('aria-current')
      ).toBe('true')
      expect(scrollTo).toHaveBeenCalledTimes(1)
    } finally {
      if (originalDescriptor) {
        Object.defineProperty(
          HTMLElement.prototype,
          'scrollTo',
          originalDescriptor
        )
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, 'scrollTo')
      }
    }
  })

  it('loads sequential block pages only after selecting an issue on a later page', async () => {
    const getDocumentPage = vi
      .fn()
      .mockResolvedValueOnce(
        buildDocumentPage({
          blocks: [buildBlock()],
          total_blocks: 3,
          next_cursor: 'blocks-2'
        })
      )
      .mockResolvedValueOnce(
        buildDocumentPage({
          blocks: [
            buildBlock({
              block_id: 'block-2',
              text: '第二页文字',
              paragraph_index: 1
            })
          ],
          total_blocks: 3,
          next_cursor: 'blocks-3'
        })
      )
      .mockResolvedValueOnce(
        buildDocumentPage({
          blocks: [
            buildBlock({
              block_id: 'block-3',
              text: '第三页错误',
              paragraph_index: 2
            })
          ],
          total_blocks: 3,
          next_cursor: null
        })
      )
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getDocumentPage,
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            items: [
              buildIssue(),
              buildIssue({
                issue_id: 'issue-later',
                block_id: 'block-3',
                start: 3,
                end: 5,
                original: '错误',
                context: '第三页错误'
              })
            ]
          })
        )
      })
    )
    await flushPromises()

    expect(getDocumentPage).toHaveBeenCalledTimes(1)

    await wrapper.get('[data-issue-id="issue-later"]').trigger('click')
    await flushPromises()

    expect(getDocumentPage).toHaveBeenCalledTimes(3)
    expect(getDocumentPage).toHaveBeenNthCalledWith(2, jobId, {
      cursor: 'blocks-2',
      limit: 100
    })
    expect(getDocumentPage).toHaveBeenNthCalledWith(3, jobId, {
      cursor: 'blocks-3',
      limit: 100
    })
    expect(wrapper.get('[data-block-id="block-3"]').classes()).toContain(
      'document-block--active'
    )
    expect(
      wrapper.get('[data-highlight-range-issue-ids~="issue-later"]').attributes('aria-current')
    ).toBe('true')
  })

  it('cycles identical and nested highlights on click without duplicating text', async () => {
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getDocumentPage: vi.fn().mockResolvedValue(
          buildDocumentPage({
            blocks: [buildBlock({ text: 'abcdef' })],
            total_blocks: 1
          })
        ),
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            total: 4,
            items: [
              buildIssue({
                issue_id: 'issue-other',
                start: 0,
                end: 1,
                original: 'a',
                context: 'abcdef'
              }),
              buildIssue({
                issue_id: 'issue-outer',
                start: 1,
                end: 5,
                original: 'bcde',
                context: 'abcdef'
              }),
              buildIssue({
                issue_id: 'issue-identical',
                start: 1,
                end: 5,
                original: 'bcde',
                context: 'abcdef'
              }),
              buildIssue({
                issue_id: 'issue-nested',
                start: 2,
                end: 4,
                original: 'cd',
                context: 'abcdef'
              })
            ]
          })
        )
      })
    )
    await flushPromises()

    expect(wrapper.get('[data-block-id="block-1"]').element.textContent).toBe('abcdef')
    expect(wrapper.findAll('.document-highlight-control')).toHaveLength(0)

    expect(wrapper.get('[data-issue-id="issue-other"]').attributes('aria-current')).toBe('true')

    await wrapper
      .get('[data-highlight-range-issue-ids="issue-identical issue-outer issue-nested"]')
      .trigger('click')
    expect(
      wrapper.get('[data-issue-id="issue-identical"]').attributes('aria-current')
    ).toBe('true')

    await wrapper
      .get('[data-highlight-range-issue-ids="issue-identical issue-outer issue-nested"]')
      .trigger('click')
    expect(wrapper.get('[data-issue-id="issue-outer"]').attributes('aria-current')).toBe('true')

    await wrapper
      .get('[data-highlight-range-issue-ids="issue-identical issue-outer issue-nested"]')
      .trigger('click')
    expect(wrapper.get('[data-issue-id="issue-nested"]').attributes('aria-current')).toBe(
      'true'
    )
    const selectedHighlight = wrapper.get('[data-highlight-selected="true"]')
    expect(selectedHighlight.classes()).toContain('document-highlight-range--active')
    expect(selectedHighlight.text()).toBe('cd')
  })

  it('cycles overlapping highlights with Enter and Space and prevents Space scrolling', async () => {
    const wrapper = mountReviewWorkspaceWithConfig({
      analysisApi: createAnalysisApiMock({
        getDocumentPage: vi.fn().mockResolvedValue(
          buildDocumentPage({
            blocks: [buildBlock({ text: 'abcdef' })],
            total_blocks: 1
          })
        ),
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            total: 4,
            items: [
              buildIssue({
                issue_id: 'issue-other',
                start: 0,
                end: 1,
                original: 'a',
                context: 'abcdef'
              }),
              buildIssue({
                issue_id: 'issue-outer',
                start: 1,
                end: 5,
                original: 'bcde',
                context: 'abcdef'
              }),
              buildIssue({
                issue_id: 'issue-identical',
                start: 1,
                end: 5,
                original: 'bcde',
                context: 'abcdef'
              }),
              buildIssue({
                issue_id: 'issue-nested',
                start: 2,
                end: 4,
                original: 'cd',
                context: 'abcdef'
              })
            ]
          })
        )
      }),
      attachTo: document.body
    })
    await flushPromises()

    let overlap = wrapper.get(
      '[data-highlight-range-issue-ids="issue-identical issue-outer issue-nested"]'
    )
    let overlapElement = overlap.element as HTMLElement
    overlapElement.focus()

    const enterEvent = new KeyboardEvent('keydown', {
      key: 'Enter',
      bubbles: true,
      cancelable: true
    })
    overlapElement.dispatchEvent(enterEvent)
    await flushPromises()

    expect(wrapper.get('[data-issue-id="issue-identical"]').attributes('aria-current')).toBe(
      'true'
    )

    overlap = wrapper.get(
      '[data-highlight-range-issue-ids="issue-identical issue-outer issue-nested"]'
    )
    overlapElement = overlap.element as HTMLElement
    expect(document.activeElement).toBe(overlapElement)

    const spaceEvent = new KeyboardEvent('keydown', {
      key: ' ',
      code: 'Space',
      bubbles: true,
      cancelable: true
    })
    document.activeElement?.dispatchEvent(spaceEvent)
    await flushPromises()

    expect(spaceEvent.defaultPrevented).toBe(true)
    expect(wrapper.get('[data-issue-id="issue-outer"]').attributes('aria-current')).toBe('true')
    wrapper.unmount()
  })

  it('cycles a transitively connected overlap cluster deterministically without dropping text', async () => {
    const wrapper = mountReviewWorkspace(buildConnectedOverlapAnalysisApi())
    await flushPromises()

    expect(wrapper.get('[data-issue-id="issue-outside"]').attributes('aria-current')).toBe('true')
    expect(wrapper.get('[data-block-id="block-1"]').element.textContent).toBe('012345678')

    await connectedClusterHighlights(wrapper)[0]?.trigger('click')
    expect(wrapper.get('[data-issue-id="issue-a"]').attributes('aria-current')).toBe('true')
    expect(wrapper.get('[data-block-id="block-1"]').element.textContent).toBe('012345678')
    expect(
      connectedClusterHighlights(wrapper).filter(
        (highlight) => highlight.attributes('aria-current') === 'true'
      )
    ).toHaveLength(1)
    expect(wrapper.get('[data-highlight-selected="true"]').text()).toBe('123')

    await connectedClusterHighlights(wrapper)[0]?.trigger('click')
    expect(wrapper.get('[data-issue-id="issue-b"]').attributes('aria-current')).toBe('true')
    expect(wrapper.get('[data-block-id="block-1"]').element.textContent).toBe('012345678')
    expect(wrapper.get('[data-highlight-selected="true"]').text()).toBe('345')

    await connectedClusterHighlights(wrapper)[0]?.trigger('click')
    expect(wrapper.get('[data-issue-id="issue-c"]').attributes('aria-current')).toBe('true')
    expect(wrapper.get('[data-block-id="block-1"]').element.textContent).toBe('012345678')
    expect(wrapper.get('[data-highlight-selected="true"]').text()).toBe('567')

    await connectedClusterHighlights(wrapper)[0]?.trigger('click')
    expect(wrapper.get('[data-issue-id="issue-a"]').attributes('aria-current')).toBe('true')
    expect(wrapper.get('[data-block-id="block-1"]').element.textContent).toBe('012345678')
  })

  it('restores focus to the regrouped highlighted control after clicking a focused range', async () => {
    const wrapper = mountReviewWorkspaceWithConfig({
      analysisApi: buildConnectedOverlapAnalysisApi(),
      attachTo: document.body
    })
    await flushPromises()

    const beforeClick = connectedClusterHighlights(wrapper)[0]
    expect(beforeClick).toBeDefined()
    ;(beforeClick!.element as HTMLElement).focus()
    expect(document.activeElement).toBe(beforeClick!.element)

    await beforeClick!.trigger('pointerdown')
    await beforeClick!.trigger('click')
    await flushPromises()

    const afterClick = wrapper.find('[data-highlight-selected="true"]')
    expect(wrapper.get('[data-issue-id="issue-a"]').attributes('aria-current')).toBe('true')
    expect(afterClick).toBeDefined()
    expect(document.activeElement).toBe(afterClick!.element)
    wrapper.unmount()
  })

  it('does not restore focus when pointer activation focused an unfocused highlight', async () => {
    const wrapper = mountReviewWorkspaceWithConfig({
      analysisApi: buildConnectedOverlapAnalysisApi(),
      attachTo: document.body
    })
    await flushPromises()

    const beforeClick = connectedClusterHighlights(wrapper)[0]
    expect(beforeClick).toBeDefined()
    expect(document.activeElement).not.toBe(beforeClick!.element)

    await beforeClick!.trigger('pointerdown')
    ;(beforeClick!.element as HTMLElement).focus()
    await beforeClick!.trigger('click')
    await flushPromises()

    const afterClick = connectedClusterHighlights(wrapper)[0]
    expect(afterClick).toBeDefined()
    expect(document.activeElement).not.toBe(afterClick!.element)
    wrapper.unmount()
  })

  it('scopes selected-highlight localization to its own document viewer', async () => {
    const first = mountReviewWorkspace()
    const second = mountReviewWorkspace(
      createAnalysisApiMock({
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            items: [
              buildIssue({ issue_id: 'issue-other' }),
              buildIssue({ issue_id: 'issue-1' })
            ]
          })
        )
      })
    )
    await flushPromises()

    const firstScroll = vi.fn()
    const secondScroll = vi.fn()
    const firstViewer = first.get('.document-viewer').element
    const secondViewer = second.get('.document-viewer').element
    for (const viewer of [firstViewer, secondViewer]) {
      Object.defineProperty(viewer, 'clientHeight', {
        configurable: true,
        value: 600
      })
      Object.defineProperty(viewer, 'scrollHeight', {
        configurable: true,
        value: 1200
      })
    }
    Object.defineProperty(firstViewer, 'scrollTo', {
      configurable: true,
      value: firstScroll
    })
    Object.defineProperty(secondViewer, 'scrollTo', {
      configurable: true,
      value: secondScroll
    })

    await second.get('[data-issue-id="issue-1"]').trigger('click')
    await flushPromises()

    expect(firstScroll).not.toHaveBeenCalled()
    expect(secondScroll).toHaveBeenCalledTimes(1)
  })

  it('loads only the observer-requested next document page', async () => {
    const observerCallbacks: ReviewIntersectionObserverCallback[] = []
    const observe = vi.fn()
    const disconnect = vi.fn()
    const observerFactory: ReviewIntersectionObserverFactory = (callback) => {
      observerCallbacks.push(callback)
      return { observe, disconnect }
    }
    const getDocumentPage = vi
      .fn()
      .mockResolvedValueOnce(buildDocumentPage({ next_cursor: 'page-2' }))
      .mockResolvedValueOnce(
        buildDocumentPage({
          blocks: [
            buildBlock({
              block_id: 'block-3',
              text: '按需加载的第三段',
              paragraph_index: 2
            })
          ],
          total_blocks: 3,
          next_cursor: 'page-3'
        })
      )
    const analysisApi = createAnalysisApiMock({ getDocumentPage })
    const wrapper = mountReviewWorkspace(analysisApi, observerFactory)
    await flushPromises()

    expect(getDocumentPage).toHaveBeenCalledTimes(1)
    expect(getDocumentPage).toHaveBeenNthCalledWith(1, jobId, {
      cursor: null,
      limit: 100
    })
    expect(observe).toHaveBeenCalledTimes(1)

    observerCallbacks[0]?.([{ isIntersecting: true }])
    observerCallbacks[0]?.([{ isIntersecting: true }])
    await flushPromises()

    expect(getDocumentPage).toHaveBeenCalledTimes(2)
    expect(getDocumentPage).toHaveBeenNthCalledWith(2, jobId, {
      cursor: 'page-2',
      limit: 100
    })
    expect(wrapper.get('[data-block-id="block-3"]').text()).toContain('按需加载的第三段')
    expect(wrapper.find('[data-block-id="block-4"]').exists()).toBe(false)

    wrapper.unmount()
    expect(disconnect).toHaveBeenCalledTimes(1)
  })

  it('loads the next issue page from production navigation and announces completion', async () => {
    const nextPage = createDeferred<IssuePageResponse>()
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 2,
          items: [buildIssue()],
          next_cursor: 'issues-2'
        })
      )
      .mockReturnValueOnce(nextPage.promise)
    const wrapper = mountReviewWorkspace(createAnalysisApiMock({ getIssues }))
    await flushPromises()

    const loadMore = wrapper.get('[data-testid="load-more-issues"]')
    expect(loadMore.attributes('aria-label')).toBe('加载更多问题')

    await loadMore.trigger('click')

    expect(wrapper.get('[data-testid="issue-pagination-status"]').text()).toContain(
      '正在加载更多问题'
    )
    expect(wrapper.get('[data-issue-id="issue-1"]').attributes('aria-current')).toBe(
      'true'
    )

    nextPage.resolve(
      buildIssuePage({
        total: 2,
        items: [
          buildIssue({
            issue_id: 'issue-2',
            block_id: 'block-2',
            start: 3,
            end: 5,
            original: '第二页问题'
          })
        ],
        next_cursor: null
      })
    )
    await flushPromises()

    expect(getIssues).toHaveBeenLastCalledWith(jobId, {
      cursor: 'issues-2',
      limit: 50
    })
    expect(wrapper.find('[data-issue-id="issue-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-issue-id="issue-2"]').exists()).toBe(true)
    expect(wrapper.get('[data-issue-id="issue-1"]').attributes('aria-current')).toBe(
      'true'
    )
    expect(wrapper.find('[data-testid="load-more-issues"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="issue-pagination-status"]').text()).toContain(
      '已加载全部问题'
    )
  })

  it('keeps filtered issue state when an older append response resolves last', async () => {
    const appendedPage = createDeferred<IssuePageResponse>()
    const filteredPage = createDeferred<IssuePageResponse>()
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 3,
          items: [buildIssue()],
          next_cursor: 'issues-2'
        })
      )
      .mockReturnValueOnce(appendedPage.promise)
      .mockReturnValueOnce(filteredPage.promise)
    const wrapper = mountReviewWorkspaceState(createAnalysisApiMock({ getIssues }))
    await flushPromises()

    await wrapper.get('[data-testid="load-next-issues"]').trigger('click')
    await wrapper.get('[data-testid="apply-error-filter"]').trigger('click')

    filteredPage.resolve(
      buildIssuePage({
        total: 1,
        items: [
          buildIssue({
            issue_id: 'issue-filtered',
            severity: 'error',
            original: '筛选结果'
          })
        ]
      })
    )
    await flushPromises()

    appendedPage.resolve(
      buildIssuePage({
        total: 3,
        items: [buildIssue({ issue_id: 'issue-stale', original: '过期分页' })]
      })
    )
    await flushPromises()

    expect(getIssues).toHaveBeenNthCalledWith(2, jobId, {
      cursor: 'issues-2',
      limit: 50
    })
    expect(getIssues).toHaveBeenNthCalledWith(3, jobId, {
      severity: 'error',
      cursor: null,
      limit: 50
    })
    expect(wrapper.find('[data-issue-id="issue-filtered"]').exists()).toBe(true)
    expect(wrapper.find('[data-issue-id="issue-stale"]').exists()).toBe(false)
    expect(wrapper.find('[data-issue-id="issue-1"]').exists()).toBe(false)
  })

  it('keeps the newest issue filter response and applies categorical filters immediately', async () => {
    const categoryPage = createDeferred<IssuePageResponse>()
    const severityPage = createDeferred<IssuePageResponse>()
    const decisionPage = createDeferred<IssuePageResponse>()
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(buildIssuePage())
      .mockReturnValueOnce(categoryPage.promise)
      .mockReturnValueOnce(severityPage.promise)
      .mockReturnValueOnce(decisionPage.promise)
    const wrapper = mountReviewWorkspace(createAnalysisApiMock({ getIssues }))
    await flushPromises()

    await wrapper.get('[aria-label="问题类别"]').setValue('security')
    expect(wrapper.find('[aria-current="true"]').exists()).toBe(false)
    await wrapper.get('[aria-label="问题严重程度"]').setValue('error')
    await wrapper.get('[aria-label="问题处理状态"]').setValue('unreviewed')

    expect(getIssues).toHaveBeenNthCalledWith(2, jobId, {
      category: 'security',
      cursor: null,
      limit: 50
    })
    expect(getIssues).toHaveBeenNthCalledWith(3, jobId, {
      category: 'security',
      severity: 'error',
      cursor: null,
      limit: 50
    })
    expect(getIssues).toHaveBeenNthCalledWith(4, jobId, {
      category: 'security',
      severity: 'error',
      decision: 'unreviewed',
      cursor: null,
      limit: 50
    })

    decisionPage.resolve(
      buildIssuePage({
        total: 1,
        items: [
          buildIssue({
            issue_id: 'issue-newest-filter',
            type: 'security',
            severity: 'error',
            original: '最新筛选结果'
          })
        ]
      })
    )
    await flushPromises()
    categoryPage.resolve(
      buildIssuePage({
        items: [buildIssue({ issue_id: 'issue-stale-category', original: '过期类别' })]
      })
    )
    severityPage.resolve(
      buildIssuePage({
        items: [buildIssue({ issue_id: 'issue-stale-severity', original: '过期严重程度' })]
      })
    )
    await flushPromises()

    expect(wrapper.find('[data-issue-id="issue-newest-filter"]').exists()).toBe(true)
    expect(wrapper.find('[data-issue-id="issue-stale-category"]').exists()).toBe(false)
    expect(wrapper.find('[data-issue-id="issue-stale-severity"]').exists()).toBe(false)
  })

  it('debounces keyword issue search by exactly 250 ms', async () => {
    vi.useFakeTimers()
    try {
      const getIssues = vi.fn().mockResolvedValue(buildIssuePage())
      const wrapper = mountReviewWorkspace(createAnalysisApiMock({ getIssues }))
      await flushPromises()

      await wrapper.get('[aria-label="搜索问题"]').setValue('专业')
      expect(getIssues).toHaveBeenCalledTimes(1)

      await vi.advanceTimersByTimeAsync(249)
      expect(getIssues).toHaveBeenCalledTimes(1)

      await vi.advanceTimersByTimeAsync(1)
      await flushPromises()

      expect(getIssues).toHaveBeenCalledTimes(2)
      expect(getIssues).toHaveBeenLastCalledWith(jobId, {
        search: '专业',
        cursor: null,
        limit: 50
      })
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })

  it('sends and optimistically previews a custom replacement without mutating raw blocks', async () => {
    const decisionResponse = createDeferred<DecisionBatchResponse>()
    const putDecisions = vi.fn().mockReturnValue(decisionResponse.promise)
    const rawBlock = buildBlock()
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getDocumentPage: vi.fn().mockResolvedValue(
          buildDocumentPage({
            blocks: [rawBlock],
            total_blocks: 1
          })
        ),
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            total: 1,
            items: [buildIssue()]
          })
        ),
        putDecisions
      })
    )
    await flushPromises()

    await wrapper.get('[aria-label="自定义替换"]').setValue('专业')
    await wrapper.get('button[name="custom-decision"]').trigger('click')

    expect(putDecisions).toHaveBeenCalledWith(jobId, [
      {
        issue_id: 'issue-1',
        issue_version: 1,
        action: 'custom',
        replacement: '专业'
      }
    ])
    expect(wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').text()).toBe(
      '专业'
    )
    expect(rawBlock.text).toBe('第一段文字')
    wrapper.unmount()
  })

  it('reconciles an applied decision with the returned server decision', async () => {
    const decisionResponse = createDeferred<DecisionBatchResponse>()
    const putDecisions = vi.fn().mockReturnValue(decisionResponse.promise)
    const authoritativeDecision = {
      issue_version: 1,
      action: 'custom' as const,
      replacement: '服务器替换',
      updated_at: '2026-08-18T01:00:00Z'
    }
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(buildIssuePage())
      .mockResolvedValueOnce(
        buildIssuePage({
          items: [
            buildIssue({ decision: authoritativeDecision }),
            buildIssue({
              issue_id: 'issue-2',
              block_id: 'block-2',
              start: 3,
              end: 5,
              original: '错误',
              message: '发现错词',
              context: '甲😀乙错误'
            })
          ]
        })
      )
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({ getIssues, putDecisions })
    )
    await flushPromises()

    await wrapper.get('[aria-label="自定义替换"]').setValue('客户端替换')
    await wrapper.get('button[name="custom-decision"]').trigger('click')
    expect(wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').text()).toBe(
      '客户端替换'
    )

    decisionResponse.resolve(
      buildAppliedResponse({
        issue_id: 'issue-1',
        ...authoritativeDecision
      })
    )
    await flushPromises()

    expect(wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').text()).toBe(
      '服务器替换'
    )
    expect(wrapper.get('aside[aria-label="问题详情"]').text()).toContain('已自定义')
  })

  it('removes a successful single decision from the unreviewed filter and refreshes summary', async () => {
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(buildIssuePage())
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 1,
          items: [buildIssue()]
        })
      )
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 0,
          items: []
        })
      )
    const getSummary = vi
      .fn()
      .mockResolvedValueOnce(buildSummary())
      .mockResolvedValueOnce(
        buildSummary({
          by_decision: { accepted: 1, ignored: 0, custom: 0, unreviewed: 1 }
        })
      )
    const putDecisions = vi.fn().mockResolvedValue(
      buildAppliedResponse({
        issue_id: 'issue-1',
        issue_version: 1,
        action: 'accepted',
        replacement: null,
        updated_at: '2026-08-18T01:00:00Z'
      })
    )
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({ getIssues, getSummary, putDecisions })
    )
    await flushPromises()

    await wrapper.get('[aria-label="问题处理状态"]').setValue('unreviewed')
    await flushPromises()
    await wrapper.get('button[name="accept"]').trigger('click')
    await flushPromises()

    expect(getIssues).toHaveBeenCalledTimes(3)
    expect(getIssues).toHaveBeenLastCalledWith(jobId, {
      decision: 'unreviewed',
      cursor: null,
      limit: 50
    })
    expect(getSummary).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-issue-id="issue-1"]').exists()).toBe(false)
  })

  it('applies the authoritative filtered first page before advancing its cursor', async () => {
    const filteredIssues = buildIssueSequence(1, 50)
    const authoritativeIssues = [
      ...buildIssueSequence(3, 50),
      ...buildIssueSequence(2, 2),
      ...buildIssueSequence(51, 51)
    ]
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(buildIssuePage())
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 52,
          items: filteredIssues,
          next_cursor: 'issues-before-decision'
        })
      )
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 51,
          items: authoritativeIssues,
          next_cursor: 'issues-after-decision'
        })
      )
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 51,
          items: buildIssueSequence(52, 52),
          next_cursor: null
        })
      )
    const putDecisions = vi.fn().mockResolvedValue(
      buildAppliedResponse({
        issue_id: 'issue-1',
        issue_version: 1,
        action: 'accepted',
        replacement: null,
        updated_at: '2026-08-18T01:00:00Z'
      })
    )
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({ getIssues, putDecisions })
    )
    await flushPromises()

    await wrapper.get('[aria-label="问题处理状态"]').setValue('unreviewed')
    await flushPromises()
    await wrapper.get('button[name="accept"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-issue-id="issue-1"]').exists()).toBe(false)
    expect(wrapper.find('[data-issue-id="issue-51"]').exists()).toBe(true)
    expect(
      wrapper.findAll('[data-issue-id]').map((issue) => issue.attributes('data-issue-id'))
    ).toEqual(authoritativeIssues.map((issue) => issue.issue_id))

    await wrapper.get('[data-testid="load-more-issues"]').trigger('click')
    await flushPromises()

    expect(getIssues).toHaveBeenLastCalledWith(jobId, {
      decision: 'unreviewed',
      cursor: 'issues-after-decision',
      limit: 50
    })
    expect(wrapper.find('[data-issue-id="issue-52"]').exists()).toBe(true)
  })

  it('preserves an unrelated newer decision while applying a stale authoritative page and cursor', async () => {
    const authoritativeReload = createDeferred<IssuePageResponse>()
    const newerDecisionResponse = createDeferred<DecisionBatchResponse>()
    const acceptedDecision = {
      issue_version: 1,
      action: 'accepted' as const,
      replacement: null,
      updated_at: '2026-08-18T01:00:00Z'
    }
    const ignoredDecision = {
      issue_version: 1,
      action: 'ignored' as const,
      replacement: null,
      updated_at: '2026-08-18T01:01:00Z'
    }
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(
        buildIssuePage({
          next_cursor: 'issues-before-decision'
        })
      )
      .mockReturnValueOnce(authoritativeReload.promise)
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 4,
          items: buildIssueSequence(4, 4),
          next_cursor: null
        })
      )
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 3,
          items: [
            buildIssue({
              issue_id: 'issue-3',
              original: '问题 3',
              message: '回填问题'
            }),
            buildIssue({
              decision: acceptedDecision
            }),
            buildIssue({
              issue_id: 'issue-2',
              block_id: 'block-2',
              start: 3,
              end: 5,
              original: '错误',
              message: '发现错词',
              context: '甲😀乙错误',
              decision: ignoredDecision
            })
          ],
          next_cursor: 'issues-after-newer-decision'
        })
      )
    const putDecisions = vi
      .fn()
      .mockResolvedValueOnce(
        buildAppliedResponse({
          issue_id: 'issue-1',
          ...acceptedDecision
        })
      )
      .mockReturnValueOnce(newerDecisionResponse.promise)
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({ getIssues, putDecisions })
    )
    await flushPromises()

    await wrapper.get('button[name="accept"]').trigger('click')
    await flushPromises()

    expect(getIssues).toHaveBeenCalledTimes(2)

    await wrapper.get('[data-issue-id="issue-2"]').trigger('click')
    await wrapper.get('button[name="ignore"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-issue-id="issue-2"]').text()).toContain('已忽略')

    authoritativeReload.resolve(
      buildIssuePage({
        total: 4,
        items: [
          buildIssue({
            issue_id: 'issue-3',
            original: '问题 3',
            message: '回填问题'
          }),
          buildIssue({
            decision: acceptedDecision
          })
        ],
        next_cursor: 'issues-after-stale-reload'
      })
    )
    await flushPromises()

    expect(
      wrapper.findAll('[data-issue-id]').map((issue) => issue.attributes('data-issue-id'))
    ).toEqual(['issue-3', 'issue-1', 'issue-2'])
    expect(wrapper.get('[data-issue-id="issue-2"]').text()).toContain('已忽略')

    await wrapper.get('[data-testid="load-more-issues"]').trigger('click')
    await flushPromises()

    expect(getIssues).toHaveBeenNthCalledWith(3, jobId, {
      cursor: 'issues-after-stale-reload',
      limit: 50
    })
    expect(wrapper.find('[data-issue-id="issue-4"]').exists()).toBe(true)

    newerDecisionResponse.resolve(
      buildAppliedResponse({
        issue_id: 'issue-2',
        ...ignoredDecision
      })
    )
    await flushPromises()

    expect(wrapper.get('[data-issue-id="issue-2"]').text()).toContain('已忽略')
  })

  it('removes an all-applied batch from the unreviewed filter and refreshes summary', async () => {
    const filteredIssues = [
      buildIssue(),
      buildIssue({
        issue_id: 'issue-2',
        block_id: 'block-2',
        start: 3,
        end: 5,
        original: '错误'
      })
    ]
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(buildIssuePage())
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 2,
          items: filteredIssues
        })
      )
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 0,
          items: []
        })
      )
    const getSummary = vi
      .fn()
      .mockResolvedValueOnce(buildSummary())
      .mockResolvedValueOnce(
        buildSummary({
          by_decision: { accepted: 2, ignored: 0, custom: 0, unreviewed: 0 }
        })
      )
    const putDecisions = vi.fn().mockResolvedValue({
      outcomes: filteredIssues.map((issue) => ({
        issue_id: issue.issue_id,
        status: 'applied' as const,
        code: null,
        decision: {
          issue_id: issue.issue_id,
          issue_version: 1,
          action: 'accepted' as const,
          replacement: null,
          updated_at: '2026-08-18T01:00:00Z'
        }
      }))
    } satisfies DecisionBatchResponse)
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({ getIssues, getSummary, putDecisions })
    )
    await flushPromises()

    await wrapper.get('[aria-label="问题处理状态"]').setValue('unreviewed')
    await flushPromises()
    await wrapper.get('button[name="accept-visible"]').trigger('click')
    await flushPromises()

    expect(getIssues).toHaveBeenCalledTimes(3)
    expect(getIssues).toHaveBeenLastCalledWith(jobId, {
      decision: 'unreviewed',
      cursor: null,
      limit: 50
    })
    expect(getSummary).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('[data-issue-id]')).toHaveLength(0)
  })

  it('keeps authoritative pagination reachable when all applied rows leave the page empty', async () => {
    const filteredIssues = buildIssueSequence(1, 2)
    const nextPage = createDeferred<IssuePageResponse>()
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(buildIssuePage())
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 3,
          items: filteredIssues,
          next_cursor: 'issues-before-decision'
        })
      )
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 1,
          items: [],
          next_cursor: 'issues-after-empty-page'
        })
      )
      .mockReturnValueOnce(nextPage.promise)
    const putDecisions = vi.fn().mockResolvedValue({
      outcomes: filteredIssues.map((issue) => ({
        issue_id: issue.issue_id,
        status: 'applied' as const,
        code: null,
        decision: {
          issue_id: issue.issue_id,
          issue_version: 1,
          action: 'accepted' as const,
          replacement: null,
          updated_at: '2026-08-18T01:00:00Z'
        }
      }))
    } satisfies DecisionBatchResponse)
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({ getIssues, putDecisions })
    )
    await flushPromises()

    await wrapper.get('[aria-label="问题处理状态"]').setValue('unreviewed')
    await flushPromises()
    await wrapper.get('button[name="accept-visible"]').trigger('click')
    await flushPromises()

    expect(wrapper.findAll('[data-issue-id]')).toHaveLength(0)
    expect(wrapper.find('[data-testid="empty-issues"]').exists()).toBe(false)

    await wrapper.get('[data-testid="load-more-issues"]').trigger('click')

    expect(
      wrapper
        .getComponent(ReviewNavigation)
        .findAll('[role="status"]')
        .map((status) => status.text())
        .filter((status) => status.includes('正在加载'))
    ).toEqual(['正在加载更多问题…'])

    nextPage.resolve(
      buildIssuePage({
        total: 1,
        items: buildIssueSequence(3, 3),
        next_cursor: null
      })
    )
    await flushPromises()

    expect(getIssues).toHaveBeenLastCalledWith(jobId, {
      decision: 'unreviewed',
      cursor: 'issues-after-empty-page',
      limit: 50
    })
    expect(wrapper.find('[data-issue-id="issue-3"]').exists()).toBe(true)
  })

  it('reloads authoritative state and announces a decision conflict', async () => {
    const authoritativeIssue = buildIssue({
      decision: {
        issue_version: 1,
        action: 'ignored',
        replacement: null,
        updated_at: '2026-08-18T01:00:00Z'
      }
    })
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 1,
          items: [buildIssue()]
        })
      )
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 1,
          items: [authoritativeIssue]
        })
      )
    const getSummary = vi
      .fn()
      .mockResolvedValueOnce(buildSummary())
      .mockResolvedValueOnce(
        buildSummary({
          by_decision: { accepted: 0, ignored: 1, custom: 0, unreviewed: 1 }
        })
      )
    const putDecisions = vi.fn().mockResolvedValue({
      outcomes: [
        {
          issue_id: 'issue-1',
          status: 'conflict',
          code: 'stale_issue_version',
          decision: null
        }
      ]
    } satisfies DecisionBatchResponse)
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({ getIssues, getSummary, putDecisions })
    )
    await flushPromises()

    await wrapper.get('button[name="accept"]').trigger('click')
    await flushPromises()

    expect(getIssues).toHaveBeenCalledTimes(2)
    expect(getIssues).toHaveBeenLastCalledWith(jobId, {
      cursor: null,
      limit: 50
    })
    expect(getSummary).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[aria-live="polite"]').text()).toContain(
      '结果已更新，请重新确认'
    )
    expect(wrapper.get('aside[aria-label="问题详情"]').text()).toContain('已忽略')
  })

  it('reloads authoritative issue and summary state after an invalid decision', async () => {
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(buildIssuePage())
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 1,
          items: [buildIssue({ suggestion: '服务器新建议' })]
        })
      )
    const getSummary = vi
      .fn()
      .mockResolvedValueOnce(buildSummary())
      .mockResolvedValueOnce(buildSummary({ total_issues: 1 }))
    const putDecisions = vi.fn().mockResolvedValue({
      outcomes: [
        {
          issue_id: 'issue-1',
          status: 'invalid',
          code: 'issue_not_found',
          decision: null
        }
      ]
    } satisfies DecisionBatchResponse)
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({ getIssues, getSummary, putDecisions })
    )
    await flushPromises()

    await wrapper.get('button[name="ignore"]').trigger('click')
    await flushPromises()

    expect(getIssues).toHaveBeenCalledTimes(2)
    expect(getSummary).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[aria-live="polite"]').text()).toContain(
      '结果已更新，请重新确认'
    )
  })

  it('reconciles batch conflict and invalid outcomes with authoritative issue state', async () => {
    const acceptedDecision = {
      issue_version: 1,
      action: 'accepted' as const,
      replacement: null,
      updated_at: '2026-08-18T02:00:00Z'
    }
    const ignoredDecision = {
      issue_version: 1,
      action: 'ignored' as const,
      replacement: null,
      updated_at: '2026-08-18T02:01:00Z'
    }
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 3,
          items: [
            buildIssue(),
            buildIssue({
              issue_id: 'issue-2',
              block_id: 'block-2',
              start: 3,
              end: 5,
              original: '冲突项',
              message: '需要重新确认'
            }),
            buildIssue({
              issue_id: 'issue-3',
              block_id: 'block-2',
              start: 0,
              end: 2,
              original: '失效项',
              message: '服务器已移除'
            })
          ]
        })
      )
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 2,
          items: [
            buildIssue({
              decision: acceptedDecision
            }),
            buildIssue({
              issue_id: 'issue-2',
              block_id: 'block-2',
              start: 3,
              end: 5,
              original: '冲突项',
              message: '服务器已忽略',
              decision: ignoredDecision
            })
          ]
        })
      )
    const getSummary = vi
      .fn()
      .mockResolvedValueOnce(buildSummary({ total_issues: 3 }))
      .mockResolvedValueOnce(
        buildSummary({
          total_issues: 2,
          by_decision: { accepted: 1, ignored: 1, custom: 0, unreviewed: 0 }
        })
      )
    const putDecisions = vi.fn().mockResolvedValue({
      outcomes: [
        {
          issue_id: 'issue-1',
          status: 'applied',
          code: null,
          decision: {
            issue_id: 'issue-1',
            ...acceptedDecision
          }
        },
        {
          issue_id: 'issue-2',
          status: 'conflict',
          code: 'stale_issue_version',
          decision: null
        },
        {
          issue_id: 'issue-3',
          status: 'invalid',
          code: 'issue_not_found',
          decision: null
        }
      ]
    } satisfies DecisionBatchResponse)
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({ getIssues, getSummary, putDecisions })
    )
    await flushPromises()

    await wrapper.get('button[name="accept-visible"]').trigger('click')
    await flushPromises()

    expect(putDecisions).toHaveBeenCalledWith(jobId, [
      {
        issue_id: 'issue-1',
        issue_version: 1,
        action: 'accepted'
      },
      {
        issue_id: 'issue-2',
        issue_version: 1,
        action: 'accepted'
      },
      {
        issue_id: 'issue-3',
        issue_version: 1,
        action: 'accepted'
      }
    ])
    expect(getIssues).toHaveBeenCalledTimes(2)
    expect(getIssues).toHaveBeenLastCalledWith(jobId, {
      cursor: null,
      limit: 50
    })
    expect(getSummary).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-issue-id="issue-1"]').text()).toContain('已接受')
    expect(wrapper.get('[data-issue-id="issue-2"]').text()).toContain('已忽略')
    expect(wrapper.find('[data-issue-id="issue-3"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="decision-announcement"]').text()).toContain(
      '成功 1 项，需重新确认 2 项'
    )
  })

  it('reconciles still-current batch reload siblings when another conflicted issue is re-decided', async () => {
    const batchAcceptedDecision = {
      issue_version: 1,
      action: 'accepted' as const,
      replacement: null,
      updated_at: '2026-08-18T03:00:00Z'
    }
    const newerIgnoredDecision = {
      issue_version: 1,
      action: 'ignored' as const,
      replacement: null,
      updated_at: '2026-08-18T03:01:00Z'
    }
    const authoritativeBatchReload = createDeferred<IssuePageResponse>()
    const newerDecisionRequest = createDeferred<DecisionBatchResponse>()
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 3,
          items: [
            buildIssue(),
            buildIssue({
              issue_id: 'issue-2',
              block_id: 'block-2',
              start: 3,
              end: 5,
              original: '冲突项',
              message: '需要重新确认'
            }),
            buildIssue({
              issue_id: 'issue-3',
              block_id: 'block-2',
              start: 0,
              end: 2,
              original: '失效项',
              message: '服务器已移除'
            })
          ]
        })
      )
      .mockReturnValueOnce(authoritativeBatchReload.promise)
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 2,
          items: [
            buildIssue({
              decision: batchAcceptedDecision
            }),
            buildIssue({
              issue_id: 'issue-2',
              block_id: 'block-2',
              start: 3,
              end: 5,
              original: '冲突项',
              message: '服务器已保存新决定',
              decision: newerIgnoredDecision
            })
          ]
        })
      )
    const putDecisions = vi
      .fn()
      .mockResolvedValueOnce({
        outcomes: [
          {
            issue_id: 'issue-1',
            status: 'applied',
            code: null,
            decision: {
              issue_id: 'issue-1',
              ...batchAcceptedDecision
            }
          },
          {
            issue_id: 'issue-2',
            status: 'conflict',
            code: 'stale_issue_version',
            decision: null
          },
          {
            issue_id: 'issue-3',
            status: 'invalid',
            code: 'issue_not_found',
            decision: null
          }
        ]
      } satisfies DecisionBatchResponse)
      .mockReturnValueOnce(newerDecisionRequest.promise)
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getIssues,
        getSummary: vi
          .fn()
          .mockResolvedValueOnce(buildSummary({ total_issues: 3 }))
          .mockResolvedValueOnce(buildSummary({ total_issues: 2 }))
          .mockResolvedValueOnce(buildSummary({ total_issues: 2 })),
        putDecisions
      })
    )
    await flushPromises()

    await wrapper.get('button[name="accept-visible"]').trigger('click')
    await flushPromises()

    expect(getIssues).toHaveBeenCalledTimes(2)

    await wrapper.get('[data-issue-id="issue-2"]').trigger('click')
    await wrapper.get('button[name="ignore"]').trigger('click')
    await flushPromises()

    expect(putDecisions).toHaveBeenNthCalledWith(2, jobId, [
      {
        issue_id: 'issue-2',
        issue_version: 1,
        action: 'ignored'
      }
    ])

    authoritativeBatchReload.resolve(
      buildIssuePage({
        total: 2,
        items: [
          buildIssue({
            decision: batchAcceptedDecision
          }),
          buildIssue({
            issue_id: 'issue-2',
            block_id: 'block-2',
            start: 3,
            end: 5,
            original: '冲突项',
            message: '服务器仍是旧状态',
            decision: batchAcceptedDecision
          })
        ]
      })
    )
    await flushPromises()

    expect(wrapper.get('[data-issue-id="issue-2"]').text()).toContain('已忽略')
    expect(wrapper.find('[data-issue-id="issue-3"]').exists()).toBe(false)

    newerDecisionRequest.resolve({
      outcomes: [
        {
          issue_id: 'issue-2',
          status: 'applied',
          code: null,
          decision: {
            issue_id: 'issue-2',
            ...newerIgnoredDecision
          }
        }
      ]
    } satisfies DecisionBatchResponse)
    await flushPromises()

    expect(wrapper.get('[data-issue-id="issue-2"]').text()).toContain('已忽略')
  })

  it('does not submit stale visible issues while a filter request is in flight', async () => {
    const filteredPage = createDeferred<IssuePageResponse>()
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(buildIssuePage())
      .mockReturnValueOnce(filteredPage.promise)
    const putDecisions = vi.fn().mockResolvedValue({ outcomes: [] } satisfies DecisionBatchResponse)
    const wrapper = mountReviewWorkspace(createAnalysisApiMock({ getIssues, putDecisions }))
    await flushPromises()

    await wrapper.get('[aria-label="问题严重程度"]').setValue('error')
    await flushPromises()

    const acceptVisible = wrapper.get('button[name="accept-visible"]')
    expect(acceptVisible.attributes('disabled')).toBeDefined()

    await acceptVisible.trigger('click')
    expect(putDecisions).not.toHaveBeenCalled()

    filteredPage.resolve(
      buildIssuePage({
        total: 1,
        items: [
          buildIssue({
            issue_id: 'issue-error',
            severity: 'error',
            original: '筛选后的问题'
          })
        ]
      })
    )
    await flushPromises()

    await wrapper.get('button[name="accept-visible"]').trigger('click')

    expect(putDecisions).toHaveBeenCalledWith(jobId, [
      {
        issue_id: 'issue-error',
        issue_version: 1,
        action: 'accepted'
      }
    ])
  })

  it('asks confirmation for API-shaped high-risk security issues', async () => {
    const originalConfirm = globalThis.confirm
    const confirm = vi.fn().mockReturnValue(false)
    globalThis.confirm = confirm

    try {
      const putDecisions = vi.fn()
      const wrapper = mountReviewWorkspace(
        createAnalysisApiMock({
          getIssues: vi.fn().mockResolvedValue(
            buildIssuePage({
              total: 2,
              items: [
                buildIssue({
                  issue_id: 'issue-security',
                  type: 'literal',
                  layer: 'security',
                  severity: 'error',
                  original: '敏感信息'
                }),
                buildIssue({
                  issue_id: 'issue-2',
                  block_id: 'block-2',
                  start: 3,
                  end: 5,
                  original: '错误',
                  message: '发现错词'
                })
              ]
            })
          ),
          putDecisions
        })
      )
      await flushPromises()

      await wrapper.get('button[name="accept-visible"]').trigger('click')

      expect(confirm).toHaveBeenCalledWith('当前包含 1 个高风险安全问题，确认批量接受建议吗？')
      expect(putDecisions).not.toHaveBeenCalled()
    } finally {
      globalThis.confirm = originalConfirm
    }
  })

  it('rejects high-risk batch acceptance when confirm is unavailable', async () => {
    const originalConfirm = globalThis.confirm
    Object.defineProperty(globalThis, 'confirm', {
      configurable: true,
      value: undefined
    })

    try {
      const putDecisions = vi.fn()
      const wrapper = mountReviewWorkspace(
        createAnalysisApiMock({
          getIssues: vi.fn().mockResolvedValue(
            buildIssuePage({
              total: 1,
              items: [
                buildIssue({
                  issue_id: 'issue-security',
                  type: 'literal',
                  layer: 'security',
                  severity: 'error',
                  original: '敏感信息'
                })
              ]
            })
          ),
          putDecisions
        })
      )
      await flushPromises()

      await wrapper.get('button[name="accept-visible"]').trigger('click')

      expect(putDecisions).not.toHaveBeenCalled()
    } finally {
      Object.defineProperty(globalThis, 'confirm', {
        configurable: true,
        value: originalConfirm
      })
    }
  })

  it('limits visible batch decisions to the first 500 loaded filtered issues', async () => {
    const putDecisions = vi.fn().mockResolvedValue({ outcomes: [] } satisfies DecisionBatchResponse)
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            total: 501,
            items: Array.from({ length: 501 }, (_, index) =>
              buildIssue({
                issue_id: `issue-${index + 1}`,
                block_id: 'block-1',
                start: 0,
                end: 2,
                original: `问题${index + 1}`
              })
            )
          })
        ),
        putDecisions
      })
    )
    await flushPromises()

    await wrapper.get('button[name="ignore-visible"]').trigger('click')
    await flushPromises()

    expect(putDecisions).toHaveBeenCalledTimes(1)
    expect(putDecisions.mock.calls[0]?.[1]).toHaveLength(500)
    expect(wrapper.text()).toContain('当前仅批量处理前 500 项')
  })

  it('hides retry UI after a failed save when switching to another issue', async () => {
    const putDecisions = vi
      .fn()
      .mockRejectedValueOnce(new Error('保存处理结果失败'))
    const wrapper = mountReviewWorkspace(createAnalysisApiMock({ putDecisions }))
    await flushPromises()

    await wrapper.get('button[name="accept"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="decision-error"]').text()).toContain(
      '保存处理结果失败'
    )

    await wrapper.get('[data-issue-id="issue-2"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('aside[aria-label="问题详情"]').text()).toContain('发现错词')
    expect(wrapper.find('[data-testid="decision-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="retry-decision"]').exists()).toBe(false)
    expect(putDecisions).toHaveBeenCalledTimes(1)
  })

  it('rolls back a failed decision and exposes an explicit retry', async () => {
    const retryResponse = createDeferred<DecisionBatchResponse>()
    const putDecisions = vi
      .fn()
      .mockRejectedValueOnce(new Error('保存处理结果失败'))
      .mockReturnValueOnce(retryResponse.promise)
    const wrapper = mountReviewWorkspace(createAnalysisApiMock({ putDecisions }))
    await flushPromises()

    await wrapper.get('button[name="accept"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').text()).toBe(
      '第一'
    )
    expect(wrapper.get('[data-testid="decision-error"]').attributes('role')).toBe('alert')
    expect(wrapper.get('[data-testid="decision-error"]').text()).toContain(
      '保存处理结果失败'
    )

    await wrapper.get('[data-testid="retry-decision"]').trigger('click')

    expect(putDecisions).toHaveBeenCalledTimes(2)
    expect(putDecisions).toHaveBeenLastCalledWith(jobId, [
      {
        issue_id: 'issue-1',
        issue_version: 1,
        action: 'accepted'
      }
    ])
    expect(wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').text()).toBe(
      '首段'
    )

    retryResponse.resolve(
      buildAppliedResponse({
        issue_id: 'issue-1',
        issue_version: 1,
        action: 'accepted',
        replacement: null,
        updated_at: '2026-08-18T01:00:00Z'
      })
    )
    await flushPromises()

    expect(wrapper.find('[data-testid="decision-error"]').exists()).toBe(false)
  })

  it('ignores stale decision responses for the same issue', async () => {
    const acceptedResponse = createDeferred<DecisionBatchResponse>()
    const ignoredResponse = createDeferred<DecisionBatchResponse>()
    const putDecisions = vi
      .fn()
      .mockReturnValueOnce(acceptedResponse.promise)
      .mockReturnValueOnce(ignoredResponse.promise)
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(buildIssuePage())
      .mockResolvedValueOnce(
        buildIssuePage({
          items: [
            buildIssue({
              decision: {
                issue_version: 1,
                action: 'ignored',
                replacement: null,
                updated_at: '2026-08-18T01:01:00Z'
              }
            }),
            buildIssue({
              issue_id: 'issue-2',
              block_id: 'block-2',
              start: 3,
              end: 5,
              original: '错误',
              message: '发现错词',
              context: '甲😀乙错误'
            })
          ]
        })
      )
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({ getIssues, putDecisions })
    )
    await flushPromises()

    await wrapper.get('button[name="accept"]').trigger('click')
    await wrapper.get('button[name="ignore"]').trigger('click')

    ignoredResponse.resolve(
      buildAppliedResponse({
        issue_id: 'issue-1',
        issue_version: 1,
        action: 'ignored',
        replacement: null,
        updated_at: '2026-08-18T01:01:00Z'
      })
    )
    await flushPromises()
    acceptedResponse.resolve(
      buildAppliedResponse({
        issue_id: 'issue-1',
        issue_version: 1,
        action: 'accepted',
        replacement: null,
        updated_at: '2026-08-18T01:00:00Z'
      })
    )
    await flushPromises()

    expect(wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').text()).toBe(
      '第一'
    )
    expect(wrapper.get('aside[aria-label="问题详情"]').text()).toContain('已忽略')
  })

  it.each([
    ['empty', ''],
    ['whitespace', '   '],
    ['NUL', '有效\u0000替换'],
    ['more than 10,000 code points', '😀'.repeat(10_001)]
  ])('rejects an invalid custom replacement before request: %s', async (_, replacement) => {
    const putDecisions = vi.fn()
    const wrapper = mountReviewWorkspace(createAnalysisApiMock({ putDecisions }))
    await flushPromises()

    await wrapper.get('[aria-label="自定义替换"]').setValue(replacement)
    await wrapper.get('button[name="custom-decision"]').trigger('click')

    expect(putDecisions).not.toHaveBeenCalled()
    expect(wrapper.get('[data-testid="custom-replacement-error"]').attributes('role')).toBe(
      'alert'
    )
  })

  it('navigates document matches inside the viewer without scrolling the page', async () => {
    const putDecisions = vi.fn()
    const scrollIntoView = vi.fn()
    const originalScrollIntoView = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'scrollIntoView'
    )
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView
    })
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getDocumentPage: vi.fn().mockResolvedValue(
          buildDocumentPage({
            blocks: [
              buildBlock({
                block_id: 'block-1',
                text: '甲项目'
              }),
              buildBlock({
                block_id: 'block-2',
                text: '乙项目'
              }),
              buildBlock({
                block_id: 'block-3',
                text: '丙项目'
              })
            ],
            total_blocks: 3
          })
        ),
        putDecisions
      })
    )
    try {
      await flushPromises()

      const viewer = wrapper.get('.document-viewer').element as HTMLElement
      const scrollTo = vi.fn()
      Object.defineProperty(viewer, 'clientHeight', {
        configurable: true,
        value: 600
      })
      Object.defineProperty(viewer, 'scrollHeight', {
        configurable: true,
        value: 1200
      })
      Object.defineProperty(viewer, 'scrollTo', {
        configurable: true,
        value: scrollTo
      })
      vi.spyOn(viewer, 'getBoundingClientRect').mockReturnValue({
        top: 100,
        bottom: 700,
        left: 0,
        right: 800,
        width: 800,
        height: 600,
        x: 0,
        y: 100,
        toJSON: () => ({})
      })
      vi.spyOn(
        wrapper.get('[data-block-id="block-2"]').element,
        'getBoundingClientRect'
      ).mockReturnValue({
        top: 550,
        bottom: 590,
        left: 0,
        right: 800,
        width: 800,
        height: 40,
        x: 0,
        y: 550,
        toJSON: () => ({})
      })

      await wrapper.get('[aria-label="查找内容"]').setValue('项目')
      await flushPromises()
      scrollIntoView.mockClear()
      scrollTo.mockClear()
      expect(wrapper.get('[data-testid="find-status"]').text()).toContain('第 1 / 3 处')

      await wrapper.get('button[name="next-match"]').trigger('click')
      await flushPromises()

      expect(wrapper.get('[data-testid="find-status"]').text()).toContain('第 2 / 3 处')
      expect(scrollIntoView).not.toHaveBeenCalled()
      expect(scrollTo).toHaveBeenCalledTimes(1)
      expect(putDecisions).not.toHaveBeenCalled()
    } finally {
      wrapper.unmount()
      if (originalScrollIntoView) {
        Object.defineProperty(
          HTMLElement.prototype,
          'scrollIntoView',
          originalScrollIntoView
        )
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
      }
    }
  })

  it('uses page scrolling when the document viewer has no internal overflow', async () => {
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getDocumentPage: vi.fn().mockResolvedValue(
          buildDocumentPage({
            blocks: [
              buildBlock({ block_id: 'block-1', text: '甲项目' }),
              buildBlock({ block_id: 'block-2', text: '乙项目' })
            ],
            total_blocks: 2
          })
        )
      })
    )
    await flushPromises()

    await wrapper.get('[aria-label="查找内容"]').setValue('项目')
    await flushPromises()

    const viewer = wrapper.get('.document-viewer').element as HTMLElement
    const viewerScroll = vi.fn()
    const blockScroll = vi.fn()
    Object.defineProperty(viewer, 'clientHeight', {
      configurable: true,
      value: 600
    })
    Object.defineProperty(viewer, 'scrollHeight', {
      configurable: true,
      value: 600
    })
    Object.defineProperty(viewer, 'scrollTo', {
      configurable: true,
      value: viewerScroll
    })
    Object.defineProperty(
      wrapper.get('[data-block-id="block-2"]').element,
      'scrollIntoView',
      { configurable: true, value: blockScroll }
    )

    await wrapper.get('button[name="next-match"]').trigger('click')
    await flushPromises()

    expect(blockScroll).toHaveBeenCalledWith({ block: 'center' })
    expect(viewerScroll).not.toHaveBeenCalled()
  })

  it('replaces every exact auto-fixable match with custom decisions only', async () => {
    const putDecisions = vi.fn().mockResolvedValue({
      outcomes: [
        {
          issue_id: 'issue-1',
          status: 'applied',
          code: null,
          decision: {
            issue_id: 'issue-1',
            issue_version: 1,
            action: 'custom',
            replacement: '条目',
            updated_at: '2026-08-18T03:00:00Z'
          }
        },
        {
          issue_id: 'issue-2',
          status: 'applied',
          code: null,
          decision: {
            issue_id: 'issue-2',
            issue_version: 1,
            action: 'custom',
            replacement: '条目',
            updated_at: '2026-08-18T03:00:00Z'
          }
        },
        {
          issue_id: 'issue-3',
          status: 'applied',
          code: null,
          decision: {
            issue_id: 'issue-3',
            issue_version: 1,
            action: 'custom',
            replacement: '条目',
            updated_at: '2026-08-18T03:00:00Z'
          }
        }
      ]
    } satisfies DecisionBatchResponse)
    const rawBlock = buildBlock({
      text: '甲😀项目乙😀项目丙项目'
    })
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getDocumentPage: vi.fn().mockResolvedValue(
          buildDocumentPage({
            blocks: [rawBlock],
            total_blocks: 1
          })
        ),
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            total: 3,
            items: [
              buildIssue({
                issue_id: 'issue-1',
                start: 2,
                end: 4,
                original: '项目',
                context: rawBlock.text
              }),
              buildIssue({
                issue_id: 'issue-2',
                start: 6,
                end: 8,
                original: '项目',
                context: rawBlock.text
              }),
              buildIssue({
                issue_id: 'issue-3',
                start: 9,
                end: 11,
                original: '项目',
                context: rawBlock.text
              })
            ]
          })
        ),
        putDecisions
      })
    )
    await flushPromises()

    await wrapper.get('[aria-label="查找内容"]').setValue('项目')
    await wrapper.get('[aria-label="替换为"]').setValue('条目')
    await wrapper.get('button[name="replace-all"]').trigger('click')
    await flushPromises()

    expect(putDecisions).toHaveBeenCalledWith(jobId, [
      {
        issue_id: 'issue-1',
        issue_version: 1,
        action: 'custom',
        replacement: '条目'
      },
      {
        issue_id: 'issue-2',
        issue_version: 1,
        action: 'custom',
        replacement: '条目'
      },
      {
        issue_id: 'issue-3',
        issue_version: 1,
        action: 'custom',
        replacement: '条目'
      }
    ])
    expect(rawBlock.text).toBe('甲😀项目乙😀项目丙项目')
  })

  it('retains loaded issue cards when production pagination fails and retries that page', async () => {
    const getIssues = vi
      .fn()
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 2,
          items: [buildIssue()],
          next_cursor: 'issues-2'
        })
      )
      .mockRejectedValueOnce(new Error('问题分页暂时不可用'))
      .mockResolvedValueOnce(
        buildIssuePage({
          total: 2,
          items: [buildIssue({ issue_id: 'issue-2', original: '第二页问题' })]
        })
      )
    const wrapper = mountReviewWorkspace(createAnalysisApiMock({ getIssues }))
    await flushPromises()

    await wrapper.get('[data-testid="load-more-issues"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('问题分页暂时不可用')
    expect(wrapper.find('[data-issue-id="issue-1"]').exists()).toBe(true)

    await wrapper.get('[data-testid="retry-issues"]').trigger('click')
    await flushPromises()

    expect(getIssues).toHaveBeenCalledTimes(3)
    expect(getIssues).toHaveBeenLastCalledWith(jobId, {
      cursor: 'issues-2',
      limit: 50
    })
    expect(wrapper.find('[data-issue-id="issue-1"]').exists()).toBe(true)
    expect(wrapper.find('[data-issue-id="issue-2"]').exists()).toBe(true)
  })

  it('coalesces concurrent retries so a later failure cannot supersede success', async () => {
    const successfulRetry = createDeferred<AnalysisSummaryResponse>()
    const supersedingFailure = createDeferred<AnalysisSummaryResponse>()
    const getSummary = vi
      .fn()
      .mockRejectedValueOnce(new Error('总览暂时不可用'))
      .mockReturnValueOnce(successfulRetry.promise)
      .mockReturnValueOnce(supersedingFailure.promise)
    const wrapper = mountReviewWorkspace(createAnalysisApiMock({ getSummary }))
    await flushPromises()

    const retry = wrapper.get('[data-testid="document-header"] button')
    await retry.trigger('click')
    await retry.trigger('click')

    expect(getSummary).toHaveBeenCalledTimes(2)

    successfulRetry.resolve(buildSummary())
    await flushPromises()

    expect(wrapper.find('[data-testid="document-header"] [role="alert"]').exists()).toBe(
      false
    )
    expect(wrapper.text()).toContain('2 个问题')
  })

  it('does not continue selected-issue pagination after unmount', async () => {
    const firstDocumentPage = createDeferred<DocumentPageResponse>()
    const getDocumentPage = vi.fn().mockReturnValue(firstDocumentPage.promise)
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getDocumentPage,
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            total: 1,
            items: [
              buildIssue({
                issue_id: 'issue-later',
                block_id: 'block-later'
              })
            ]
          })
        )
      })
    )
    await flushPromises()

    await wrapper.get('[data-issue-id="issue-later"]').trigger('click')
    wrapper.unmount()
    firstDocumentPage.resolve(
      buildDocumentPage({
        blocks: [buildBlock()],
        total_blocks: 2,
        next_cursor: 'blocks-2'
      })
    )
    await flushPromises()

    expect(getDocumentPage).toHaveBeenCalledTimes(1)
  })

  it('shows request failures with retries and partial checker failures', async () => {
    const getDocumentPage = vi
      .fn()
      .mockRejectedValueOnce(new Error('文档分页暂时不可用'))
      .mockResolvedValueOnce(buildDocumentPage())
    const analysisApi = createAnalysisApiMock({
      getDocumentPage,
      getSummary: vi.fn().mockResolvedValue(
        buildSummary({
          status: 'partial',
          checker_failures: {
            security: {
              code: 'checker_failed',
              message: '安全检查器启动失败'
            }
          }
        })
      )
    })
    const wrapper = mountReviewWorkspace(analysisApi)
    await flushPromises()

    expect(wrapper.get('[data-testid="document-error"]').attributes('role')).toBe('alert')
    expect(wrapper.get('[data-testid="document-error"]').text()).toContain(
      '文档分页暂时不可用'
    )
    expect(wrapper.get('.checker-failures__category').text()).toBe('安全')
    expect(wrapper.text()).toContain('安全检查器启动失败')

    await wrapper.get('[data-testid="retry-document"]').trigger('click')
    await flushPromises()

    expect(getDocumentPage).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-testid="document-error"]').exists()).toBe(false)
    expect(wrapper.find('[data-block-id="block-1"]').exists()).toBe(true)
  })

  it('renders a document with an explicit empty issue state', async () => {
    const wrapper = mountReviewWorkspace(
      createAnalysisApiMock({
        getSummary: vi.fn().mockResolvedValue(buildSummary({ total_issues: 0 })),
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            total: 0,
            items: []
          })
        )
      })
    )
    await flushPromises()

    expect(wrapper.find('[data-block-id="block-1"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="empty-issues"]').text()).toContain('未发现问题')
    expect(wrapper.get('aside[aria-label="问题详情"]').text()).toContain('请选择问题')
  })
})
