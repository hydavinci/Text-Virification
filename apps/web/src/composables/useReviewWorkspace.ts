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
  DecisionCommand,
  DocumentBlock,
  DocumentPageResponse,
  Issue,
  IssueDecisionSummary,
  IssuesQuery,
  IssuePageResponse
} from '../types/analysis'
import type { DecisionAction } from '../types/review'

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

interface FailedDecision {
  command: DecisionCommand
}

interface DecisionRequestGuard {
  issueId: string
  generation: number
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
  decisionError: Ref<string | null>
  decisionAnnouncement: Ref<string>
  selectIssue(issueId: string): void
  selectHighlight(issueId: string): void
  setFilters(filters: ReviewIssueFilters): Promise<void>
  decide(action: DecisionAction, replacement?: string): Promise<void>
  retryDecision(): Promise<void>
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
  const decisionError = ref<string | null>(null)
  const decisionAnnouncement = ref('')
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
  let localizationGeneration = 0
  let summaryRequest: Promise<void> | null = null
  let documentRequest: Promise<void> | null = null
  let issueRequest: Promise<void> | null = null
  let failedDecision: FailedDecision | null = null
  let explicitlySelectedIssueId: string | null = null
  let lastDocumentRequest: PageRequest = { cursor: null, append: false }
  let lastIssueRequest: PageRequest = { cursor: null, append: false }
  const authoritativeDecisions = new Map<string, IssueDecisionSummary | null>()
  const decisionGenerations = new Map<string, number>()

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

  function loadSummary(): Promise<void> {
    const generation = ++summaryGeneration
    loading.summary = true
    errors.summary = null

    const request = (async () => {
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
    })()

    summaryRequest = request
    void request.finally(() => {
      if (summaryRequest === request) {
        summaryRequest = null
      }
    })
    return request
  }

  function loadDocumentPage(cursor: string | null, append: boolean): Promise<void> {
    const generation = ++documentGeneration
    lastDocumentRequest = { cursor, append }
    loading.document = true
    errors.document = null

    const request = (async () => {
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
    })()

    documentRequest = request
    void request.finally(() => {
      if (documentRequest === request) {
        documentRequest = null
      }
    })
    return request
  }

  function loadIssuePage(
    cursor: string | null,
    append: boolean,
    decisionGuard?: DecisionRequestGuard
  ): Promise<void> {
    const generation = ++issueGeneration
    lastIssueRequest = { cursor, append }
    loading.issues = true
    errors.issues = null

    const request = (async () => {
      try {
        const response = await analysisApi.getIssues(jobId, {
          ...filters.value,
          cursor,
          limit: ISSUE_PAGE_LIMIT
        })
        if (
          !isCurrent(generation, issueGeneration) ||
          (decisionGuard &&
            !isDecisionCurrent(decisionGuard.issueId, decisionGuard.generation))
        ) {
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
    })()

    issueRequest = request
    void request.finally(() => {
      if (issueRequest === request) {
        issueRequest = null
      }
    })
    return request
  }

  async function localizeSelectedIssue(
    issueId: string,
    generation: number
  ): Promise<void> {
    const visitedCursors = new Set<string>()

    while (isLocalizationCurrent(issueId, generation)) {
      const issue = issuesById.value[issueId]
      if (!issue) {
        return
      }
      if (blocksById.value[issue.block_id]) {
        if (explicitlySelectedIssueId === issueId) {
          explicitlySelectedIssueId = null
        }
        return
      }
      if (documentRequest) {
        await documentRequest
        continue
      }
      if (errors.document) {
        return
      }

      const cursor = blockCursor.value
      if (!cursor || visitedCursors.has(cursor)) {
        return
      }

      visitedCursors.add(cursor)
      await loadDocumentPage(cursor, true)
    }
  }

  function isLocalizationCurrent(issueId: string, generation: number): boolean {
    return (
      active &&
      generation === localizationGeneration &&
      explicitlySelectedIssueId === issueId &&
      selectedIssueId.value === issueId
    )
  }

  function startSelectedIssueLocalization(issueId: string): void {
    const generation = ++localizationGeneration
    void localizeSelectedIssue(issueId, generation)
  }

  function resumeSelectedIssueLocalization(): void {
    const issueId = explicitlySelectedIssueId
    if (issueId && selectedIssueId.value === issueId) {
      startSelectedIssueLocalization(issueId)
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

  function applyIssuePage(response: IssuePageResponse, append: boolean): void {
    const nextById = append ? { ...issuesById.value } : {}
    const nextIds = append ? [...issueIds.value] : []
    const seen = new Set(nextIds)

    if (!append) {
      authoritativeDecisions.clear()
    }

    for (const issue of response.items) {
      nextById[issue.issue_id] = issue
      authoritativeDecisions.set(issue.issue_id, issue.decision)
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
      explicitlySelectedIssueId = issueId
      startSelectedIssueLocalization(issueId)
    }
  }

  function selectHighlight(issueId: string): void {
    if (issuesById.value[issueId]) {
      localizationGeneration += 1
      explicitlySelectedIssueId = null
      selectedIssueId.value = issueId
    }
  }

  async function setFilters(nextFilters: ReviewIssueFilters): Promise<void> {
    filters.value = normalizeFilters(nextFilters)
    localizationGeneration += 1
    explicitlySelectedIssueId = null
    selectedIssueId.value = null
    issueCursor.value = null
    lastIssueRequest = { cursor: null, append: false }
    await loadIssuePage(null, false)
  }

  function nextDecisionGeneration(issueId: string): number {
    const generation = (decisionGenerations.get(issueId) ?? 0) + 1
    decisionGenerations.set(issueId, generation)
    return generation
  }

  function isDecisionCurrent(issueId: string, generation: number): boolean {
    return active && decisionGenerations.get(issueId) === generation
  }

  function setIssueDecision(
    issueId: string,
    decision: IssueDecisionSummary | null
  ): void {
    const issue = issuesById.value[issueId]
    if (!issue) {
      return
    }

    issuesById.value = {
      ...issuesById.value,
      [issueId]: {
        ...issue,
        decision
      }
    }
  }

  function optimisticDecision(command: DecisionCommand): IssueDecisionSummary {
    const fields = {
      issue_version: command.issue_version,
      updated_at: new Date().toISOString()
    }

    if (command.action === 'custom') {
      return {
        ...fields,
        action: 'custom',
        replacement: command.replacement
      }
    }

    return {
      ...fields,
      action: command.action,
      replacement: null
    }
  }

  function decisionCommand(
    issue: Issue,
    action: DecisionAction,
    replacement?: string
  ): DecisionCommand | null {
    if (issue.document_version === null) {
      return null
    }

    const fields = {
      issue_id: issue.issue_id,
      issue_version: issue.document_version
    }

    if (action === 'custom') {
      if (!isValidCustomReplacement(replacement)) {
        return null
      }
      return {
        ...fields,
        action: 'custom',
        replacement
      }
    }

    return {
      ...fields,
      action
    }
  }

  async function submitDecision(command: DecisionCommand): Promise<void> {
    const generation = nextDecisionGeneration(command.issue_id)
    decisionError.value = null
    decisionAnnouncement.value = ''
    failedDecision = null
    setIssueDecision(command.issue_id, optimisticDecision(command))

    try {
      const response = await analysisApi.putDecisions(jobId, [command])
      if (!isDecisionCurrent(command.issue_id, generation)) {
        return
      }

      const outcome = response.outcomes.find(
        (item) => item.issue_id === command.issue_id
      )
      if (!outcome) {
        throw new Error('保存处理结果失败：服务器未返回对应结果。')
      }

      if (outcome.status === 'applied') {
        authoritativeDecisions.set(command.issue_id, outcome.decision)
        setIssueDecision(command.issue_id, outcome.decision)
        return
      }

      setIssueDecision(
        command.issue_id,
        authoritativeDecisions.get(command.issue_id) ?? null
      )
      decisionAnnouncement.value = '结果已更新，请重新确认'
      await Promise.all([
        loadIssuePage(null, false, {
          issueId: command.issue_id,
          generation
        }),
        loadSummary()
      ])
    } catch (error) {
      if (!isDecisionCurrent(command.issue_id, generation)) {
        return
      }

      setIssueDecision(
        command.issue_id,
        authoritativeDecisions.get(command.issue_id) ?? null
      )
      decisionError.value = errorMessage(error, '保存处理结果失败。')
      failedDecision = { command }
    }
  }

  async function decide(
    action: DecisionAction,
    replacement?: string
  ): Promise<void> {
    const issue = selectedIssue.value
    if (!issue) {
      return
    }

    const command = decisionCommand(issue, action, replacement)
    if (!command) {
      decisionError.value =
        issue.document_version === null
          ? '问题版本不可用，请重新加载问题列表。'
          : '自定义替换内容无效。'
      failedDecision = null
      return
    }

    await submitDecision(command)
  }

  async function retryDecision(): Promise<void> {
    const retry = failedDecision
    if (!retry) {
      return
    }
    await submitDecision(retry.command)
  }

  async function loadNextBlocks(): Promise<void> {
    if (documentRequest) {
      await documentRequest
      return
    }
    if (!blockCursor.value) {
      return
    }
    await loadDocumentPage(blockCursor.value, true)
  }

  async function loadNextIssues(): Promise<void> {
    if (issueRequest) {
      await issueRequest
      return
    }
    if (!issueCursor.value) {
      return
    }
    await loadIssuePage(issueCursor.value, true)
  }

  function retrySummary(): Promise<void> {
    return summaryRequest ?? loadSummary()
  }

  async function retryDocument(): Promise<void> {
    if (documentRequest) {
      await documentRequest
      return
    }

    await loadDocumentPage(lastDocumentRequest.cursor, lastDocumentRequest.append)
    if (!errors.document) {
      resumeSelectedIssueLocalization()
    }
  }

  function retryIssues(): Promise<void> {
    return issueRequest ?? loadIssuePage(lastIssueRequest.cursor, lastIssueRequest.append)
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
    localizationGeneration += 1
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
    decisionError,
    decisionAnnouncement,
    selectIssue,
    selectHighlight,
    setFilters,
    decide,
    retryDecision,
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

function normalizeFilters(filters: ReviewIssueFilters): ReviewIssueFilters {
  return Object.fromEntries(
    Object.entries(filters).filter(([, value]) => value !== undefined && value !== '')
  ) as ReviewIssueFilters
}

function isValidCustomReplacement(
  replacement: string | undefined
): replacement is string {
  return (
    replacement !== undefined &&
    replacement.trim().length > 0 &&
    !replacement.includes('\u0000') &&
    Array.from(replacement).length <= 10_000
  )
}
