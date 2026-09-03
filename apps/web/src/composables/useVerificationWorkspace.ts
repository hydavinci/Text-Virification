import { computed, ref, shallowRef, toRaw } from 'vue'

import type {
  DocumentRevision,
  IssueState,
  TextBlock,
  VerificationIssue,
  VerificationResult,
  WorkspaceReviewSummary
} from '../types/verification'

interface BatchStateSnapshot {
  documentId: string
  verificationRunId: string
  sourceVersion: string
  entries: Record<string, PriorIssueState>
}

interface Utf16Range {
  start: number
  end: number
}

type PriorIssueState =
  | { hadValue: false }
  | { hadValue: true; value: IssueState }

export interface WorkspaceReadonlyValue<T> {
  readonly __v_isRef: true
  readonly value: T
}

function workspaceReadonlyValue<T>(
  readValue: () => T
): WorkspaceReadonlyValue<T> {
  const facade: WorkspaceReadonlyValue<T> = {
    __v_isRef: true,
    get value(): T {
      return readValue()
    }
  }
  return Object.freeze(facade)
}

function hasOwn<T extends object>(value: T, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(value, key)
}

function isInteger(value: number | null): value is number {
  return value !== null && Number.isInteger(value)
}

function codePointLength(value: string): number {
  return Array.from(value).length
}

function freezeRecursively<T>(value: T): T {
  if (
    value === null ||
    (typeof value !== 'object' && typeof value !== 'function')
  ) {
    return value
  }
  for (const key of Reflect.ownKeys(value)) {
    freezeRecursively(Reflect.get(value, key))
  }
  return Object.freeze(value)
}

function utf16IndexAtCodePointOffset(
  value: string,
  codePointOffset: number
): number | null {
  if (!Number.isInteger(codePointOffset) || codePointOffset < 0) {
    return null
  }

  let currentCodePointOffset = 0
  let currentUtf16Index = 0
  for (const character of value) {
    if (currentCodePointOffset === codePointOffset) {
      return currentUtf16Index
    }
    currentCodePointOffset += 1
    currentUtf16Index += character.length
  }
  return currentCodePointOffset === codePointOffset ? currentUtf16Index : null
}

function utf16RangeForCodePointOffsets(
  value: string,
  start: number,
  end: number
): Utf16Range | null {
  if (
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 0 ||
    end < start
  ) {
    return null
  }

  const utf16Start = utf16IndexAtCodePointOffset(value, start)
  const utf16End = utf16IndexAtCodePointOffset(value, end)
  if (utf16Start === null || utf16End === null) {
    return null
  }
  return {
    start: utf16Start,
    end: utf16End
  }
}

function sliceCodePointRange(
  value: string,
  start: number,
  end: number
): string | null {
  const range = utf16RangeForCodePointOffsets(value, start, end)
  return range === null ? null : value.slice(range.start, range.end)
}

function replaceCodePointRange(
  value: string,
  start: number,
  end: number,
  replacement: string
): string | null {
  const range = utf16RangeForCodePointOffsets(value, start, end)
  if (range === null) {
    return null
  }
  return `${value.slice(0, range.start)}${replacement}${value.slice(range.end)}`
}

function hasCanonicalBlocks(result: VerificationResult): boolean {
  const blocksById = new Map<string, TextBlock>()
  const documentLength = codePointLength(result.text)

  for (const block of result.blocks) {
    if (
      typeof block.block_id !== 'string' ||
      blocksById.has(block.block_id) ||
      (block.parent_id !== null && typeof block.parent_id !== 'string')
    ) {
      return false
    }
    const offsets = [
      block.global_start,
      block.global_end,
      block.block_start,
      block.block_end
    ]
    if (
      offsets.some((offset) => !Number.isInteger(offset) || offset < 0) ||
      block.global_end < block.global_start ||
      block.block_end < block.block_start
    ) {
      return false
    }
    const blockLength = codePointLength(block.text)
    if (
      block.global_end - block.global_start !== blockLength ||
      block.block_end - block.block_start !== blockLength ||
      block.block_start !== 0 ||
      block.block_end !== blockLength ||
      block.global_end > documentLength ||
      sliceCodePointRange(
        result.text,
        block.global_start,
        block.global_end
      ) !== block.text
    ) {
      return false
    }
    blocksById.set(block.block_id, block)
  }

  for (const block of result.blocks) {
    if (block.parent_id === null) {
      continue
    }
    const parent = blocksById.get(block.parent_id)
    if (
      parent === undefined ||
      parent.block_id === block.block_id ||
      parent.global_start > block.global_start ||
      block.global_end > parent.global_end
    ) {
      return false
    }
  }

  const ancestorsById = new Map<string, ReadonlySet<string>>()
  for (const block of result.blocks) {
    const visited = new Set([block.block_id])
    const ancestors = new Set<string>()
    let parentId = block.parent_id
    while (parentId !== null) {
      if (visited.has(parentId)) {
        return false
      }
      const parent = blocksById.get(parentId)
      if (parent === undefined) {
        return false
      }
      visited.add(parentId)
      ancestors.add(parentId)
      parentId = parent.parent_id
    }
    ancestorsById.set(block.block_id, ancestors)
  }

  for (let firstIndex = 0; firstIndex < result.blocks.length; firstIndex += 1) {
    const first = result.blocks[firstIndex]
    for (
      let secondIndex = firstIndex + 1;
      secondIndex < result.blocks.length;
      secondIndex += 1
    ) {
      const second = result.blocks[secondIndex]
      if (
        first.global_start >= second.global_end ||
        second.global_start >= first.global_end
      ) {
        continue
      }
      if (
        ancestorsById.get(first.block_id)?.has(second.block_id) ||
        ancestorsById.get(second.block_id)?.has(first.block_id)
      ) {
        continue
      }
      return false
    }
  }
  return true
}

function isCanonicalIssue(
  issue: VerificationIssue,
  result: VerificationResult,
  blocksById: ReadonlyMap<string, VerificationResult['blocks'][number]>
): boolean {
  if (
    !issue.issue_id ||
    issue.document_id !== result.document_id ||
    issue.verification_run_id !== result.verification_run_id ||
    !Number.isInteger(issue.start) ||
    !Number.isInteger(issue.end) ||
    issue.start < 0 ||
    issue.end <= issue.start ||
    issue.end - issue.start !== codePointLength(issue.original) ||
    sliceCodePointRange(result.text, issue.start, issue.end) !== issue.original
  ) {
    return false
  }

  if (issue.block_id === null) {
    return issue.block_start === null && issue.block_end === null
  }

  const block = blocksById.get(issue.block_id)
  if (
    block === undefined ||
    !isInteger(issue.block_start) ||
    !isInteger(issue.block_end) ||
    issue.block_end <= issue.block_start ||
    issue.block_end - issue.block_start !== issue.end - issue.start ||
    issue.start < block.global_start ||
    issue.end > block.global_end
  ) {
    return false
  }

  const expectedBlockStart = block.block_start + issue.start - block.global_start
  const expectedBlockEnd = block.block_start + issue.end - block.global_start
  const localStart = issue.block_start - block.block_start
  const localEnd = issue.block_end - block.block_start
  return (
    issue.block_start === expectedBlockStart &&
    issue.block_end === expectedBlockEnd &&
    sliceCodePointRange(block.text, localStart, localEnd) === issue.original
  )
}

function canonicalIssues(
  result: VerificationResult
): readonly VerificationIssue[] {
  if (!hasCanonicalBlocks(result)) {
    return Object.freeze([])
  }
  const blocksById = new Map(result.blocks.map((block) => [block.block_id, block]))
  const candidates = result.issues
    .filter((issue) => isCanonicalIssue(issue, result, blocksById))
    .sort((left, right) =>
      left.start - right.start ||
      left.end - right.end ||
      left.issue_id.localeCompare(right.issue_id) ||
      JSON.stringify(left).localeCompare(JSON.stringify(right))
    )
  const accepted: VerificationIssue[] = []
  const seenIds = new Set<string>()

  for (const issue of candidates) {
    if (seenIds.has(issue.issue_id)) {
      continue
    }
    accepted.push(issue)
    seenIds.add(issue.issue_id)
  }
  return Object.freeze(accepted)
}

function sourceRevision(result: VerificationResult): Readonly<DocumentRevision> {
  return Object.freeze({
    revision_id: null,
    document_id: result.document_id,
    verification_run_id: result.verification_run_id,
    source_version: result.source_version,
    revision_number: null,
    created_at: null,
    parent_revision_id: null,
    persistence_state: 'source',
    kind: 'source',
    text: result.text
  })
}

export function useVerificationWorkspace() {
  const result = shallowRef<VerificationResult | null>(null)
  const issueStates = ref<Record<string, IssueState>>({})
  const selectedSuggestions = ref<Record<string, string | null>>({})
  const safeIssues = shallowRef<readonly VerificationIssue[]>(Object.freeze([]))
  const currentRevision = shallowRef<Readonly<DocumentRevision> | null>(null)
  const requiresReverification = ref(false)
  const batchHistory: BatchStateSnapshot[] = []

  const visibleIssues = computed<readonly VerificationIssue[]>(() =>
    requiresReverification.value ? Object.freeze([]) : safeIssues.value
  )

  function issueIds(): Set<string> {
    return new Set(safeIssues.value.map((issue) => issue.issue_id))
  }

  function applyAcceptedReplacements(): string {
    const currentResult = result.value
    if (currentResult === null) {
      return ''
    }

    let text = currentResult.text
    const acceptedIssues = safeIssues.value
      .filter((issue) => issueStates.value[issue.issue_id] === 'accepted')
      .filter((issue) => effectiveSuggestion(issue) !== null)
      .sort((left, right) =>
        right.start - left.start ||
        right.end - left.end ||
        right.issue_id.localeCompare(left.issue_id)
      )

    for (const issue of acceptedIssues) {
      const suggestion = effectiveSuggestion(issue)
      if (suggestion === null) {
        continue
      }
      const replaced = replaceCodePointRange(
        text,
        issue.start,
        issue.end,
        suggestion
      )
      if (replaced !== null) {
        text = replaced
      }
    }
    return text
  }

  function effectiveSuggestion(issue: VerificationIssue): string | null {
    return hasOwn(selectedSuggestions.value, issue.issue_id)
      ? selectedSuggestions.value[issue.issue_id]
      : issue.suggestion
  }

  const replacementConflictIssueIds = computed(() => {
    const acceptedIssues = safeIssues.value
      .filter((issue) => issueStates.value[issue.issue_id] === 'accepted')
      .filter((issue) => effectiveSuggestion(issue) !== null)
    const conflictingIds = new Set<string>()

    for (let leftIndex = 0; leftIndex < acceptedIssues.length; leftIndex += 1) {
      const left = acceptedIssues[leftIndex]
      for (
        let rightIndex = leftIndex + 1;
        rightIndex < acceptedIssues.length;
        rightIndex += 1
      ) {
        const right = acceptedIssues[rightIndex]
        if (left.start < right.end && right.start < left.end) {
          conflictingIds.add(left.issue_id)
          conflictingIds.add(right.issue_id)
        }
      }
    }

    return Object.freeze(
      acceptedIssues
        .filter((issue) => conflictingIds.has(issue.issue_id))
        .map((issue) => issue.issue_id)
    )
  })

  const hasReplacementConflicts = computed(
    () => replacementConflictIssueIds.value.length > 0
  )

  const modifiedText = computed(() => {
    if (
      (requiresReverification.value || hasReplacementConflicts.value) &&
      currentRevision.value !== null
    ) {
      return currentRevision.value.text
    }
    return applyAcceptedReplacements()
  })

  const summary = computed<WorkspaceReviewSummary>(() => {
    const counts: WorkspaceReviewSummary = {
      total: visibleIssues.value.length,
      pending: 0,
      accepted: 0,
      rejected: 0
    }
    for (const issue of visibleIssues.value) {
      const state = issueStates.value[issue.issue_id] ?? 'pending'
      counts[state] += 1
    }
    return Object.freeze(counts)
  })

  function createReviewRevision(): void {
    const currentResult = result.value
    if (
      currentResult === null ||
      requiresReverification.value ||
      hasReplacementConflicts.value
    ) {
      return
    }
    const text = applyAcceptedReplacements()
    const priorRevision = currentRevision.value
    if (
      priorRevision !== null &&
      priorRevision.document_id === currentResult.document_id &&
      priorRevision.verification_run_id === currentResult.verification_run_id &&
      priorRevision.source_version === currentResult.source_version &&
      priorRevision.kind !== 'manual' &&
      priorRevision.text === text
    ) {
      return
    }
    if (
      text === currentResult.text &&
      (priorRevision === null || priorRevision.persistence_state === 'source')
    ) {
      currentRevision.value = sourceRevision(currentResult)
      return
    }
    currentRevision.value = Object.freeze({
      revision_id: globalThis.crypto.randomUUID(),
      document_id: currentResult.document_id,
      verification_run_id: currentResult.verification_run_id,
      source_version: currentResult.source_version,
      revision_number: null,
      created_at: new Date().toISOString(),
      parent_revision_id: priorRevision?.revision_id ?? null,
      persistence_state: 'draft',
      kind: 'review',
      text
    })
  }

  function loadResult(nextResult: VerificationResult): void {
    const canonicalResult = freezeRecursively(structuredClone(toRaw(nextResult)))
    const priorResult = result.value
    const sameSourceRevision =
      !requiresReverification.value &&
      priorResult !== null &&
      priorResult.document_id === canonicalResult.document_id &&
      priorResult.source_version === canonicalResult.source_version &&
      priorResult.verification_run_id === canonicalResult.verification_run_id
    const nextIssues = canonicalIssues(canonicalResult)
    const nextIds = new Set(nextIssues.map((issue) => issue.issue_id))
    const nextStates: Record<string, IssueState> = {}
    const nextSuggestions: Record<string, string | null> = {}

    if (sameSourceRevision) {
      for (const issueId of nextIds) {
        if (hasOwn(issueStates.value, issueId)) {
          nextStates[issueId] = issueStates.value[issueId]
        }
        if (hasOwn(selectedSuggestions.value, issueId)) {
          nextSuggestions[issueId] = selectedSuggestions.value[issueId]
        }
      }
    }

    result.value = canonicalResult
    safeIssues.value = nextIssues
    issueStates.value = nextStates
    selectedSuggestions.value = nextSuggestions
    requiresReverification.value = false
    batchHistory.length = 0
    if (!sameSourceRevision) {
      currentRevision.value = sourceRevision(canonicalResult)
      return
    }
    createReviewRevision()
  }

  function clearResult(): void {
    result.value = null
    safeIssues.value = Object.freeze([])
    issueStates.value = {}
    selectedSuggestions.value = {}
    currentRevision.value = null
    requiresReverification.value = false
    batchHistory.length = 0
  }

  function setIssueState(issueId: string, state: IssueState): void {
    if (requiresReverification.value || !issueIds().has(issueId)) {
      return
    }
    issueStates.value = {
      ...issueStates.value,
      [issueId]: state
    }
    createReviewRevision()
  }

  function acceptIssue(issueId: string): void {
    setIssueState(issueId, 'accepted')
  }

  function rejectIssue(issueId: string): void {
    setIssueState(issueId, 'rejected')
  }

  function undoIssue(issueId: string): void {
    if (requiresReverification.value || !issueIds().has(issueId)) {
      return
    }
    const nextStates = { ...issueStates.value }
    delete nextStates[issueId]
    issueStates.value = nextStates
    createReviewRevision()
  }

  function setIssueStates(issueIdsToUpdate: string[], state: IssueState): void {
    const currentResult = result.value
    if (currentResult === null || requiresReverification.value) {
      return
    }
    const validIds = issueIds()
    const requestedIds = [...new Set(issueIdsToUpdate)].filter((issueId) =>
      validIds.has(issueId)
    )
    if (requestedIds.length === 0) {
      return
    }

    const entries: Record<string, PriorIssueState> = {}
    const nextStates = { ...issueStates.value }
    for (const issueId of requestedIds) {
      entries[issueId] = hasOwn(issueStates.value, issueId)
        ? { hadValue: true, value: issueStates.value[issueId] }
        : { hadValue: false }
      nextStates[issueId] = state
    }
    batchHistory.push({
      documentId: currentResult.document_id,
      verificationRunId: currentResult.verification_run_id,
      sourceVersion: currentResult.source_version,
      entries
    })
    issueStates.value = nextStates
    createReviewRevision()
  }

  function acceptIssues(issueIdsToAccept: string[]): void {
    setIssueStates(issueIdsToAccept, 'accepted')
  }

  function rejectIssues(issueIdsToReject: string[]): void {
    setIssueStates(issueIdsToReject, 'rejected')
  }

  function undoLastBatch(): void {
    const currentResult = result.value
    const snapshot = batchHistory.pop()
    if (
      currentResult === null ||
      snapshot === undefined ||
      snapshot.documentId !== currentResult.document_id ||
      snapshot.verificationRunId !== currentResult.verification_run_id ||
      snapshot.sourceVersion !== currentResult.source_version
    ) {
      return
    }

    const nextStates = { ...issueStates.value }
    for (const [issueId, priorState] of Object.entries(snapshot.entries)) {
      if (priorState.hadValue) {
        nextStates[issueId] = priorState.value
      } else {
        delete nextStates[issueId]
      }
    }
    issueStates.value = nextStates
    createReviewRevision()
  }

  function selectSuggestion(issueId: string, suggestion: string | null): void {
    if (requiresReverification.value || !issueIds().has(issueId)) {
      return
    }
    selectedSuggestions.value = {
      ...selectedSuggestions.value,
      [issueId]: suggestion
    }
    createReviewRevision()
  }

  function saveManualEdit(text: string): Readonly<DocumentRevision> | null {
    const currentResult = result.value
    if (currentResult === null) {
      return null
    }
    const priorRevision = currentRevision.value ?? sourceRevision(currentResult)
    const revision = Object.freeze({
      revision_id: globalThis.crypto.randomUUID(),
      document_id: currentResult.document_id,
      verification_run_id: currentResult.verification_run_id,
      source_version: currentResult.source_version,
      revision_number: null,
      created_at: new Date().toISOString(),
      parent_revision_id: priorRevision.revision_id,
      persistence_state: 'draft' as const,
      kind: 'manual' as const,
      text
    })
    currentRevision.value = revision
    requiresReverification.value = true
    issueStates.value = {}
    selectedSuggestions.value = {}
    batchHistory.length = 0
    return revision
  }

  const issueStateSnapshots = computed(() =>
    Object.freeze({ ...issueStates.value })
  )
  const selectedSuggestionSnapshots = computed(() =>
    Object.freeze({ ...selectedSuggestions.value })
  )

  return {
    result: workspaceReadonlyValue(() => result.value),
    issueStates: workspaceReadonlyValue(() => issueStateSnapshots.value),
    selectedSuggestions: workspaceReadonlyValue(
      () => selectedSuggestionSnapshots.value
    ),
    currentRevision: workspaceReadonlyValue(() => currentRevision.value),
    requiresReverification: workspaceReadonlyValue(
      () => requiresReverification.value
    ),
    modifiedText: workspaceReadonlyValue(() => modifiedText.value),
    visibleIssues: workspaceReadonlyValue(() => visibleIssues.value),
    summary: workspaceReadonlyValue(() => summary.value),
    replacementConflictIssueIds: workspaceReadonlyValue(
      () => replacementConflictIssueIds.value
    ),
    hasReplacementConflicts: workspaceReadonlyValue(
      () => hasReplacementConflicts.value
    ),
    loadResult,
    clearResult,
    setIssueState,
    acceptIssue,
    rejectIssue,
    undoIssue,
    acceptIssues,
    rejectIssues,
    undoLastBatch,
    selectSuggestion,
    saveManualEdit
  }
}
