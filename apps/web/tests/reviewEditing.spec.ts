import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { analysisApiKey, type AnalysisApi } from '../src/api/analysis'
import { exportsApiKey, type ExportsApi } from '../src/api/exports'
import { revisionsApiKey, type RevisionsApi } from '../src/api/revisions'
import { useDerivedPreview } from '../src/composables/useDerivedPreview'
import { useEditDraft } from '../src/composables/useEditDraft'
import { useReviewHistory } from '../src/composables/useReviewHistory'
import { useReviewWorkspace, type ReviewWorkspaceState } from '../src/composables/useReviewWorkspace'
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
import type {
  DocumentVersion,
  DiffDerivedResponse,
  EditDraft,
  ModifiedDerivedResponse,
  OperationBatch,
  OperationBatchPage,
  VersionEvent,
  VersionListResponse
} from '../src/types/revisions'
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

function buildVersion(overrides: Partial<DocumentVersion> = {}): DocumentVersion {
  return {
    version_id: 'version-1',
    job_id: jobId,
    parent_version_id: null,
    revision_number: 1,
    status: 'succeeded',
    source_kind: 'original',
    created_reason: 'upload',
    content_sha256: 'a'.repeat(64),
    created_at: '2026-08-23T12:00:00Z',
    started_at: '2026-08-23T12:00:01Z',
    completed_at: '2026-08-23T12:00:02Z',
    failure_code: null,
    failure_message: null,
    ...overrides
  }
}

function buildVersionsResponse(
  overrides: Partial<VersionListResponse> = {}
): VersionListResponse {
  return {
    job_id: jobId,
    active_version_id: 'version-2',
    versions: [
      buildVersion(),
      buildVersion({
        version_id: 'version-2',
        parent_version_id: 'version-1',
        revision_number: 2
      })
    ],
    ...overrides
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
    blocks: [buildBlock()],
    total_blocks: 1,
    next_cursor: null,
    checker_failures: {},
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
    suggestions: [
      {
        suggestion_id: 'suggestion-1',
        text: '首段',
        source: 'rule',
        explanation: null,
        rank: 1,
        preferred: true
      }
    ],
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

function buildIssuePage(overrides: Partial<IssuePageResponse> = {}): IssuePageResponse {
  return {
    job_id: jobId,
    status: 'completed',
    total: 1,
    items: [buildIssue()],
    next_cursor: null,
    checker_failures: {},
    ...overrides
  }
}

function buildSummary(
  overrides: Partial<AnalysisSummaryResponse> = {}
): AnalysisSummaryResponse {
  return {
    job_id: jobId,
    status: 'completed',
    total_issues: 1,
    by_category: {
      character: 1,
      vocabulary: 0,
      sentence: 0,
      format: 0,
      discourse: 0,
      security: 0
    },
    by_severity: { error: 0, warning: 1, info: 0 },
    by_decision: { accepted: 0, ignored: 0, custom: 0, unreviewed: 1 },
    checker_failures: {},
    ...overrides
  }
}

function buildDraft(overrides: Partial<EditDraft> = {}): EditDraft {
  return {
    draft_id: 'draft-1',
    job_id: jobId,
    base_version_id: 'version-2',
    revision: 1,
    blocks: [{ block_id: 'block-1', text: '服务器草稿' }],
    content_sha256: null,
    created_at: '2026-08-23T12:00:00Z',
    updated_at: '2026-08-23T12:00:00Z',
    consumed_at: null,
    ...overrides
  }
}

function buildBatch(overrides: Partial<OperationBatch> = {}): OperationBatch {
  return {
    batch_id: 'batch-1',
    job_id: jobId,
    version_id: 'version-2',
    operation_type: 'decision',
    affected_count: 1,
    undoes_batch_id: null,
    created_at: '2026-08-23T12:00:00Z',
    ...overrides
  }
}

function buildAppliedResponse(decision: IssueDecision | null): DecisionBatchResponse {
  return {
    batch_id: 'batch-1',
    outcomes: [
      {
        issue_id: 'issue-1',
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
    putDecisions: vi.fn().mockResolvedValue({
      batch_id: 'batch-1',
      outcomes: [
        {
          issue_id: 'issue-1',
          status: 'applied',
          code: null,
          decision: {
            issue_id: 'issue-1',
            issue_version: 1,
            revision: 1,
            action: 'accepted',
            replacement: '首段',
            suggestion_id: 'suggestion-1',
            updated_at: '2026-08-23T12:00:00Z'
          }
        }
      ]
    } satisfies DecisionBatchResponse),
    ...overrides
  }
}

function createRevisionsApiMock(overrides: Partial<RevisionsApi> = {}): RevisionsApi {
  return {
    listVersions: vi.fn().mockResolvedValue(buildVersionsResponse()),
    createDraft: vi.fn().mockResolvedValue(buildDraft()),
    getDraft: vi.fn().mockResolvedValue(buildDraft()),
    updateDraft: vi.fn().mockResolvedValue(buildDraft({ revision: 2 })),
    deleteDraft: vi.fn().mockResolvedValue(undefined),
    reanalyze: vi.fn().mockResolvedValue({
      version: buildVersion({
        version_id: 'version-3',
        parent_version_id: 'version-2',
        revision_number: 3,
        status: 'queued'
      }),
      events_url: '/api/v1/jobs/job-1/versions/version-3/events'
    }),
    getDerived: vi.fn().mockResolvedValue({
      job_id: jobId,
      version_id: 'version-2',
      decision_snapshot_sha256: 'new-hash',
      blocks: [buildBlock({ text: '修改后' })]
    }),
    subscribeVersionEvents: vi.fn().mockReturnValue(vi.fn()),
    listHistory: vi.fn().mockResolvedValue({
      job_id: jobId,
      version_id: 'version-2',
      total: 0,
      items: [],
      next_cursor: null
    } satisfies OperationBatchPage),
    undoBatch: vi.fn().mockResolvedValue(buildBatch({ operation_type: 'undo' })),
    ...overrides
  }
}

function createExportsApiMock(overrides: Partial<ExportsApi> = {}): ExportsApi {
  return {
    create: vi.fn(),
    get: vi.fn(),
    downloadUrl: vi.fn().mockReturnValue('/api/v1/jobs/job-1/exports/export-1/download'),
    ...overrides
  }
}

function mountWorkspace(
  analysisApi = createAnalysisApiMock(),
  revisionsApi = createRevisionsApiMock()
): ReviewWorkspaceState {
  let workspace!: ReviewWorkspaceState
  const Harness = defineComponent({
    setup() {
      workspace = useReviewWorkspace(jobId)
      return {}
    },
    template: '<div />'
  })

  mount(Harness, {
    global: {
      provide: {
        [analysisApiKey as symbol]: analysisApi,
        [revisionsApiKey as symbol]: revisionsApi
      }
    }
  })

  return workspace
}

function mountReviewWorkspaceView(
  analysisApi = createAnalysisApiMock(),
  revisionsApi = createRevisionsApiMock()
) {
  return mount(ReviewWorkspaceView, {
    props: {
      jobId,
      sourceName: 'sample.txt',
      fileType: 'txt'
    },
    global: {
      provide: {
        [analysisApiKey as symbol]: analysisApi,
        [revisionsApiKey as symbol]: revisionsApi,
        [exportsApiKey as symbol]: createExportsApiMock()
      }
    }
  })
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('review editing state', () => {
  it('renders version labels and creates active or historical drafts explicitly', async () => {
    const createDraft = vi.fn().mockResolvedValue(buildDraft())
    const revisionsApi = createRevisionsApiMock({ createDraft })
    const wrapper = mountReviewWorkspaceView(createAnalysisApiMock(), revisionsApi)
    await flushPromises()

    expect(wrapper.find('select[aria-label="版本"]').exists()).toBe(true)
    expect(wrapper.findAll('select[aria-label="版本"] option').map((option) => option.text())).toEqual([
      '版本 1（历史，只读）',
      '版本 2（当前）'
    ])

    await wrapper.get('button[name="edit-version"]').trigger('click')
    await flushPromises()

    expect(createDraft).toHaveBeenLastCalledWith(jobId, 'version-2')
    expect(wrapper.find('textarea[aria-label="第 1 段"]').exists()).toBe(true)

    await wrapper.get('button[name="discard-draft"]').trigger('click')
    await flushPromises()
    await wrapper.get('select[aria-label="版本"]').setValue('version-1')
    await flushPromises()

    expect(wrapper.get('button[name="edit-version"]').text()).toBe('从此版本创建新版本')

    await wrapper.get('button[name="edit-version"]').trigger('click')
    await flushPromises()

    expect(createDraft).toHaveBeenLastCalledWith(jobId, 'version-1')
  })

  it('prevents version and view switching while an edit draft is active', async () => {
    const revisionsApi = createRevisionsApiMock()
    const wrapper = mountReviewWorkspaceView(createAnalysisApiMock(), revisionsApi)
    await flushPromises()

    await wrapper.get('button[name="edit-version"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('select[aria-label="版本"]').attributes('disabled')).toBeDefined()
    expect(
      wrapper
        .findAll('button[role="tab"][data-mode]')
        .map((tab) => tab.attributes('disabled'))
    ).toEqual(['', '', ''])
  })

  it('rejects draft saves and reanalysis when the expected base version no longer matches', async () => {
    const updateDraft = vi.fn()
    const reanalyze = vi.fn()
    const revisionsApi = createRevisionsApiMock({ updateDraft, reanalyze })
    let draftState!: ReturnType<typeof useEditDraft>
    const Harness = defineComponent({
      setup() {
        draftState = useEditDraft(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    await draftState.begin('version-2')
    draftState.updateBlock('block-1', '不应提交的旧草稿')

    await expect(draftState.save('version-1')).rejects.toThrow(
      'Draft base version does not match the selected version.'
    )
    await expect(draftState.reanalyze('version-1')).rejects.toThrow(
      'Draft base version does not match the selected version.'
    )
    expect(updateDraft).not.toHaveBeenCalled()
    expect(reanalyze).not.toHaveBeenCalled()
  })

  it('dismisses an SSE-reported reanalysis failure when returning to the draft', async () => {
    let progressHandler!: (event: VersionEvent) => void
    const revisionsApi = createRevisionsApiMock({
      subscribeVersionEvents: vi.fn().mockImplementation(
        (
          _jobId: string,
          _versionId: string,
          onEvent: (event: VersionEvent) => void
        ) => {
          progressHandler = onEvent
          return vi.fn()
        }
      )
    })
    const wrapper = mountReviewWorkspaceView(createAnalysisApiMock(), revisionsApi)
    await flushPromises()

    await wrapper.get('button[name="edit-version"]').trigger('click')
    await flushPromises()
    await wrapper.get('button[name="save-reanalyze"]').trigger('click')
    await flushPromises()
    progressHandler({
      sequence: 1,
      status: 'failed',
      progress: 100,
      message: '重新检查服务失败',
      created_at: '2026-08-23T12:01:00Z',
      metadata: null
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="reanalysis-failure"]').text()).toContain(
      '重新检查服务失败'
    )

    await wrapper.get('button[name="return-to-draft"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-testid="reanalysis-failure"]').exists()).toBe(false)
    expect(wrapper.find('textarea[aria-label="第 1 段"]').exists()).toBe(true)
  })

  it('unlocks document controls after reanalysis succeeds', async () => {
    let progressHandler!: (event: VersionEvent) => void
    const revisionsApi = createRevisionsApiMock({
      subscribeVersionEvents: vi.fn().mockImplementation(
        (
          _jobId: string,
          _versionId: string,
          onEvent: (event: VersionEvent) => void
        ) => {
          progressHandler = onEvent
          return vi.fn()
        }
      )
    })
    const wrapper = mountReviewWorkspaceView(createAnalysisApiMock(), revisionsApi)
    await flushPromises()

    await wrapper.get('button[name="edit-version"]').trigger('click')
    await flushPromises()
    await wrapper.get('button[name="save-reanalyze"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('select[aria-label="版本"]').attributes('disabled')).toBeDefined()

    progressHandler({
      sequence: 1,
      status: 'succeeded',
      progress: 100,
      message: '重新检查完成',
      created_at: '2026-08-23T12:01:00Z',
      metadata: null
    })
    await flushPromises()

    expect(wrapper.get('select[aria-label="版本"]').attributes('disabled')).toBeUndefined()
    expect(
      wrapper
        .findAll('button[role="tab"][data-mode]')
        .map((tab) => tab.attributes('disabled'))
    ).toEqual([undefined, undefined, undefined])
  })

  it('surfaces draft creation failures before the editor is mounted', async () => {
    const revisionsApi = createRevisionsApiMock({
      createDraft: vi.fn().mockRejectedValue(new Error('无法创建草稿'))
    })
    const wrapper = mountReviewWorkspaceView(createAnalysisApiMock(), revisionsApi)
    await flushPromises()

    await wrapper.get('button[name="edit-version"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="draft-error"]').attributes('role')).toBe('alert')
    expect(wrapper.get('[data-testid="draft-error"]').text()).toContain('无法创建草稿')
    expect(wrapper.find('textarea[aria-label="第 1 段"]').exists()).toBe(false)
  })

  it('keeps edited draft text after a failed reanalysis returns to the editor', async () => {
    const revisionsApi = createRevisionsApiMock({
      createDraft: vi.fn().mockResolvedValue(
        buildDraft({
          blocks: [
            { block_id: 'block-1', text: '第一段文字' },
            { block_id: 'block-2', text: '第二段文字' }
          ]
        })
      ),
      updateDraft: vi.fn().mockResolvedValue(
        buildDraft({
          revision: 2,
          blocks: [
            { block_id: 'block-1', text: '本地保留文本' },
            { block_id: 'block-2', text: '第二段文字' }
          ]
        })
      ),
      reanalyze: vi.fn().mockRejectedValue(new Error('重新检查失败'))
    })
    const wrapper = mountReviewWorkspaceView(createAnalysisApiMock(), revisionsApi)
    await flushPromises()

    await wrapper.get('button[name="edit-version"]').trigger('click')
    await flushPromises()
    await wrapper.get('textarea[aria-label="第 1 段"]').setValue('本地保留文本')

    expect(wrapper.get('button[name="save-reanalyze"]').text()).toBe('保存草稿并重新检查')
    expect(wrapper.get('button[name="discard-draft"]').text()).toBe('放弃草稿')

    await wrapper.get('button[name="save-reanalyze"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="reanalysis-failure"]').text()).toContain('重新检查失败')

    await wrapper.get('button[name="return-to-draft"]').trigger('click')
    await flushPromises()

    expect((wrapper.get('textarea[aria-label="第 1 段"]').element as HTMLTextAreaElement).value).toBe(
      '本地保留文本'
    )
  })

  it('renders modified and diff document views from derived preview state', async () => {
    const modified: ModifiedDerivedResponse = {
      job_id: jobId,
      version_id: 'version-2',
      decision_snapshot_sha256: 'hash-1',
      blocks: [buildBlock({ text: '修改后文本' })]
    }
    const diff: DiffDerivedResponse = {
      job_id: jobId,
      version_id: 'version-2',
      decision_snapshot_sha256: 'hash-1',
      blocks: [
        {
          block_id: 'block-1',
          segments: [
            { kind: 'equal', text: '第一' },
            { kind: 'delete', text: '段' },
            { kind: 'insert', text: '节' }
          ]
        }
      ]
    }
    const getDerived = vi
      .fn()
      .mockResolvedValueOnce(modified)
      .mockResolvedValueOnce(diff)
    const wrapper = mountReviewWorkspaceView(
      createAnalysisApiMock(),
      createRevisionsApiMock({ getDerived })
    )
    await flushPromises()

    await wrapper.get('button[role="tab"][data-mode="modified"]').trigger('click')
    await flushPromises()

    expect(getDerived).toHaveBeenLastCalledWith(jobId, 'version-2', 'modified')
    expect(wrapper.get('[data-block-id="block-1"]').text()).toBe('修改后文本')
    expect(wrapper.find('[data-highlight-range-issue-ids]').exists()).toBe(false)

    await wrapper.get('button[role="tab"][data-mode="diff"]').trigger('click')
    await flushPromises()

    expect(getDerived).toHaveBeenLastCalledWith(jobId, 'version-2', 'diff')
    expect(wrapper.get('del').text()).toBe('段')
    expect(wrapper.get('ins').text()).toBe('节')
  })

  it('reloads document, issues, and summary with the selected historical version', async () => {
    const analysisApi = createAnalysisApiMock()
    const workspace = mountWorkspace(analysisApi)
    await flushPromises()

    await workspace.selectVersion('version-1')
    await flushPromises()

    expect(analysisApi.getSummary).toHaveBeenLastCalledWith(jobId, {
      version_id: 'version-1'
    })
    expect(analysisApi.getDocumentPage).toHaveBeenLastCalledWith(jobId, {
      version_id: 'version-1',
      cursor: null,
      limit: 100
    })
    expect(analysisApi.getIssues).toHaveBeenLastCalledWith(jobId, {
      version_id: 'version-1',
      cursor: null,
      limit: 50
    })
  })

  it('allows editing only for the active succeeded version by default', async () => {
    const workspace = mountWorkspace()
    await flushPromises()

    expect(workspace.selectedVersionId.value).toBe('version-2')
    expect(workspace.canEditSelectedVersion.value).toBe(true)

    await workspace.selectVersion('version-1')

    expect(workspace.canEditSelectedVersion.value).toBe(false)
  })

  it('keeps active-version default analysis calls unpinned until a historical version is selected', async () => {
    const analysisApi = createAnalysisApiMock()
    const workspace = mountWorkspace(analysisApi)
    await flushPromises()

    await workspace.setFilters({ severity: 'error' })
    await flushPromises()

    expect(analysisApi.getIssues).toHaveBeenLastCalledWith(jobId, {
      severity: 'error',
      cursor: null,
      limit: 50
    })

    await workspace.selectVersion('version-1')
    await flushPromises()
    await workspace.setFilters({ severity: 'warning' })

    expect(analysisApi.getIssues).toHaveBeenLastCalledWith(jobId, {
      version_id: 'version-1',
      severity: 'warning',
      cursor: null,
      limit: 50
    })
  })

  it('rejects visible batch acceptance before a request when an issue lacks a preferred suggestion', async () => {
    const putDecisions = vi.fn()
    const workspace = mountWorkspace(
      createAnalysisApiMock({
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            items: [buildIssue({ suggestions: [] })]
          })
        ),
        putDecisions
      })
    )
    await flushPromises()

    await workspace.decideVisible('accepted')

    expect(putDecisions).not.toHaveBeenCalled()
    expect(workspace.batchDecisionError.value).toContain('没有首选建议')
  })

  it('keeps submitted local draft text when a stale draft save fails', async () => {
    const revisionsApi = createRevisionsApiMock({
      updateDraft: vi.fn().mockRejectedValue(
        new ApiError(409, {
          code: 'stale_draft_revision',
          message: '草稿已过期'
        })
      )
    })
    let draftState!: ReturnType<typeof useEditDraft>
    const Harness = defineComponent({
      setup() {
        draftState = useEditDraft(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    await draftState.begin('version-2')
    draftState.updateBlock('block-1', '本地保留文本')
    await expect(draftState.save()).rejects.toThrow('草稿已过期')

    expect(draftState.localBlocks.value).toEqual([
      { block_id: 'block-1', text: '本地保留文本' }
    ])
    expect(draftState.conflict.value?.code).toBe('stale_draft_revision')
    expect(draftState.conflict.value?.submittedBlocks).toEqual([
      { block_id: 'block-1', text: '本地保留文本' }
    ])
  })

  it('reuses a reanalysis idempotency key for the same draft revision retry and rotates after revision changes', async () => {
    vi.spyOn(Date, 'now')
      .mockReturnValueOnce(1000)
      .mockReturnValueOnce(2000)
      .mockReturnValueOnce(3000)
    const reanalyze = vi
      .fn()
      .mockRejectedValueOnce(new Error('暂时失败'))
      .mockResolvedValueOnce({
        version: buildVersion({ version_id: 'version-3', status: 'queued' }),
        events_url: '/api/v1/jobs/job-1/versions/version-3/events'
      })
      .mockResolvedValueOnce({
        version: buildVersion({ version_id: 'version-4', status: 'queued' }),
        events_url: '/api/v1/jobs/job-1/versions/version-4/events'
      })
    const revisionsApi = createRevisionsApiMock({
      reanalyze,
      updateDraft: vi.fn().mockResolvedValue(buildDraft({ revision: 2 }))
    })
    let draftState!: ReturnType<typeof useEditDraft>
    const Harness = defineComponent({
      setup() {
        draftState = useEditDraft(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    await draftState.begin('version-2')
    await expect(draftState.reanalyze()).rejects.toThrow('暂时失败')
    await draftState.reanalyze()

    const firstKey = reanalyze.mock.calls[0]?.[2].idempotency_key
    expect(reanalyze.mock.calls[1]?.[2].idempotency_key).toBe(firstKey)

    draftState.updateBlock('block-1', '修订后')
    await draftState.save()
    await draftState.reanalyze()

    expect(reanalyze.mock.calls[2]?.[2].idempotency_key).not.toBe(firstKey)
  })

  it('keeps a reanalysis idempotency key after enqueue so same draft revision resubmits reuse it', async () => {
    vi.spyOn(Date, 'now').mockReturnValueOnce(1000).mockReturnValueOnce(2000)
    const reanalyze = vi.fn().mockResolvedValue({
      version: buildVersion({ version_id: 'version-3', status: 'queued' }),
      events_url: '/api/v1/jobs/job-1/versions/version-3/events'
    })
    const revisionsApi = createRevisionsApiMock({ reanalyze })
    let draftState!: ReturnType<typeof useEditDraft>
    const Harness = defineComponent({
      setup() {
        draftState = useEditDraft(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    await draftState.begin('version-2')
    await draftState.reanalyze()
    await draftState.reanalyze()

    expect(reanalyze.mock.calls[1]?.[2].idempotency_key).toBe(
      reanalyze.mock.calls[0]?.[2].idempotency_key
    )
  })

  it('does not reanalyze a stale draft when discard and begin happen while save is pending', async () => {
    const saveResponse = createDeferred<EditDraft>()
    const reanalyze = vi.fn()
    const revisionsApi = createRevisionsApiMock({
      updateDraft: vi.fn().mockReturnValue(saveResponse.promise),
      createDraft: vi
        .fn()
        .mockResolvedValueOnce(buildDraft({ draft_id: 'draft-1' }))
        .mockResolvedValueOnce(buildDraft({ draft_id: 'draft-2' })),
      reanalyze
    })
    let draftState!: ReturnType<typeof useEditDraft>
    const Harness = defineComponent({
      setup() {
        draftState = useEditDraft(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    await draftState.begin('version-2')
    draftState.updateBlock('block-1', '保存后重分析')
    const reanalysis = draftState.reanalyze()
    await draftState.discard()
    await draftState.begin('version-2')
    saveResponse.resolve(buildDraft({ draft_id: 'draft-1', revision: 2 }))

    await expect(reanalysis).rejects.toThrow('Draft request is stale.')
    expect(reanalyze).not.toHaveBeenCalled()
    expect(draftState.draft.value?.draft_id).toBe('draft-2')
  })

  it('does not let a late save response erase newer local draft edits', async () => {
    const saveResponse = createDeferred<EditDraft>()
    const revisionsApi = createRevisionsApiMock({
      updateDraft: vi.fn().mockReturnValue(saveResponse.promise)
    })
    let draftState!: ReturnType<typeof useEditDraft>
    const Harness = defineComponent({
      setup() {
        draftState = useEditDraft(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    await draftState.begin('version-2')
    draftState.updateBlock('block-1', '提交中的文本')
    const save = draftState.save()
    draftState.updateBlock('block-1', '新的本地文本')
    saveResponse.resolve(
      buildDraft({ revision: 2, blocks: [{ block_id: 'block-1', text: '提交中的文本' }] })
    )
    await save

    expect(draftState.localBlocks.value).toEqual([
      { block_id: 'block-1', text: '新的本地文本' }
    ])
    expect(draftState.dirty.value).toBe(true)
  })

  it('ignores reanalysis progress events from an older generation', async () => {
    let progressHandler: ((event: VersionEvent) => void) | null = null
    const revisionsApi = createRevisionsApiMock({
      subscribeVersionEvents: vi.fn().mockImplementation(
        (
          _jobId: string,
          _versionId: string,
          onEvent: (event: VersionEvent) => void
        ) => {
          progressHandler = onEvent
          return vi.fn()
        }
      )
    })
    const workspace = mountWorkspace(createAnalysisApiMock(), revisionsApi)
    await flushPromises()

    await workspace.draft.begin('version-2')
    await workspace.draft.reanalyze()
    const oldProgressHandler = progressHandler as ((event: VersionEvent) => void) | null

    await workspace.draft.begin('version-2')
    await workspace.draft.reanalyze()

    oldProgressHandler?.({
      sequence: 1,
      status: 'analyzing',
      progress: 50,
      message: '旧请求',
      created_at: '2026-08-23T12:01:00Z',
      metadata: null
    })

    expect(workspace.reanalysis.value?.message).not.toBe('旧请求')
  })

  it('ignores derived responses whose decision hash is older than current state', async () => {
    const staleDerived = createDeferred<Awaited<ReturnType<RevisionsApi['getDerived']>>>()
    const freshDerived = createDeferred<Awaited<ReturnType<RevisionsApi['getDerived']>>>()
    const revisionsApi = createRevisionsApiMock({
      getDerived: vi
        .fn()
        .mockReturnValueOnce(staleDerived.promise)
        .mockReturnValueOnce(freshDerived.promise)
    })
    let preview!: ReturnType<typeof useDerivedPreview>
    const Harness = defineComponent({
      setup() {
        preview = useDerivedPreview(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    const staleLoad = preview.load('modified', 'version-2', 'old-hash')
    const freshLoad = preview.load('modified', 'version-2', 'new-hash')

    freshDerived.resolve({
      job_id: jobId,
      version_id: 'version-2',
      decision_snapshot_sha256: 'new-hash',
      blocks: [buildBlock({ text: '新结果' })]
    })
    await freshLoad
    staleDerived.resolve({
      job_id: jobId,
      version_id: 'version-2',
      decision_snapshot_sha256: 'old-hash',
      blocks: [buildBlock({ text: '旧结果' })]
    })
    await staleLoad

    expect(preview.modified.value?.blocks).toEqual([buildBlock({ text: '新结果' })])
  })

  it('ignores a current derived response when its decision hash does not match the expected hash', async () => {
    const revisionsApi = createRevisionsApiMock({
      getDerived: vi
        .fn()
        .mockResolvedValueOnce({
          job_id: jobId,
          version_id: 'version-2',
          decision_snapshot_sha256: 'new-hash',
          blocks: [buildBlock({ text: '新结果' })]
        })
        .mockResolvedValueOnce({
          job_id: jobId,
          version_id: 'version-2',
          decision_snapshot_sha256: 'old-hash',
          blocks: [buildBlock({ text: '不应显示' })]
        })
    })
    let preview!: ReturnType<typeof useDerivedPreview>
    const Harness = defineComponent({
      setup() {
        preview = useDerivedPreview(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    await preview.load('modified', 'version-2', 'new-hash')
    await preview.load('modified', 'version-2', 'new-hash')

    expect(preview.modified.value?.blocks).toEqual([buildBlock({ text: '新结果' })])
    expect(preview.decisionSnapshotSha256.value).toBe('new-hash')
  })

  it('derives the latest undoable batch from authoritative history', async () => {
    const revisionsApi = createRevisionsApiMock({
      listHistory: vi.fn().mockResolvedValue({
        job_id: jobId,
        version_id: 'version-2',
        total: 3,
        items: [
          buildBatch({
            batch_id: 'undo-batch-2',
            operation_type: 'undo',
            undoes_batch_id: 'batch-2',
            created_at: '2026-08-23T12:03:00Z'
          }),
          buildBatch({
            batch_id: 'batch-2',
            operation_type: 'decision',
            created_at: '2026-08-23T12:02:00Z'
          }),
          buildBatch({
            batch_id: 'batch-1',
            operation_type: 'decision',
            created_at: '2026-08-23T12:01:00Z'
          })
        ],
        next_cursor: null
      })
    })
    let history!: ReturnType<typeof useReviewHistory>
    const Harness = defineComponent({
      setup() {
        history = useReviewHistory(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    await history.loadHistory('version-2')

    expect(history.latestBatch.value?.batch_id).toBe('batch-1')
    expect(history.canUndoLatestBatch.value).toBe(true)
  })

  it('updates history state with the returned undo batch', async () => {
    const revisionsApi = createRevisionsApiMock({
      listHistory: vi.fn().mockResolvedValue({
        job_id: jobId,
        version_id: 'version-2',
        total: 2,
        items: [
          buildBatch({
            batch_id: 'batch-2',
            operation_type: 'decision',
            created_at: '2026-08-23T12:02:00Z'
          }),
          buildBatch({
            batch_id: 'batch-1',
            operation_type: 'decision',
            created_at: '2026-08-23T12:01:00Z'
          })
        ],
        next_cursor: null
      }),
      undoBatch: vi.fn().mockResolvedValue(
        buildBatch({
          batch_id: 'undo-batch-2',
          operation_type: 'undo',
          undoes_batch_id: 'batch-2',
          created_at: '2026-08-23T12:03:00Z'
        })
      )
    })
    let history!: ReturnType<typeof useReviewHistory>
    const Harness = defineComponent({
      setup() {
        history = useReviewHistory(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    await history.loadHistory('version-2')
    await history.undoLatestBatch()

    expect(history.historyPage.value?.items[0]?.batch_id).toBe('undo-batch-2')
    expect(history.latestBatch.value?.batch_id).toBe('batch-1')
    expect(history.canUndoLatestBatch.value).toBe(true)
  })

  it('keeps a locally recorded decision when an older history load resolves later', async () => {
    const historyResponse = createDeferred<OperationBatchPage>()
    const revisionsApi = createRevisionsApiMock({
      listHistory: vi.fn().mockReturnValue(historyResponse.promise)
    })
    let history!: ReturnType<typeof useReviewHistory>
    const Harness = defineComponent({
      setup() {
        history = useReviewHistory(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    const load = history.loadHistory('version-2')
    history.recordDecisionBatch('local-batch', 'version-2', 1)
    historyResponse.resolve({
      job_id: jobId,
      version_id: 'version-2',
      total: 0,
      items: [],
      next_cursor: null
    })
    await load

    expect(history.latestBatch.value?.batch_id).toBe('local-batch')
  })

  it('keeps a local undo when an older history load resolves later', async () => {
    const historyResponse = createDeferred<OperationBatchPage>()
    const revisionsApi = createRevisionsApiMock({
      listHistory: vi.fn().mockReturnValue(historyResponse.promise),
      undoBatch: vi.fn().mockResolvedValue(
        buildBatch({
          batch_id: 'undo-local-batch',
          operation_type: 'undo',
          undoes_batch_id: 'local-batch',
          created_at: '2026-08-23T12:01:00Z'
        })
      )
    })
    let history!: ReturnType<typeof useReviewHistory>
    const Harness = defineComponent({
      setup() {
        history = useReviewHistory(jobId, revisionsApi)
        return {}
      },
      template: '<div />'
    })
    mount(Harness)

    history.recordDecisionBatch('local-batch', 'version-2', 1)
    const load = history.loadHistory('version-2')
    await history.undoLatestBatch()
    historyResponse.resolve({
      job_id: jobId,
      version_id: 'version-2',
      total: 1,
      items: [buildBatch({ batch_id: 'local-batch' })],
      next_cursor: null
    })
    await load

    expect(history.latestBatch.value).toBeNull()
    expect(history.historyPage.value?.items[0]?.batch_id).toBe('undo-local-batch')
  })

  it('starts a 10-second undo deadline after a successful decision batch', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-08-23T12:00:00Z'))
    const workspace = mountWorkspace()
    await flushPromises()

    await workspace.decideVisible('accepted')
    await flushPromises()

    expect(workspace.history.latestBatch.value?.batch_id).toBe('batch-1')
    expect(workspace.history.undoToastVisible.value).toBe(true)
    expect(workspace.history.undoToastDeadline.value?.toISOString()).toBe(
      '2026-08-23T12:00:10.000Z'
    )
  })

  it('keeps long-term undo available after the 10-second toast deadline passes', async () => {
    vi.useFakeTimers()
    const workspace = mountWorkspace()
    await flushPromises()

    await workspace.decideVisible('accepted')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(10_000)
    await flushPromises()

    expect(workspace.history.undoToastVisible.value).toBe(false)
    expect(workspace.history.canUndoLatestBatch.value).toBe(true)
    expect(workspace.history.latestBatch.value?.batch_id).toBe('batch-1')
  })

  it('reloads workspace analysis and clears derived preview after undo', async () => {
    const analysisApi = createAnalysisApiMock()
    const revisionsApi = createRevisionsApiMock({
      listHistory: vi.fn().mockResolvedValue({
        job_id: jobId,
        version_id: 'version-2',
        total: 1,
        items: [buildBatch({ batch_id: 'batch-1' })],
        next_cursor: null
      }),
      undoBatch: vi.fn().mockResolvedValue(
        buildBatch({
          batch_id: 'undo-batch-1',
          operation_type: 'undo',
          undoes_batch_id: 'batch-1'
        })
      )
    })
    const workspace = mountWorkspace(analysisApi, revisionsApi)
    await flushPromises()
    await workspace.derivedPreview.load('modified', 'version-2', null)
    expect(workspace.derivedPreview.modified.value).not.toBeNull()
    const summaryCalls = vi.mocked(analysisApi.getSummary).mock.calls.length
    const issueCalls = vi.mocked(analysisApi.getIssues).mock.calls.length

    await workspace.history.undoLatestBatch()
    await flushPromises()

    expect(workspace.derivedPreview.modified.value).toBeNull()
    expect(analysisApi.getSummary).toHaveBeenCalledTimes(summaryCalls + 1)
    expect(analysisApi.getIssues).toHaveBeenCalledTimes(issueCalls + 1)
  })

  it('ignores a decision response submitted for a version that is no longer selected', async () => {
    const decisionResponse = createDeferred<DecisionBatchResponse>()
    const analysisApi = createAnalysisApiMock({
      putDecisions: vi.fn().mockReturnValue(decisionResponse.promise)
    })
    const workspace = mountWorkspace(analysisApi)
    await flushPromises()

    void workspace.decideVisible('accepted')
    await flushPromises()
    await workspace.selectVersion('version-1')
    await flushPromises()
    const summaryCalls = vi.mocked(analysisApi.getSummary).mock.calls.length
    const issueCalls = vi.mocked(analysisApi.getIssues).mock.calls.length

    decisionResponse.resolve({
      batch_id: 'stale-batch',
      outcomes: [
        {
          issue_id: 'issue-1',
          status: 'applied',
          code: null,
          decision: {
            issue_id: 'issue-1',
            issue_version: 1,
            revision: 1,
            action: 'accepted',
            replacement: '首段',
            suggestion_id: 'suggestion-1',
            updated_at: '2026-08-23T12:00:00Z'
          }
        }
      ]
    })
    await flushPromises()

    expect(workspace.history.latestBatch.value?.batch_id).not.toBe('stale-batch')
    expect(analysisApi.getSummary).toHaveBeenCalledTimes(summaryCalls)
    expect(analysisApi.getIssues).toHaveBeenCalledTimes(issueCalls)
  })

  it('accepts an edited candidate as the final replacement', async () => {
    const putDecisions = vi.fn().mockResolvedValue(buildAppliedResponse({
      issue_id: 'issue-1',
      issue_version: 1,
      revision: 1,
      action: 'accepted',
      replacement: '人工调整',
      suggestion_id: 'suggestion-1',
      updated_at: '2026-08-23T12:00:00Z'
    }))
    const analysisApi = createAnalysisApiMock({
      getIssues: vi.fn().mockResolvedValue(
        buildIssuePage({
          items: [
            buildIssue({
              suggestion: '候选一',
              suggestions: [
                {
                  suggestion_id: 'suggestion-1',
                  text: '候选一',
                  source: 'rule',
                  explanation: '规则候选',
                  rank: 1,
                  preferred: true
                },
                {
                  suggestion_id: 'suggestion-2',
                  text: '候选二',
                  source: 'llm',
                  explanation: '模型候选',
                  rank: 2,
                  preferred: false
                }
              ]
            })
          ]
        })
      ),
      putDecisions
    })
    const wrapper = mountReviewWorkspaceView(analysisApi)
    await flushPromises()

    await wrapper.get('[name="suggestion"]').setValue('候选一')
    await wrapper.get('[aria-label="最终替换内容"]').setValue('人工调整')
    await wrapper.get('[name="accept"]').trigger('click')

    expect(putDecisions).toHaveBeenCalledWith(jobId, [{
      issue_id: 'issue-1',
      issue_version: 1,
      expected_revision: 0,
      action: 'accepted',
      replacement: '人工调整',
      suggestion_id: 'suggestion-1'
    }])
  })

  it('restores an existing decision to unreviewed through a reversible command', async () => {
    const putDecisions = vi.fn().mockResolvedValue(buildAppliedResponse(null))
    const wrapper = mountReviewWorkspaceView(
      createAnalysisApiMock({
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            items: [
              buildIssue({
                decision: {
                  issue_version: 1,
                  revision: 3,
                  action: 'accepted',
                  replacement: '已接受',
                  suggestion_id: 'suggestion-1',
                  updated_at: '2026-08-23T12:00:00Z'
                }
              })
            ]
          })
        ),
        putDecisions
      })
    )
    await flushPromises()

    await wrapper.get('button[name="restore-unreviewed"]').trigger('click')

    expect(putDecisions).toHaveBeenCalledWith(jobId, [{
      issue_id: 'issue-1',
      issue_version: 1,
      expected_revision: 3,
      action: 'unreviewed',
      replacement: null,
      suggestion_id: null
    }])
  })


  it('accepts a legacy single suggestion with an explicit null suggestion id', async () => {
    const putDecisions = vi.fn().mockResolvedValue(buildAppliedResponse({
      issue_id: 'issue-1',
      issue_version: 1,
      revision: 1,
      action: 'accepted',
      replacement: '旧建议',
      suggestion_id: null,
      updated_at: '2026-08-23T12:00:00Z'
    }))
    const wrapper = mountReviewWorkspaceView(
      createAnalysisApiMock({
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            items: [buildIssue({ suggestion: '旧建议', suggestions: undefined })]
          })
        ),
        putDecisions
      })
    )
    await flushPromises()

    await wrapper.get('button[name="accept"]').trigger('click')

    expect(putDecisions).toHaveBeenCalledWith(jobId, [{
      issue_id: 'issue-1',
      issue_version: 1,
      expected_revision: 0,
      action: 'accepted',
      replacement: '旧建议',
      suggestion_id: null
    }])
  })

  it('resubmits an accepted decision preserving its null suggestion id', async () => {
    const putDecisions = vi.fn().mockResolvedValue(buildAppliedResponse({
      issue_id: 'issue-1',
      issue_version: 1,
      revision: 5,
      action: 'accepted',
      replacement: '已存替换',
      suggestion_id: null,
      updated_at: '2026-08-23T12:00:00Z'
    }))
    const wrapper = mountReviewWorkspaceView(
      createAnalysisApiMock({
        getIssues: vi.fn().mockResolvedValue(
          buildIssuePage({
            items: [
              buildIssue({
                decision: {
                  issue_version: 1,
                  revision: 4,
                  action: 'accepted',
                  replacement: '已存替换',
                  suggestion_id: null,
                  updated_at: '2026-08-23T11:00:00Z'
                }
              })
            ]
          })
        ),
        putDecisions
      })
    )
    await flushPromises()

    await wrapper.get('button[name="accept"]').trigger('click')

    expect(putDecisions).toHaveBeenCalledWith(jobId, [{
      issue_id: 'issue-1',
      issue_version: 1,
      expected_revision: 4,
      action: 'accepted',
      replacement: '已存替换',
      suggestion_id: null
    }])
  })

  it('searches draft text only while the draft editor is visible', async () => {
    const wrapper = mountReviewWorkspaceView(
      createAnalysisApiMock({
        getDocumentPage: vi.fn().mockResolvedValue(
          buildDocumentPage({
            blocks: [buildBlock({ text: '原文内容' })],
            total_blocks: 1
          })
        )
      }),
      createRevisionsApiMock({
        createDraft: vi.fn().mockResolvedValue(
          buildDraft({ blocks: [{ block_id: 'block-1', text: '草稿专有词' }] })
        ),
        updateDraft: vi.fn().mockResolvedValue(
          buildDraft({ revision: 2, blocks: [{ block_id: 'block-1', text: '草稿专有词' }] })
        ),
        reanalyze: vi.fn().mockResolvedValue({
          version: buildVersion({ version_id: 'version-3', status: 'queued' }),
          events_url: '/api/v1/jobs/job-1/versions/version-3/events'
        })
      })
    )
    await flushPromises()

    await wrapper.get('button[name="edit-version"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-tool="search"]').trigger('click')
    await wrapper.get('[aria-label="查找内容"]').setValue('草稿专有词')
    await flushPromises()
    expect(wrapper.get('[data-testid="find-status"]').text()).toContain('第 1 / 1 处')

    await wrapper.get('button[name="save-reanalyze"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[aria-label="替换为"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="find-status"]').text()).toContain('未找到匹配')
  })

  it('does not undo a previous version batch after switching versions before history reloads', async () => {
    const historyResponse = createDeferred<OperationBatchPage>()
    const undoBatch = vi.fn().mockResolvedValue(buildBatch({ operation_type: 'undo' }))
    const workspace = mountWorkspace(
      createAnalysisApiMock(),
      createRevisionsApiMock({
        listHistory: vi
          .fn()
          .mockResolvedValueOnce({
            job_id: jobId,
            version_id: 'version-2',
            total: 0,
            items: [],
            next_cursor: null
          })
          .mockReturnValueOnce(historyResponse.promise),
        undoBatch
      })
    )
    await flushPromises()
    await workspace.decideVisible('accepted')
    await flushPromises()

    const switching = workspace.selectVersion('version-1')
    await flushPromises()
    await workspace.history.undoLatestBatch()

    expect(undoBatch).not.toHaveBeenCalled()
    historyResponse.resolve({
      job_id: jobId,
      version_id: 'version-1',
      total: 0,
      items: [],
      next_cursor: null
    })
    await switching
  })

  it('shows find with flags and clear in review mode while hiding replacement controls', async () => {
    const wrapper = mountReviewWorkspaceView(
      createAnalysisApiMock({
        getDocumentPage: vi.fn().mockResolvedValue(
          buildDocumentPage({
            blocks: [buildBlock({ text: 'Item item ITEM' })],
            total_blocks: 1
          })
        )
      })
    )
    await flushPromises()

    await wrapper.get('[data-tool="search"]').trigger('click')
    await wrapper.get('[aria-label="查找内容"]').setValue('item')
    await flushPromises()

    expect(wrapper.get('[data-testid="find-status"]').text()).toContain('第 1 / 3 处')
    expect(wrapper.find('[aria-label="替换为"]').exists()).toBe(false)
    expect(wrapper.find('button[name="replace-current"]').exists()).toBe(false)
    expect(wrapper.find('button[name="replace-all"]').exists()).toBe(false)

    await wrapper.get('[aria-label="区分大小写"]').setValue(true)
    await flushPromises()
    expect(wrapper.get('[data-testid="find-status"]').text()).toContain('第 1 / 1 处')

    await wrapper.get('[aria-label="使用正则表达式"]').setValue(true)
    await wrapper.get('[aria-label="区分大小写"]').setValue(false)
    await wrapper.get('[aria-label="查找内容"]').setValue('item|ITEM')
    await flushPromises()
    expect(wrapper.get('[data-testid="find-status"]').text()).toContain('第 1 / 3 处')

    await wrapper.get('button[name="clear-find"]').trigger('click')
    expect((wrapper.get('[aria-label="查找内容"]').element as HTMLInputElement).value).toBe('')
  })

  it('surfaces invalid regex errors inline without navigating matches', async () => {
    const wrapper = mountReviewWorkspaceView()
    await flushPromises()

    await wrapper.get('[data-tool="search"]').trigger('click')
    await wrapper.get('[aria-label="使用正则表达式"]').setValue(true)
    await wrapper.get('[aria-label="查找内容"]').setValue('(')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('正则表达式无效')
    expect(wrapper.get('[data-testid="find-status"]').text()).toContain('正则表达式无效')
    expect(wrapper.get('button[name="next-match"]').attributes('disabled')).toBeDefined()
  })

  it('supports Enter and Shift+Enter match navigation', async () => {
    const wrapper = mountReviewWorkspaceView(
      createAnalysisApiMock({
        getDocumentPage: vi.fn().mockResolvedValue(
          buildDocumentPage({
            blocks: [buildBlock({ text: '项目一 项目二 项目三' })],
            total_blocks: 1
          })
        )
      })
    )
    await flushPromises()

    await wrapper.get('[data-tool="search"]').trigger('click')
    await wrapper.get('[aria-label="查找内容"]').setValue('项目')
    await flushPromises()
    await wrapper.get('[aria-label="查找内容"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(wrapper.get('[data-testid="find-status"]').text()).toContain('第 2 / 3 处')

    await wrapper.get('[aria-label="查找内容"]').trigger('keydown', { key: 'Enter', shiftKey: true })
    await flushPromises()
    expect(wrapper.get('[data-testid="find-status"]').text()).toContain('第 1 / 3 处')
  })

  it('replaces the current and all search matches only in an editable draft', async () => {
    const updateDraft = vi.fn().mockResolvedValue(
      buildDraft({
        revision: 2,
        blocks: [{ block_id: 'block-1', text: '条目一 条目二 条目三' }]
      })
    )
    const wrapper = mountReviewWorkspaceView(
      createAnalysisApiMock(),
      createRevisionsApiMock({
        createDraft: vi.fn().mockResolvedValue(
          buildDraft({
            blocks: [{ block_id: 'block-1', text: '项目一 项目二 项目三' }]
          })
        ),
        updateDraft
      })
    )
    await flushPromises()

    await wrapper.get('button[name="edit-version"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-tool="search"]').trigger('click')
    await wrapper.get('[aria-label="查找内容"]').setValue('项目')
    await wrapper.get('[aria-label="替换为"]').setValue('条目')
    await wrapper.get('button[name="replace-current"]').trigger('click')
    await flushPromises()

    expect((wrapper.get('textarea[aria-label="第 1 段"]').element as HTMLTextAreaElement).value).toBe(
      '条目一 项目二 项目三'
    )

    await wrapper.get('button[name="replace-all"]').trigger('click')
    await flushPromises()
    expect((wrapper.get('textarea[aria-label="第 1 段"]').element as HTMLTextAreaElement).value).toBe(
      '条目一 条目二 条目三'
    )
    expect(wrapper.emitted('dirtyChange')?.at(-1)).toEqual([true])
  })

  it('shows toast undo and history undo using the same history state', async () => {
    const undoBatch = vi.fn().mockResolvedValue(
      buildBatch({
        batch_id: 'undo-batch-1',
        operation_type: 'undo',
        undoes_batch_id: 'batch-1'
      })
    )
    const wrapper = mountReviewWorkspaceView(
      createAnalysisApiMock(),
      createRevisionsApiMock({ undoBatch })
    )
    await flushPromises()

    await wrapper.get('button[name="accept"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="status"][data-testid="undo-toast"]').text()).toContain('可撤销')
    await wrapper.get('[data-testid="undo-toast"] button[name="undo-latest"]').trigger('click')
    await flushPromises()
    expect(undoBatch).toHaveBeenCalledWith(jobId, 'batch-1')

    await wrapper.get('button[name="accept"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-tool="history"]').trigger('click')
    await wrapper.get('[data-testid="history-undo-latest"]').trigger('click')
    await flushPromises()

    expect(undoBatch).toHaveBeenCalledTimes(2)
  })

  it('shows undo conflict messages in the toast and history panel', async () => {
    const wrapper = mountReviewWorkspaceView(
      createAnalysisApiMock(),
      createRevisionsApiMock({
        undoBatch: vi.fn().mockRejectedValue(new Error('历史已变化，请刷新后重试'))
      })
    )
    await flushPromises()

    await wrapper.get('button[name="accept"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-testid="undo-toast"] button[name="undo-latest"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-testid="undo-toast"]').text()).toContain('历史已变化，请刷新后重试')
    await wrapper.get('[data-tool="history"]').trigger('click')
    expect(wrapper.get('[data-testid="operation-history"]').text()).toContain('历史已变化，请刷新后重试')
  })

})
