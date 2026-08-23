import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { analysisApiKey, type AnalysisApi } from '../src/api/analysis'
import { revisionsApiKey, type RevisionsApi } from '../src/api/revisions'
import { useDerivedPreview } from '../src/composables/useDerivedPreview'
import { useEditDraft } from '../src/composables/useEditDraft'
import { useReviewWorkspace, type ReviewWorkspaceState } from '../src/composables/useReviewWorkspace'
import { ApiError } from '../src/types/api'
import type {
  AnalysisSummaryResponse,
  DecisionBatchResponse,
  DocumentBlock,
  DocumentPageResponse,
  Issue,
  IssuePageResponse
} from '../src/types/analysis'
import type {
  DocumentVersion,
  EditDraft,
  OperationBatch,
  OperationBatchPage,
  VersionEvent,
  VersionListResponse
} from '../src/types/revisions'

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

afterEach(() => {
  vi.restoreAllMocks()
  vi.useRealTimers()
})

describe('review editing state', () => {
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
})
