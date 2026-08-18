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
  DecisionBatchResponse,
  DocumentBlock,
  DocumentPageResponse,
  Issue,
  IssueDecision,
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
      :filters="filters"
      @select="selectIssue"
      @retry="retryIssues"
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
    const wrapper = mountReviewWorkspace(createAnalysisApiMock({ putDecisions }))
    await flushPromises()

    await wrapper.get('[aria-label="自定义替换"]').setValue('客户端替换')
    await wrapper.get('button[name="custom-decision"]').trigger('click')
    expect(wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').text()).toBe(
      '客户端替换'
    )

    decisionResponse.resolve(
      buildAppliedResponse({
        issue_id: 'issue-1',
        issue_version: 1,
        action: 'custom',
        replacement: '服务器替换',
        updated_at: '2026-08-18T01:00:00Z'
      })
    )
    await flushPromises()

    expect(wrapper.get('[data-highlight-range-issue-ids~="issue-1"]').text()).toBe(
      '服务器替换'
    )
    expect(wrapper.get('aside[aria-label="问题详情"]').text()).toContain('已自定义')
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
    const wrapper = mountReviewWorkspace(createAnalysisApiMock({ putDecisions }))
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
