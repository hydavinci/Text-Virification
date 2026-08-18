import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import { analysisApiKey, type AnalysisApi } from '../src/api/analysis'
import {
  reviewIntersectionObserverFactoryKey,
  type ReviewIntersectionObserverCallback,
  type ReviewIntersectionObserverFactory
} from '../src/components/review/observer'
import ReviewNavigation from '../src/components/review/ReviewNavigation.vue'
import { useReviewWorkspace } from '../src/composables/useReviewWorkspace'
import type {
  AnalysisSummaryResponse,
  DocumentBlock,
  DocumentPageResponse,
  Issue,
  IssuePageResponse
} from '../src/types/analysis'
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

function createAnalysisApiMock(overrides: Partial<AnalysisApi> = {}): AnalysisApi {
  return {
    getSummary: vi.fn().mockResolvedValue(buildSummary()),
    getDocumentPage: vi.fn().mockResolvedValue(buildDocumentPage()),
    getIssues: vi.fn().mockResolvedValue(buildIssuePage()),
    putDecisions: vi.fn(),
    ...overrides
  }
}

function mountReviewWorkspace(
  analysisApi = createAnalysisApiMock(),
  observerFactory?: ReviewIntersectionObserverFactory
) {
  const provide: Record<symbol, unknown> = {
    [analysisApiKey as symbol]: analysisApi
  }

  if (observerFactory) {
    provide[reviewIntersectionObserverFactoryKey as symbol] = observerFactory
  }

  return mount(ReviewWorkspaceView, {
    props: {
      jobId,
      sourceName: 'sample.txt',
      fileType: 'txt'
    },
    global: { provide }
  })
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
      :selected-issue-id="selectedIssueId"
      :loading="loading.issues"
      :error="errors.issues"
      @select="selectIssue"
      @retry="retryIssues"
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

describe('ReviewWorkspaceView', () => {
  it('renders semantic columns and synchronizes issue and highlight selection', async () => {
    const wrapper = mountReviewWorkspace()
    await flushPromises()

    expect(wrapper.find('[aria-label="文档审阅工作台"]').exists()).toBe(true)
    expect(wrapper.find('nav[aria-label="问题筛选"]').exists()).toBe(true)
    expect(wrapper.find('article[aria-label="文档内容"]').exists()).toBe(true)
    expect(wrapper.find('aside[aria-label="问题详情"]').exists()).toBe(true)

    await wrapper.get('[data-issue-id="issue-2"]').trigger('click')

    expect(wrapper.get('[data-block-id="block-2"]').classes()).toContain(
      'document-block--active'
    )
    expect(
      wrapper.get('[data-highlight-range-issue-ids~="issue-2"]').text()
    ).toBe('错误')
    expect(
      wrapper.get('[data-highlight-issue-id="issue-2"]').attributes('aria-current')
    ).toBe('true')

    await wrapper.get('[data-highlight-issue-id="issue-1"]').trigger('click')

    expect(wrapper.get('[data-issue-id="issue-1"]').attributes('aria-current')).toBe('true')
    expect(wrapper.get('[data-block-id="block-1"]').classes()).toContain(
      'document-block--active'
    )
  })

  it('retries localization when the selected issue resolves before its block', async () => {
    const documentPage = createDeferred<DocumentPageResponse>()
    const scrollIntoView = vi.fn()
    const originalDescriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'scrollIntoView'
    )
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView
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

      expect(wrapper.get('[data-issue-id="issue-1"]').attributes('aria-current')).toBe(
        'true'
      )
      expect(scrollIntoView).not.toHaveBeenCalled()

      documentPage.resolve(
        buildDocumentPage({
          blocks: [buildBlock()],
          total_blocks: 1
        })
      )
      await flushPromises()

      expect(
        wrapper.get('[data-highlight-issue-id="issue-1"]').attributes('aria-current')
      ).toBe('true')
      expect(scrollIntoView).toHaveBeenCalledTimes(1)
    } finally {
      if (originalDescriptor) {
        Object.defineProperty(
          HTMLElement.prototype,
          'scrollIntoView',
          originalDescriptor
        )
      } else {
        Reflect.deleteProperty(HTMLElement.prototype, 'scrollIntoView')
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
      wrapper.get('[data-highlight-issue-id="issue-later"]').attributes('aria-current')
    ).toBe('true')
  })

  it('keeps identical and nested issue ranges addressable without duplicating text', async () => {
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
            total: 3,
            items: [
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
    expect(wrapper.findAll('[data-highlight-issue-id]')).toHaveLength(3)

    await wrapper.get('[data-highlight-issue-id="issue-identical"]').trigger('click')
    expect(
      wrapper.get('[data-issue-id="issue-identical"]').attributes('aria-current')
    ).toBe('true')

    await wrapper.get('[data-highlight-issue-id="issue-nested"]').trigger('click')
    expect(wrapper.get('[data-issue-id="issue-nested"]').attributes('aria-current')).toBe(
      'true'
    )
    expect(
      wrapper.get('[data-highlight-range-issue-ids~="issue-nested"]').classes()
    ).toContain('document-highlight-range--active')
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
    Object.defineProperty(
      first.get('[data-highlight-issue-id="issue-1"]').element,
      'scrollIntoView',
      { configurable: true, value: firstScroll }
    )
    Object.defineProperty(
      second.get('[data-highlight-issue-id="issue-1"]').element,
      'scrollIntoView',
      { configurable: true, value: secondScroll }
    )

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

  it('retains loaded issue cards when append fails and retries that page', async () => {
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
    const wrapper = mountReviewWorkspaceState(createAnalysisApiMock({ getIssues }))
    await flushPromises()

    await wrapper.get('[data-testid="load-next-issues"]').trigger('click')
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

    const retry = wrapper.get('.review-toolbar__error button')
    await retry.trigger('click')
    await retry.trigger('click')

    expect(getSummary).toHaveBeenCalledTimes(2)

    successfulRetry.resolve(buildSummary())
    await flushPromises()

    expect(wrapper.find('.review-toolbar__error').exists()).toBe(false)
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
    expect(wrapper.text()).toContain('security')
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
