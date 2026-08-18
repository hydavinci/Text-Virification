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
const MAX_VISIBLE_BATCH_DECISIONS = 500

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
  message: string
  command?: DecisionCommand
}

interface DecisionRequestGuard {
  issueId: string
  generation: number
}

interface ReviewFindMatch {
  key: string
  blockId: string
  start: number
  end: number
  matchedIssueId: string | null
  autoFixable: boolean
}

export interface ReviewWorkspaceState {
  summary: Ref<AnalysisSummaryResponse | null>
  filters: Ref<ReviewIssueFilters>
  blocks: ComputedRef<DocumentBlock[]>
  issues: ComputedRef<Issue[]>
  issueStatusById: ComputedRef<Record<string, string>>
  selectedIssueId: Ref<string | null>
  selectedIssue: ComputedRef<Issue | null>
  selectedBlockId: ComputedRef<string | null>
  blockCursor: Ref<string | null>
  issueCursor: Ref<string | null>
  loading: LoadingState
  errors: ErrorState
  checkerFailures: ComputedRef<CheckerFailureMap>
  decisionError: ComputedRef<string | null>
  canRetryDecision: ComputedRef<boolean>
  decisionAnnouncement: Ref<string>
  batchLimit: number
  visibleIssueCount: ComputedRef<number>
  highRiskVisibleIssueCount: ComputedRef<number>
  batchDecisionError: Ref<string | null>
  bulkActionPending: Ref<boolean>
  findQuery: Ref<string>
  replaceText: Ref<string>
  findStatus: ComputedRef<string>
  canNavigateMatches: ComputedRef<boolean>
  canReplaceAllMatches: ComputedRef<boolean>
  findReplaceError: Ref<string | null>
  selectIssue(issueId: string): void
  selectHighlight(issueId: string): void
  setFilters(filters: ReviewIssueFilters): Promise<void>
  decide(action: DecisionAction, replacement?: string): Promise<void>
  decideVisible(action: Exclude<DecisionAction, 'custom'>): Promise<void>
  retryDecision(): Promise<void>
  loadNextBlocks(): Promise<void>
  loadNextIssues(): Promise<void>
  setFindQuery(value: string): void
  setReplaceText(value: string): void
  goToPreviousMatch(): void
  goToNextMatch(): void
  replaceAllMatches(): Promise<void>
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
  const decisionAnnouncement = ref('')
  const batchDecisionError = ref<string | null>(null)
  const bulkActionPending = ref(false)
  const findQuery = ref('')
  const replaceText = ref('')
  const findReplaceError = ref<string | null>(null)
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
  let explicitlySelectedIssueId: string | null = null
  let lastDocumentRequest: PageRequest = { cursor: null, append: false }
  let lastIssueRequest: PageRequest = { cursor: null, append: false }
  const authoritativeDecisions = new Map<string, IssueDecisionSummary | null>()
  const decisionGenerations = new Map<string, number>()
  const failedDecisions = ref<Record<string, FailedDecision | undefined>>({})
  const currentFindMatchIndex = ref(-1)

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
  const findMatches = computed(() =>
    findDocumentMatches(blocks.value, issues.value, findQuery.value)
  )
  const currentFindMatch = computed(() => {
    const matches = findMatches.value
    const index = normalizeFindMatchIndex(currentFindMatchIndex.value, matches.length)
    return index === -1 ? null : matches[index] ?? null
  })
  const selectedBlockId = computed(
    () => currentFindMatch.value?.blockId ?? selectedIssue.value?.block_id ?? null
  )
  const checkerFailures = computed<CheckerFailureMap>(() => ({
    ...summary.value?.checker_failures,
    ...documentCheckerFailures.value,
    ...issueCheckerFailures.value
  }))
  const selectedFailedDecision = computed(() => {
    const issueId = selectedIssueId.value
    return issueId ? failedDecisions.value[issueId] ?? null : null
  })
  const decisionError = computed(() => selectedFailedDecision.value?.message ?? null)
  const canRetryDecision = computed(
    () => selectedFailedDecision.value?.command !== undefined
  )
  const issueStatusById = computed(() =>
    Object.fromEntries(
      issues.value.map((issue) => [
        issue.issue_id,
        decisionStatusLabel(issue.decision)
      ])
    )
  )
  const visibleIssueCount = computed(() => issues.value.length)
  const visibleBatchIssues = computed(() =>
    issues.value.slice(0, MAX_VISIBLE_BATCH_DECISIONS)
  )
  const highRiskVisibleIssueCount = computed(
    () => visibleBatchIssues.value.filter(isHighRiskSecurityIssue).length
  )
  const findStatus = computed(() => {
    if (!findQuery.value) {
      return '仅在已加载内容中查找'
    }

    const matches = findMatches.value
    if (!matches.length) {
      return '未找到匹配'
    }

    const index = normalizeFindMatchIndex(currentFindMatchIndex.value, matches.length)
    return `第 ${index + 1} / ${matches.length} 处`
  })
  const canNavigateMatches = computed(() => findMatches.value.length > 0)
  const canReplaceAllMatches = computed(() => {
    if (!isValidCustomReplacement(replaceText.value)) {
      return false
    }

    const matches = findMatches.value
    if (!matches.length || matches.length > MAX_VISIBLE_BATCH_DECISIONS) {
      return false
    }

    return matches.every((match) => match.matchedIssueId !== null && match.autoFixable)
  })

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

  function loadIssuePage(cursor: string | null, append: boolean): Promise<void> {
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
    })()

    issueRequest = request
    void request.finally(() => {
      if (issueRequest === request) {
        issueRequest = null
      }
    })
    return request
  }

  function reloadAuthoritativeIssues(
    decisionGuards: DecisionRequestGuard | DecisionRequestGuard[]
  ): Promise<void> {
    const generation = ++issueGeneration
    lastIssueRequest = { cursor: null, append: false }
    loading.issues = true
    errors.issues = null

    const request = (async () => {
      try {
        const response = await analysisApi.getIssues(jobId, {
          ...filters.value,
          cursor: null,
          limit: ISSUE_PAGE_LIMIT
        })
        if (!isCurrent(generation, issueGeneration)) {
          return
        }
        reconcileAuthoritativeIssuePage(response, decisionGuards)
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

  function reconcileAuthoritativeIssuePage(
    response: IssuePageResponse,
    decisionGuards: DecisionRequestGuard | DecisionRequestGuard[]
  ): void {
    const guards = currentDecisionGuards(decisionGuards)
    if (!guards.length) {
      return
    }

    const nextById = { ...issuesById.value }
    const nextIds = [...issueIds.value]
    const authoritativeIssues = new Map(
      response.items.map((issue) => [issue.issue_id, issue] as const)
    )

    for (const guard of guards) {
      const authoritativeIssue = authoritativeIssues.get(guard.issueId)

      if (authoritativeIssue) {
        nextById[guard.issueId] = authoritativeIssue
        authoritativeDecisions.set(guard.issueId, authoritativeIssue.decision)
        continue
      }

      delete nextById[guard.issueId]
      authoritativeDecisions.delete(guard.issueId)
    }

    issuesById.value = nextById
    issueIds.value = nextIds.filter((issueId) =>
      Object.prototype.hasOwnProperty.call(nextById, issueId)
    )
    issueCursor.value = response.next_cursor
    issueCheckerFailures.value = response.checker_failures

    if (
      !selectedIssueId.value ||
      !Object.prototype.hasOwnProperty.call(nextById, selectedIssueId.value)
    ) {
      selectedIssueId.value = issueIds.value[0] ?? null
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
    issuesById.value = {}
    issueIds.value = []
    issueCursor.value = null
    issueCheckerFailures.value = {}
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

  function currentDecisionGuards(
    decisionGuards: DecisionRequestGuard | DecisionRequestGuard[]
  ): DecisionRequestGuard[] {
    const guards = Array.isArray(decisionGuards) ? decisionGuards : [decisionGuards]
    return guards.filter((guard) => isDecisionCurrent(guard.issueId, guard.generation))
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

  function setFailedDecision(issueId: string, failure: FailedDecision): void {
    failedDecisions.value = {
      ...failedDecisions.value,
      [issueId]: failure
    }
  }

  function clearFailedDecision(issueId: string): void {
    if (!Object.prototype.hasOwnProperty.call(failedDecisions.value, issueId)) {
      return
    }

    const nextFailedDecisions = { ...failedDecisions.value }
    delete nextFailedDecisions[issueId]
    failedDecisions.value = nextFailedDecisions
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
    decisionAnnouncement.value = ''
    clearFailedDecision(command.issue_id)
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
        await Promise.all([
          reloadAuthoritativeIssues({
            issueId: command.issue_id,
            generation
          }),
          loadSummary()
        ])
        return
      }

      setIssueDecision(
        command.issue_id,
        authoritativeDecisions.get(command.issue_id) ?? null
      )
      decisionAnnouncement.value = '结果已更新，请重新确认'
      await Promise.all([
        reloadAuthoritativeIssues({
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
      setFailedDecision(command.issue_id, {
        message: errorMessage(error, '保存处理结果失败。'),
        command
      })
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
      setFailedDecision(issue.issue_id, {
        message:
          issue.document_version === null
            ? '问题版本不可用，请重新加载问题列表。'
            : '自定义替换内容无效。'
      })
      return
    }

    await submitDecision(command)
  }

  async function submitDecisionBatch(
    commands: DecisionCommand[],
    failureTarget: Ref<string | null>,
    failureMessage: string
  ): Promise<void> {
    if (!commands.length) {
      return
    }

    const generations = new Map<string, number>()
    failureTarget.value = null
    bulkActionPending.value = true
    decisionAnnouncement.value = ''

    for (const command of commands) {
      const generation = nextDecisionGeneration(command.issue_id)
      generations.set(command.issue_id, generation)
      clearFailedDecision(command.issue_id)
      setIssueDecision(command.issue_id, optimisticDecision(command))
    }

    try {
      const response = await analysisApi.putDecisions(jobId, commands)
      let appliedCount = 0
      let needsReviewCount = 0
      const authoritativeReloadGuards: DecisionRequestGuard[] = []

      for (const command of commands) {
        const generation = generations.get(command.issue_id)
        if (generation === undefined || !isDecisionCurrent(command.issue_id, generation)) {
          continue
        }

        const outcome = response.outcomes.find(
          (item) => item.issue_id === command.issue_id
        )

        if (!outcome) {
          throw new Error('保存处理结果失败：服务器未返回对应结果。')
        }

        authoritativeReloadGuards.push({
          issueId: command.issue_id,
          generation
        })

        if (outcome.status === 'applied') {
          authoritativeDecisions.set(command.issue_id, outcome.decision)
          setIssueDecision(command.issue_id, outcome.decision)
          appliedCount += 1
          continue
        }

        setIssueDecision(
          command.issue_id,
          authoritativeDecisions.get(command.issue_id) ?? null
        )
        needsReviewCount += 1
      }

      decisionAnnouncement.value = batchDecisionAnnouncement(appliedCount, needsReviewCount)
      await Promise.all([
        loadSummary(),
        authoritativeReloadGuards.length > 0
          ? reloadAuthoritativeIssues(authoritativeReloadGuards)
          : Promise.resolve()
      ])
    } catch (error) {
      for (const command of commands) {
        const generation = generations.get(command.issue_id)
        if (generation === undefined || !isDecisionCurrent(command.issue_id, generation)) {
          continue
        }

        setIssueDecision(
          command.issue_id,
          authoritativeDecisions.get(command.issue_id) ?? null
        )
      }

      failureTarget.value = errorMessage(error, failureMessage)
    } finally {
      bulkActionPending.value = false
    }
  }

  async function decideVisible(
    action: Exclude<DecisionAction, 'custom'>
  ): Promise<void> {
    findReplaceError.value = null
    if (loading.issues) {
      return
    }

    const commands = visibleBatchIssues.value.flatMap((issue) => {
      const command = decisionCommand(issue, action)
      return command ? [command] : []
    })

    await submitDecisionBatch(commands, batchDecisionError, '批量保存处理结果失败。')
  }

  async function retryDecision(): Promise<void> {
    const issueId = selectedIssueId.value
    const retry = issueId ? failedDecisions.value[issueId] : null
    if (!retry?.command) {
      return
    }
    await submitDecision(retry.command)
  }

  function setFindQuery(value: string): void {
    findQuery.value = value
    currentFindMatchIndex.value = value ? 0 : -1
    findReplaceError.value = null
    syncCurrentFindMatchSelection()
  }

  function setReplaceText(value: string): void {
    replaceText.value = value
    findReplaceError.value = null
  }

  function syncCurrentFindMatchSelection(): void {
    const match = currentFindMatch.value

    if (!findQuery.value || !match) {
      return
    }

    if (match.matchedIssueId && issuesById.value[match.matchedIssueId]) {
      selectHighlight(match.matchedIssueId)
      return
    }

    localizationGeneration += 1
    explicitlySelectedIssueId = null
    selectedIssueId.value = null
  }

  function goToPreviousMatch(): void {
    const matches = findMatches.value
    if (!matches.length) {
      return
    }

    const currentIndex = normalizeFindMatchIndex(currentFindMatchIndex.value, matches.length)
    currentFindMatchIndex.value = (currentIndex - 1 + matches.length) % matches.length
    syncCurrentFindMatchSelection()
  }

  function goToNextMatch(): void {
    const matches = findMatches.value
    if (!matches.length) {
      return
    }

    const currentIndex = normalizeFindMatchIndex(currentFindMatchIndex.value, matches.length)
    currentFindMatchIndex.value = (currentIndex + 1) % matches.length
    syncCurrentFindMatchSelection()
  }

  async function replaceAllMatches(): Promise<void> {
    batchDecisionError.value = null

    if (!canReplaceAllMatches.value) {
      findReplaceError.value = '仅支持替换与单个可自动修复问题完全对应的匹配项。'
      return
    }

    const replacement = replaceText.value
    const commands = findMatches.value.flatMap((match) => {
      const issue = match.matchedIssueId ? issuesById.value[match.matchedIssueId] : null
      const command = issue ? decisionCommand(issue, 'custom', replacement) : null
      return command ? [command] : []
    })

    if (commands.length !== findMatches.value.length) {
      findReplaceError.value = '仅支持替换与单个可自动修复问题完全对应的匹配项。'
      return
    }

    await submitDecisionBatch(commands, findReplaceError, '批量替换失败。')
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
    issueStatusById,
    selectedIssueId,
    selectedIssue,
    selectedBlockId,
    blockCursor,
    issueCursor,
    loading,
    errors,
    checkerFailures,
    decisionError,
    canRetryDecision,
    decisionAnnouncement,
    batchLimit: MAX_VISIBLE_BATCH_DECISIONS,
    visibleIssueCount,
    highRiskVisibleIssueCount,
    batchDecisionError,
    bulkActionPending,
    findQuery,
    replaceText,
    findStatus,
    canNavigateMatches,
    canReplaceAllMatches,
    findReplaceError,
    selectIssue,
    selectHighlight,
    setFilters,
    decide,
    decideVisible,
    retryDecision,
    loadNextBlocks,
    loadNextIssues,
    setFindQuery,
    setReplaceText,
    goToPreviousMatch,
    goToNextMatch,
    replaceAllMatches,
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

function normalizeFindMatchIndex(index: number, length: number): number {
  if (length < 1) {
    return -1
  }

  if (index < 0) {
    return 0
  }

  if (index >= length) {
    return length - 1
  }

  return index
}

function findDocumentMatches(
  blocks: DocumentBlock[],
  issues: Issue[],
  query: string
): ReviewFindMatch[] {
  const queryPoints = Array.from(query)
  if (!queryPoints.length) {
    return []
  }

  const exactIssueByRange = new Map<string, Issue[]>()
  for (const issue of issues) {
    const key = `${issue.block_id}:${issue.start}:${issue.end}`
    const matches = exactIssueByRange.get(key)
    if (matches) {
      matches.push(issue)
    } else {
      exactIssueByRange.set(key, [issue])
    }
  }

  const matches: ReviewFindMatch[] = []

  for (const block of blocks) {
    const points = Array.from(block.text)
    const maxStart = points.length - queryPoints.length

    for (let start = 0; start <= maxStart; start += 1) {
      const end = start + queryPoints.length
      const slice = points.slice(start, end)
      if (slice.length !== queryPoints.length || slice.join('') !== query) {
        continue
      }

      const exactIssues = exactIssueByRange.get(`${block.block_id}:${start}:${end}`) ?? []
      const exactIssue = exactIssues.length === 1 ? exactIssues[0] : null

      matches.push({
        key: `${block.block_id}:${start}:${end}`,
        blockId: block.block_id,
        start,
        end,
        matchedIssueId: exactIssue?.issue_id ?? null,
        autoFixable: exactIssue?.auto_fixable ?? false
      })
    }
  }

  return matches
}

function isHighRiskSecurityIssue(issue: Issue): boolean {
  return issue.layer === 'security' && issue.severity === 'error'
}

function decisionStatusLabel(decision: IssueDecisionSummary | null): string {
  switch (decision?.action) {
    case 'accepted':
      return '已接受'
    case 'ignored':
      return '已忽略'
    case 'custom':
      return '已自定义'
    default:
      return '未处理'
  }
}

function batchDecisionAnnouncement(appliedCount: number, needsReviewCount: number): string {
  if (appliedCount > 0 && needsReviewCount > 0) {
    return `成功 ${appliedCount} 项，需重新确认 ${needsReviewCount} 项`
  }

  if (appliedCount > 0) {
    return `成功 ${appliedCount} 项`
  }

  if (needsReviewCount > 0) {
    return `需重新确认 ${needsReviewCount} 项`
  }

  return ''
}
