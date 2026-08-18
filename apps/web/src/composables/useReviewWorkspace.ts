import {
  computed,
  inject,
  onScopeDispose,
  reactive,
  ref,
  type ComputedRef,
  type Ref
} from 'vue'

import { analysisApiKey } from '../api/analysis'
import type {
  AnalysisSummaryResponse,
  CheckerFailureMap,
  DocumentBlock,
  DocumentPageResponse,
  Issue,
  IssuesQuery,
  IssuePageResponse
} from '../types/analysis'

const DOCUMENT_PAGE_LIMIT = 100
const ISSUE_PAGE_LIMIT = 50

export type ReviewIssueFilters = Omit<IssuesQuery, 'cursor' | 'limit'>

interface LoadingState {
  summary: boolean
  document: boolean
  issues: boolean
}

interface ErrorState {
  summary: string | null
  document: string | null
  issues: string | null
}

interface PageRequest {
  cursor: string | null
  append: boolean
}

export interface ReviewWorkspaceState {
  summary: Ref<AnalysisSummaryResponse | null>
  filters: Ref<ReviewIssueFilters>
  blocks: ComputedRef<DocumentBlock[]>
  issues: ComputedRef<Issue[]>
  selectedIssueId: Ref<string | null>
  selectedIssue: ComputedRef<Issue | null>
  selectedBlockId: ComputedRef<string | null>
  blockCursor: Ref<string | null>
  issueCursor: Ref<string | null>
  loading: LoadingState
  errors: ErrorState
  checkerFailures: ComputedRef<CheckerFailureMap>
  selectIssue(issueId: string): void
  selectHighlight(issueId: string): void
  setFilters(filters: ReviewIssueFilters): Promise<void>
  loadNextBlocks(): Promise<void>
  loadNextIssues(): Promise<void>
  retrySummary(): Promise<void>
  retryDocument(): Promise<void>
  retryIssues(): Promise<void>
}

export function useReviewWorkspace(jobId: string): ReviewWorkspaceState {
  const injectedAnalysisApi = inject(analysisApiKey)

  if (!injectedAnalysisApi) {
    throw new Error('AnalysisApi is not provided.')
  }

  const analysisApi = injectedAnalysisApi

  const summary = ref<AnalysisSummaryResponse | null>(null)
  const filters = ref<ReviewIssueFilters>({})
  const blocksById = ref<Record<string, DocumentBlock>>({})
  const blockIds = ref<string[]>([])
  const issuesById = ref<Record<string, Issue>>({})
  const issueIds = ref<string[]>([])
  const selectedIssueId = ref<string | null>(null)
  const blockCursor = ref<string | null>(null)
  const issueCursor = ref<string | null>(null)
  const documentCheckerFailures = ref<CheckerFailureMap>({})
  const issueCheckerFailures = ref<CheckerFailureMap>({})
  const loading = reactive<LoadingState>({
    summary: false,
    document: false,
    issues: false
  })
  const errors = reactive<ErrorState>({
    summary: null,
    document: null,
    issues: null
  })

  let active = true
  let summaryGeneration = 0
  let documentGeneration = 0
  let issueGeneration = 0
  let lastDocumentRequest: PageRequest = { cursor: null, append: false }
  let lastIssueRequest: PageRequest = { cursor: null, append: false }

  const blocks = computed(() =>
    blockIds.value.flatMap((blockId) => {
      const block = blocksById.value[blockId]
      return block ? [block] : []
    })
  )
  const issues = computed(() =>
    issueIds.value.flatMap((issueId) => {
      const issue = issuesById.value[issueId]
      return issue ? [issue] : []
    })
  )
  const selectedIssue = computed(() => {
    const issueId = selectedIssueId.value
    return issueId ? issuesById.value[issueId] ?? null : null
  })
  const selectedBlockId = computed(() => selectedIssue.value?.block_id ?? null)
  const checkerFailures = computed<CheckerFailureMap>(() => ({
    ...summary.value?.checker_failures,
    ...documentCheckerFailures.value,
    ...issueCheckerFailures.value
  }))

  function isCurrent(generation: number, currentGeneration: number): boolean {
    return active && generation === currentGeneration
  }

  async function loadSummary(): Promise<void> {
    const generation = ++summaryGeneration
    loading.summary = true
    errors.summary = null

    try {
      const response = await analysisApi.getSummary(jobId)
      if (!isCurrent(generation, summaryGeneration)) {
        return
      }
      summary.value = response
    } catch (error) {
      if (!isCurrent(generation, summaryGeneration)) {
        return
      }
      errors.summary = errorMessage(error, '无法加载问题总览。')
    } finally {
      if (isCurrent(generation, summaryGeneration)) {
        loading.summary = false
      }
    }
  }

  async function loadDocumentPage(cursor: string | null, append: boolean): Promise<void> {
    const generation = ++documentGeneration
    lastDocumentRequest = { cursor, append }
    loading.document = true
    errors.document = null

    try {
      const response = await analysisApi.getDocumentPage(jobId, {
        cursor,
        limit: DOCUMENT_PAGE_LIMIT
      })
      if (!isCurrent(generation, documentGeneration)) {
        return
      }
      applyDocumentPage(response, append)
    } catch (error) {
      if (!isCurrent(generation, documentGeneration)) {
        return
      }
      errors.document = errorMessage(error, '无法加载文档内容。')
    } finally {
      if (isCurrent(generation, documentGeneration)) {
        loading.document = false
      }
    }
  }

  function applyDocumentPage(response: DocumentPageResponse, append: boolean): void {
    const nextById = append ? { ...blocksById.value } : {}
    const nextIds = append ? [...blockIds.value] : []
    const seen = new Set(nextIds)

    for (const block of response.blocks) {
      nextById[block.block_id] = block
      if (!seen.has(block.block_id)) {
        nextIds.push(block.block_id)
        seen.add(block.block_id)
      }
    }

    blocksById.value = nextById
    blockIds.value = nextIds
    blockCursor.value = response.next_cursor
    documentCheckerFailures.value = response.checker_failures
  }

  async function loadIssuePage(cursor: string | null, append: boolean): Promise<void> {
    const generation = ++issueGeneration
    lastIssueRequest = { cursor, append }
    loading.issues = true
    errors.issues = null

    try {
      const response = await analysisApi.getIssues(jobId, {
        ...filters.value,
        cursor,
        limit: ISSUE_PAGE_LIMIT
      })
      if (!isCurrent(generation, issueGeneration)) {
        return
      }
      applyIssuePage(response, append)
    } catch (error) {
      if (!isCurrent(generation, issueGeneration)) {
        return
      }
      errors.issues = errorMessage(error, '无法加载问题列表。')
    } finally {
      if (isCurrent(generation, issueGeneration)) {
        loading.issues = false
      }
    }
  }

  function applyIssuePage(response: IssuePageResponse, append: boolean): void {
    const nextById = append ? { ...issuesById.value } : {}
    const nextIds = append ? [...issueIds.value] : []
    const seen = new Set(nextIds)

    for (const issue of response.items) {
      nextById[issue.issue_id] = issue
      if (!seen.has(issue.issue_id)) {
        nextIds.push(issue.issue_id)
        seen.add(issue.issue_id)
      }
    }

    issuesById.value = nextById
    issueIds.value = nextIds
    issueCursor.value = response.next_cursor
    issueCheckerFailures.value = response.checker_failures

    if (
      !selectedIssueId.value ||
      !Object.prototype.hasOwnProperty.call(nextById, selectedIssueId.value)
    ) {
      selectedIssueId.value = nextIds[0] ?? null
    }
  }

  function selectIssue(issueId: string): void {
    if (issuesById.value[issueId]) {
      selectedIssueId.value = issueId
    }
  }

  function selectHighlight(issueId: string): void {
    selectIssue(issueId)
  }

  async function setFilters(nextFilters: ReviewIssueFilters): Promise<void> {
    filters.value = { ...nextFilters }
    await loadIssuePage(null, false)
  }

  async function loadNextBlocks(): Promise<void> {
    if (loading.document || !blockCursor.value) {
      return
    }
    await loadDocumentPage(blockCursor.value, true)
  }

  async function loadNextIssues(): Promise<void> {
    if (loading.issues || !issueCursor.value) {
      return
    }
    await loadIssuePage(issueCursor.value, true)
  }

  function retrySummary(): Promise<void> {
    return loadSummary()
  }

  function retryDocument(): Promise<void> {
    return loadDocumentPage(lastDocumentRequest.cursor, lastDocumentRequest.append)
  }

  function retryIssues(): Promise<void> {
    return loadIssuePage(lastIssueRequest.cursor, lastIssueRequest.append)
  }

  void Promise.allSettled([
    loadSummary(),
    loadDocumentPage(null, false),
    loadIssuePage(null, false)
  ])

  onScopeDispose(() => {
    active = false
    summaryGeneration += 1
    documentGeneration += 1
    issueGeneration += 1
  })

  return {
    summary,
    filters,
    blocks,
    issues,
    selectedIssueId,
    selectedIssue,
    selectedBlockId,
    blockCursor,
    issueCursor,
    loading,
    errors,
    checkerFailures,
    selectIssue,
    selectHighlight,
    setFilters,
    loadNextBlocks,
    loadNextIssues,
    retrySummary,
    retryDocument,
    retryIssues
  }
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback
}
