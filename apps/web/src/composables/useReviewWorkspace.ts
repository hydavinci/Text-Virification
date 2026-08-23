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
import { revisionsApiKey, type RevisionsApi } from '../api/revisions'
import {
  useDocumentVersions,
  type DocumentVersionsState
} from './useDocumentVersions'
import { useDerivedPreview, type DerivedPreviewState } from './useDerivedPreview'
import { useEditDraft, type EditDraftState } from './useEditDraft'
import { useReviewHistory, type ReviewHistoryState } from './useReviewHistory'
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

type ReviewDecisionAction = DecisionAction | 'custom'

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
  scopeGeneration: number
}

interface ReviewFindMatch {
  key: string
  blockId: string
  start: number
  end: number
  matchedIssueId: string | null
  autoFixable: boolean
}

interface SearchBlock {
  block_id: string
  text: string
}

export interface ReviewWorkspaceState {
  summary: Ref<AnalysisSummaryResponse | null>
  versions: DocumentVersionsState['versions']
  activeVersionId: DocumentVersionsState['activeVersionId']
  selectedVersionId: DocumentVersionsState['selectedVersionId']
  selectedVersion: DocumentVersionsState['selectedVersion']
  reanalysis: DocumentVersionsState['reanalysis']
  canEditSelectedVersion: ComputedRef<boolean>
  draft: EditDraftState
  derivedPreview: DerivedPreviewState
  history: ReviewHistoryState
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
  findRegex: Ref<boolean>
  findCaseSensitive: Ref<boolean>
  findStatus: ComputedRef<string>
  canNavigateMatches: ComputedRef<boolean>
  canReplaceCurrentMatch: ComputedRef<boolean>
  canReplaceAllMatches: ComputedRef<boolean>
  findReplaceError: ComputedRef<string | null>
  selectIssue(issueId: string): void
  selectHighlight(issueId: string): void
  setFilters(filters: ReviewIssueFilters): Promise<void>
  selectVersion(versionId: string): Promise<void>
  decide(action: ReviewDecisionAction, replacement?: string, suggestionId?: string | null): Promise<void>
  decideVisible(action: Extract<DecisionAction, 'accepted' | 'ignored'>): Promise<void>
  retryDecision(): Promise<void>
  loadNextBlocks(): Promise<void>
  loadNextIssues(): Promise<void>
  setFindQuery(value: string): void
  setReplaceText(value: string): void
  setFindRegex(value: boolean): void
  setFindCaseSensitive(value: boolean): void
  clearFind(): void
  goToPreviousMatch(): void
  goToNextMatch(): void
  replaceCurrentMatch(): void
  replaceAllMatches(): Promise<void>
  retrySummary(): Promise<void>
  retryDocument(): Promise<void>
  retryIssues(): Promise<void>
}

export function useReviewWorkspace(jobId: string): ReviewWorkspaceState {
  const injectedAnalysisApi = inject(analysisApiKey)
  const injectedRevisionsApi = inject(revisionsApiKey, null)

  if (!injectedAnalysisApi) {
    throw new Error('AnalysisApi is not provided.')
  }

  const analysisApi = injectedAnalysisApi
  const revisionsApi = injectedRevisionsApi ?? createUnavailableRevisionsApi()

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
  const findRegex = ref(false)
  const findCaseSensitive = ref(false)
  const replacementError = ref<string | null>(null)
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
  let decisionScopeGeneration = 0
  let explicitHistoricalVersionId: string | null = null
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
  const documentVersions = useDocumentVersions(jobId, revisionsApi)
  const derivedPreview = useDerivedPreview(jobId, revisionsApi)
  const history = useReviewHistory(jobId, revisionsApi, async () => {
    derivedPreview.clear()
    await Promise.all([loadSummary(), loadIssuePage(null, false)])
  })
  const draft = useEditDraft(jobId, revisionsApi, (version) => {
    documentVersions.trackReanalysis(version, async (versionId) => {
      await selectVersion(versionId)
    })
  })

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
  const searchableBlocks = computed(() =>
    draft.draft.value
      ? draft.localBlocks.value.map((block) => ({
          block_id: block.block_id,
          text: block.text
        }))
      : blocks.value
  )
  const compiledSearch = computed(() => {
    if (!findQuery.value) {
      return { pattern: null, error: null }
    }

    try {
      return {
        pattern: compileSearch(findQuery.value, findRegex.value, findCaseSensitive.value),
        error: null
      }
    } catch {
      return {
        pattern: null,
        error: '正则表达式无效。'
      }
    }
  })
  const findMatches = computed(() =>
    compiledSearch.value.pattern
      ? findDocumentMatches(searchableBlocks.value, issues.value, compiledSearch.value.pattern)
      : []
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

    if (compiledSearch.value.error) {
      return '正则表达式无效'
    }

    const matches = findMatches.value
    if (!matches.length) {
      return '未找到匹配'
    }

    const index = normalizeFindMatchIndex(currentFindMatchIndex.value, matches.length)
    return `第 ${index + 1} / ${matches.length} 处`
  })
  const canNavigateMatches = computed(() => findMatches.value.length > 0)
  const canReplaceCurrentMatch = computed(
    () => draft.draft.value !== null && currentFindMatch.value !== null && !compiledSearch.value.error
  )
  const canReplaceAllMatches = computed(
    () =>
      draft.draft.value !== null &&
      findMatches.value.length > 0 &&
      !compiledSearch.value.error
  )
  const findReplaceError = computed(() => compiledSearch.value.error ?? replacementError.value)
  const canEditSelectedVersion = computed(
    () =>
      documentVersions.selectedVersion.value?.version_id ===
        documentVersions.activeVersionId.value &&
      documentVersions.selectedVersion.value?.status === 'succeeded'
  )

  function isCurrent(generation: number, currentGeneration: number): boolean {
    return active && generation === currentGeneration
  }

  function selectedVersionQuery(): { version_id: string } | undefined {
    return explicitHistoricalVersionId
      ? { version_id: explicitHistoricalVersionId }
      : undefined
  }

  function loadSummary(): Promise<void> {
    const generation = ++summaryGeneration
    loading.summary = true
    errors.summary = null

    const request = (async () => {
      try {
        const versionQuery = selectedVersionQuery()
        const response = versionQuery
          ? await analysisApi.getSummary(jobId, versionQuery)
          : await analysisApi.getSummary(jobId)
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
          ...(selectedVersionQuery() ?? {}),
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
          ...(selectedVersionQuery() ?? {}),
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
    const loadedDecisionGenerations = new Map(
      issueIds.value.map((issueId) => [
        issueId,
        decisionGenerations.get(issueId) ?? 0
      ])
    )
    lastIssueRequest = { cursor: null, append: false }
    loading.issues = true
    errors.issues = null

    const request = (async () => {
      try {
        const response = await analysisApi.getIssues(jobId, {
          ...(selectedVersionQuery() ?? {}),
          ...filters.value,
          cursor: null,
          limit: ISSUE_PAGE_LIMIT
        })
        if (!isCurrent(generation, issueGeneration)) {
          return
        }
        reconcileAuthoritativeIssuePage(
          response,
          decisionGuards,
          loadedDecisionGenerations
        )
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
    decisionGuards: DecisionRequestGuard | DecisionRequestGuard[],
    loadedDecisionGenerations: ReadonlyMap<string, number>
  ): void {
    const requestedGuards = Array.isArray(decisionGuards)
      ? decisionGuards
      : [decisionGuards]
    const currentGuards = currentDecisionGuards(requestedGuards)
    if (!currentGuards.length) {
      return
    }

    const protectedIssueIds = new Set(
      [...loadedDecisionGenerations]
        .filter(
          ([issueId, generation]) =>
            (decisionGenerations.get(issueId) ?? 0) > generation
        )
        .map(([issueId]) => issueId)
    )
    const previousById = issuesById.value
    const previousIds = issueIds.value
    const previousAuthoritativeDecisions = new Map(authoritativeDecisions)
    const nextById: Record<string, Issue> = {}
    const nextIds: string[] = []
    const seen = new Set<string>()

    authoritativeDecisions.clear()

    for (const issue of response.items) {
      if (seen.has(issue.issue_id)) {
        continue
      }

      const protectedIssue = protectedIssueIds.has(issue.issue_id)
        ? previousById[issue.issue_id]
        : undefined
      if (protectedIssue) {
        nextById[issue.issue_id] = protectedIssue
        if (previousAuthoritativeDecisions.has(issue.issue_id)) {
          authoritativeDecisions.set(
            issue.issue_id,
            previousAuthoritativeDecisions.get(issue.issue_id) ?? null
          )
        }
      } else if (!protectedIssueIds.has(issue.issue_id)) {
        nextById[issue.issue_id] = issue
        authoritativeDecisions.set(issue.issue_id, issue.decision)
      }

      if (nextById[issue.issue_id]) {
        nextIds.push(issue.issue_id)
      }
      seen.add(issue.issue_id)
    }

    for (const issueId of previousIds) {
      const protectedIssue = protectedIssueIds.has(issueId)
        ? previousById[issueId]
        : undefined
      if (!protectedIssue || seen.has(issueId)) {
        continue
      }

      nextById[issueId] = protectedIssue
      nextIds.push(issueId)
      if (previousAuthoritativeDecisions.has(issueId)) {
        authoritativeDecisions.set(
          issueId,
          previousAuthoritativeDecisions.get(issueId) ?? null
        )
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

  async function selectVersion(versionId: string): Promise<void> {
    await documentVersions.selectVersion(versionId)
    explicitHistoricalVersionId =
      versionId === documentVersions.activeVersionId.value ? null : versionId
    decisionScopeGeneration += 1
    decisionGenerations.clear()
    derivedPreview.clear()
    localizationGeneration += 1
    explicitlySelectedIssueId = null
    selectedIssueId.value = null
    blocksById.value = {}
    blockIds.value = []
    blockCursor.value = null
    documentCheckerFailures.value = {}
    issuesById.value = {}
    issueIds.value = []
    issueCursor.value = null
    issueCheckerFailures.value = {}
    authoritativeDecisions.clear()
    failedDecisions.value = {}
    lastDocumentRequest = { cursor: null, append: false }
    lastIssueRequest = { cursor: null, append: false }
    await Promise.allSettled([
      loadSummary(),
      loadDocumentPage(null, false),
      loadIssuePage(null, false),
      history.loadHistory(versionId)
    ])
  }

  function nextDecisionGeneration(issueId: string): DecisionRequestGuard {
    const generation = (decisionGenerations.get(issueId) ?? 0) + 1
    decisionGenerations.set(issueId, generation)
    return {
      issueId,
      generation,
      scopeGeneration: decisionScopeGeneration
    }
  }

  function isDecisionCurrent(guard: DecisionRequestGuard): boolean {
    return (
      active &&
      decisionScopeGeneration === guard.scopeGeneration &&
      decisionGenerations.get(guard.issueId) === guard.generation
    )
  }

  function currentDecisionGuards(
    decisionGuards: DecisionRequestGuard | DecisionRequestGuard[]
  ): DecisionRequestGuard[] {
    const guards = Array.isArray(decisionGuards) ? decisionGuards : [decisionGuards]
    return guards.filter((guard) => isDecisionCurrent(guard))
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

  function optimisticDecision(command: DecisionCommand): IssueDecisionSummary | null {
    const fields = {
      issue_version: command.issue_version,
      revision: command.expected_revision + 1,
      updated_at: new Date().toISOString()
    }

    if (command.action === 'accepted') {
      return {
        ...fields,
        action: 'accepted',
        replacement: command.replacement,
        suggestion_id: command.suggestion_id
      }
    }

    if (command.action === 'unreviewed') {
      return null
    }

    return {
      ...fields,
      action: 'ignored',
      replacement: null,
      suggestion_id: null
    }
  }

  function decisionCommand(
    issue: Issue,
    action: ReviewDecisionAction,
    replacement?: string,
    candidateSuggestionId?: string | null,
    options: { requirePreferredSuggestion?: boolean } = {}
  ): DecisionCommand | null {
    if (issue.document_version === null) {
      return null
    }

    const fields = {
      issue_id: issue.issue_id,
      issue_version: issue.document_version,
      expected_revision: issue.decision?.revision ?? 0
    }

    if (action === 'custom') {
      if (!isValidCustomReplacement(replacement)) {
        return null
      }
      return {
        ...fields,
        action: 'accepted',
        replacement,
        suggestion_id: null
      }
    }

    if (action === 'accepted') {
      const preferredSuggestion = findPreferredSuggestion(issue)
      const acceptedReplacement =
        replacement ??
        (issue.decision?.action === 'accepted' && issue.decision.replacement !== null
          ? issue.decision.replacement
          : preferredSuggestion?.text ?? issue.suggestion ?? issue.original)
      const selectedSuggestionIdForCommand =
        candidateSuggestionId ??
        (issue.decision?.action === 'accepted'
          ? issue.decision.suggestion_id ?? null
          : preferredSuggestion?.suggestion_id ?? null)
      if (
        options.requirePreferredSuggestion &&
        !(
          issue.decision?.action === 'accepted' &&
          issue.decision.replacement !== null
        ) &&
        (!preferredSuggestion || !isValidFinalReplacement(acceptedReplacement))
      ) {
        return null
      }
      return {
        ...fields,
        action: 'accepted',
        replacement: acceptedReplacement,
        suggestion_id: selectedSuggestionIdForCommand
      }
    }

    return {
      ...fields,
      action,
      replacement: null,
      suggestion_id: null
    }
  }

  async function submitDecision(command: DecisionCommand): Promise<void> {
    const guard = nextDecisionGeneration(command.issue_id)
    const submittedVersionId = documentVersions.selectedVersionId.value
    decisionAnnouncement.value = ''
    derivedPreview.clear()
    clearFailedDecision(command.issue_id)
    setIssueDecision(command.issue_id, optimisticDecision(command))

    try {
      const response = await analysisApi.putDecisions(jobId, [command])
      if (!isDecisionCurrent(guard)) {
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
        history.recordDecisionBatch(
          response.batch_id,
          submittedVersionId,
          1
        )
        await Promise.all([
          reloadAuthoritativeIssues(guard),
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
        reloadAuthoritativeIssues(guard),
        loadSummary()
      ])
    } catch (error) {
      if (!isDecisionCurrent(guard)) {
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
    action: ReviewDecisionAction,
    replacement?: string,
    suggestionId?: string | null
  ): Promise<void> {
    const issue = selectedIssue.value
    if (!issue) {
      return
    }

    const command = decisionCommand(issue, action, replacement, suggestionId)
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

    const guards = new Map<string, DecisionRequestGuard>()
    const submittedVersionId = documentVersions.selectedVersionId.value
    failureTarget.value = null
    bulkActionPending.value = true
    decisionAnnouncement.value = ''
    derivedPreview.clear()

    for (const command of commands) {
      const guard = nextDecisionGeneration(command.issue_id)
      guards.set(command.issue_id, guard)
      clearFailedDecision(command.issue_id)
      setIssueDecision(command.issue_id, optimisticDecision(command))
    }

    try {
      const response = await analysisApi.putDecisions(jobId, commands)
      let appliedCount = 0
      let needsReviewCount = 0
      const authoritativeReloadGuards: DecisionRequestGuard[] = []

      for (const command of commands) {
        const guard = guards.get(command.issue_id)
        if (!guard || !isDecisionCurrent(guard)) {
          continue
        }

        const outcome = response.outcomes.find(
          (item) => item.issue_id === command.issue_id
        )

        if (!outcome) {
          throw new Error('保存处理结果失败：服务器未返回对应结果。')
        }

        authoritativeReloadGuards.push({
          ...guard
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

      if (authoritativeReloadGuards.length === 0) {
        return
      }

      decisionAnnouncement.value = batchDecisionAnnouncement(appliedCount, needsReviewCount)
      history.recordDecisionBatch(
        response.batch_id,
        submittedVersionId,
        appliedCount
      )
      await Promise.all([
        loadSummary(),
        authoritativeReloadGuards.length > 0
          ? reloadAuthoritativeIssues(authoritativeReloadGuards)
          : Promise.resolve()
      ])
    } catch (error) {
      for (const command of commands) {
        const guard = guards.get(command.issue_id)
        if (!guard || !isDecisionCurrent(guard)) {
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
    action: Extract<DecisionAction, 'accepted' | 'ignored'>
  ): Promise<void> {
    replacementError.value = null
    if (loading.issues) {
      return
    }

    const commands: DecisionCommand[] = []
    for (const issue of visibleBatchIssues.value) {
      const command = decisionCommand(issue, action, undefined, undefined, {
        requirePreferredSuggestion: action === 'accepted'
      })
      if (!command) {
        batchDecisionError.value =
          action === 'accepted'
            ? '当前页包含没有首选建议的问题，无法批量接受。'
            : '批量保存处理结果失败。'
        return
      }
      commands.push(command)
    }

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
    replacementError.value = null
    syncCurrentFindMatchSelection()
  }

  function setReplaceText(value: string): void {
    replaceText.value = value
    replacementError.value = null
  }

  function setFindRegex(value: boolean): void {
    findRegex.value = value
    currentFindMatchIndex.value = findQuery.value ? 0 : -1
    replacementError.value = null
    syncCurrentFindMatchSelection()
  }

  function setFindCaseSensitive(value: boolean): void {
    findCaseSensitive.value = value
    currentFindMatchIndex.value = findQuery.value ? 0 : -1
    replacementError.value = null
    syncCurrentFindMatchSelection()
  }

  function clearFind(): void {
    findQuery.value = ''
    replaceText.value = ''
    currentFindMatchIndex.value = -1
    replacementError.value = null
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

  function replaceCurrentMatch(): void {
    batchDecisionError.value = null
    replacementError.value = null

    const match = currentFindMatch.value
    if (!draft.draft.value || !match) {
      replacementError.value = '请先创建可编辑草稿。'
      return
    }

    replaceDraftMatches([match], replaceText.value)
  }

  function replaceDraftMatches(matches: ReviewFindMatch[], replacement: string): void {
    const matchesByBlock = new Map<string, ReviewFindMatch[]>()
    for (const match of matches) {
      const blockMatches = matchesByBlock.get(match.blockId)
      if (blockMatches) {
        blockMatches.push(match)
      } else {
        matchesByBlock.set(match.blockId, [match])
      }
    }

    for (const [blockId, blockMatches] of matchesByBlock) {
      const block = draft.localBlocks.value.find((candidate) => candidate.block_id === blockId)
      if (!block) {
        continue
      }
      const points = Array.from(block.text)
      for (const match of [...blockMatches].sort((left, right) => right.start - left.start)) {
        points.splice(match.start, match.end - match.start, replacement)
      }
      draft.updateBlock(blockId, points.join(''))
    }

    currentFindMatchIndex.value = normalizeFindMatchIndex(
      currentFindMatchIndex.value,
      findMatches.value.length
    )
  }

  async function replaceAllMatches(): Promise<void> {
    batchDecisionError.value = null
    replacementError.value = null

    if (!draft.draft.value) {
      replacementError.value = '请先创建可编辑草稿。'
      return
    }

    const matches = findMatches.value
    if (!matches.length) {
      replacementError.value = '未找到可替换内容。'
      return
    }

    replaceDraftMatches(matches, replaceText.value)
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
    documentVersions.refreshVersions().then(async () => {
      if (documentVersions.selectedVersionId.value) {
        await history.loadHistory(documentVersions.selectedVersionId.value)
      }
    }),
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
    decisionScopeGeneration += 1
  })

  return {
    summary,
    versions: documentVersions.versions,
    activeVersionId: documentVersions.activeVersionId,
    selectedVersionId: documentVersions.selectedVersionId,
    selectedVersion: documentVersions.selectedVersion,
    reanalysis: documentVersions.reanalysis,
    canEditSelectedVersion,
    draft,
    derivedPreview,
    history,
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
    findRegex,
    findCaseSensitive,
    findStatus,
    canNavigateMatches,
    canReplaceCurrentMatch,
    canReplaceAllMatches,
    findReplaceError,
    selectIssue,
    selectHighlight,
    setFilters,
    selectVersion,
    decide,
    decideVisible,
    retryDecision,
    loadNextBlocks,
    loadNextIssues,
    setFindQuery,
    setReplaceText,
    setFindRegex,
    setFindCaseSensitive,
    clearFind,
    goToPreviousMatch,
    goToNextMatch,
    replaceCurrentMatch,
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

function isValidFinalReplacement(replacement: string | undefined): replacement is string {
  return replacement !== undefined && replacement.length > 0 && !replacement.includes('\u0000')
}

function findPreferredSuggestion(issue: Issue): NonNullable<Issue['suggestions']>[number] | null {
  return issue.suggestions?.find((suggestion) => suggestion.preferred) ?? null
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

export function compileSearch(query: string, regex: boolean, caseSensitive: boolean): RegExp {
  const source = regex ? query : escapeRegExp(query)
  return new RegExp(source, caseSensitive ? 'gu' : 'giu')
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function findDocumentMatches(
  blocks: SearchBlock[],
  issues: Issue[],
  pattern: RegExp
): ReviewFindMatch[] {
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
    const codeUnitToPoint = codeUnitPointMap(block.text)
    pattern.lastIndex = 0
    let result: RegExpExecArray | null
    while ((result = pattern.exec(block.text)) !== null) {
      const matchedText = result[0] ?? ''
      const start = codeUnitToPoint.get(result.index) ?? 0
      const end =
        codeUnitToPoint.get(result.index + matchedText.length) ??
        Array.from(block.text.slice(0, result.index + matchedText.length)).length
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

      if (matchedText.length === 0) {
        const nextCodeUnitIndex =
          result.index + (points[start]?.length ?? 1)
        pattern.lastIndex = Math.max(pattern.lastIndex, nextCodeUnitIndex)
      }
    }
  }

  return matches
}

function codeUnitPointMap(text: string): Map<number, number> {
  const map = new Map<number, number>()
  let codeUnitIndex = 0
  let pointIndex = 0
  map.set(0, 0)
  for (const point of Array.from(text)) {
    codeUnitIndex += point.length
    pointIndex += 1
    map.set(codeUnitIndex, pointIndex)
  }
  return map
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

function createUnavailableRevisionsApi(): RevisionsApi {
  const unavailable = () => Promise.reject(new Error('RevisionsApi is not provided.'))

  return {
    listVersions: () =>
      Promise.resolve({
        job_id: '',
        active_version_id: null,
        versions: []
      }),
    createDraft: unavailable as RevisionsApi['createDraft'],
    getDraft: unavailable as RevisionsApi['getDraft'],
    updateDraft: unavailable as RevisionsApi['updateDraft'],
    deleteDraft: unavailable as RevisionsApi['deleteDraft'],
    reanalyze: unavailable as RevisionsApi['reanalyze'],
    getDerived: unavailable as RevisionsApi['getDerived'],
    subscribeVersionEvents: () => () => undefined,
    listHistory: () =>
      Promise.resolve({
        job_id: '',
        version_id: '',
        total: 0,
        items: [],
        next_cursor: null
      }),
    undoBatch: unavailable as RevisionsApi['undoBatch']
  }
}
