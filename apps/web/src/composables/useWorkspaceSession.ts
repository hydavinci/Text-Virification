import { computed, ref } from 'vue'

import { createAnalyzeOptionsSnapshot, createDefaultAnalyzeOptions } from '../api/analyzeOptions'
import type {
  AnalyzeOptions,
  FileType,
  IssueSeverity,
  VerificationResult
} from '../types/verification'
import type { IssueLayerFilter } from './useIssueNavigation'
import {
  type PreparedWorkspaceRestore,
  type useVerificationWorkspace
} from './useVerificationWorkspace'
import { MAX_VERIFICATION_ISSUES } from '../validation/verificationLimits'

export const WORKSPACE_SESSION_VERSION = 7
export const WORKSPACE_SESSION_KEY = 'text-verification-session'
export const WORKSPACE_SESSION_UI_KEY = `${WORKSPACE_SESSION_KEY}-ui`
export const MAX_WORKSPACE_SESSION_RAW_BYTES = 32 * 1024 * 1024
export const MAX_WORKSPACE_RESULT_BLOCKS = 20_000
export const MAX_WORKSPACE_RESULT_ISSUES = MAX_VERIFICATION_ISSUES
export const MAX_WORKSPACE_REVISION_CHAIN = 10_000
export const MAX_WORKSPACE_REVISION_CODE_POINTS = 5_000_000
const MAX_WORKSPACE_ISSUE_ALTERNATIVES = 100
const MAX_WORKSPACE_ISSUE_TEXT_CODE_POINTS = 10_000
const MAX_WORKSPACE_TERMINOLOGY_ITEMS = 500
const MAX_WORKSPACE_TERMINOLOGY_CODE_POINTS = 200
const MAX_RECHECK_GRANT_CODE_POINTS = 8 * 1024

export type WorkspaceViewMode = 'sentence' | 'continuous'
export type WorkspaceSettingsTab = 'settings' | 'terms' | 'banned'
export type WorkspaceResultTab = 'issues' | 'summary'
export type WorkspaceSeverityFilter = 'all' | IssueSeverity

export interface WorkspaceExportAuthoritySource {
  jobId: string
  documentId: string
  verificationRunId: string
  sourceVersion: string
  fileType: FileType
  requiresOcrReconstruction: boolean
  latestRevisionId: string | null
  latestRevisionNumber: number
  persistedText: string | null
}

export interface WorkspaceExportAuthority
  extends WorkspaceExportAuthoritySource {
  recheckGrant: string
}

export interface WorkspaceSessionUiState {
  options: AnalyzeOptions
  filters: {
    layer: IssueLayerFilter
    severity: WorkspaceSeverityFilter
  }
  viewMode: WorkspaceViewMode
  ui: {
    settingsTab: WorkspaceSettingsTab
    resultTab: WorkspaceResultTab
    showFindReplace: boolean
    trackChanges: boolean
    selectedIssueId: string | null
  }
  jobId: string | null
  exportAuthority: WorkspaceExportAuthority | null
}

type VerificationWorkspace = ReturnType<typeof useVerificationWorkspace>

interface PreparedSession {
  workspace: PreparedWorkspaceRestore
  state: WorkspaceSessionUiState
}

const SESSION_KEYS = [
  'version',
  'workspace',
  'options',
  'filters',
  'viewMode',
  'ui',
  'jobId',
  'exportAuthority'
] as const
const VERSION_3_SESSION_KEYS = [
  'version',
  'workspace',
  'options',
  'filters',
  'viewMode',
  'ui',
  'jobId'
] as const
const VERSION_4_SESSION_KEYS = SESSION_KEYS
const VERSION_5_SESSION_KEYS = SESSION_KEYS
const WORKSPACE_KEYS = [
  'result',
  'currentRevision',
  'revisionChain',
  'requiresReverification',
  'issueStates',
  'selectedSuggestions'
] as const
const OPTION_KEYS = [
  'scenario',
  'enableSecurity',
  'enableSensitive',
  'enableAdExtreme',
  'glossary',
  'bannedWords'
] as const
const FILTER_KEYS = ['layer', 'severity'] as const
const UI_KEYS = [
  'settingsTab',
  'resultTab',
  'showFindReplace',
  'trackChanges',
  'selectedIssueId'
] as const
const LAYERS = new Set([
  'all',
  'character',
  'vocabulary',
  'sentence',
  'format',
  'discourse',
  'security'
])
const SEVERITIES = new Set(['all', 'error', 'warning', 'info'])
const FILE_TYPES = new Set(['docx', 'doc', 'pdf', 'txt', 'rtf', 'md', 'csv', 'png', 'jpg'])
const EXPORT_AUTHORITY_KEYS = [
  'jobId',
  'documentId',
  'verificationRunId',
  'sourceVersion',
  'fileType',
  'requiresOcrReconstruction',
  'latestRevisionId',
  'latestRevisionNumber',
  'persistedText',
  'recheckGrant'
] as const
const LEGACY_EXPORT_AUTHORITY_KEYS = [
  'jobId',
  'documentId',
  'verificationRunId',
  'sourceVersion',
  'fileType',
  'requiresOcrReconstruction',
  'latestRevisionId',
  'latestRevisionNumber',
  'persistedText'
] as const
const LEGACY_EXPORT_PROVENANCE_KEYS = [
  'resultDocumentId',
  'resultVerificationRunId',
  'resultSourceVersion',
  'resultTextFingerprint',
  'binding'
] as const
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
const SHA256_SOURCE_VERSION_PATTERN = /^sha256:[0-9a-f]{64}$/

export function bindWorkspaceExportAuthority(
  source: WorkspaceExportAuthoritySource,
  result: VerificationResult,
  submittedText: string,
  recheckGrant: string
): WorkspaceExportAuthority | null {
  const preparedSource = preparedExportAuthoritySource(source)
  if (
    preparedSource === undefined ||
    result.execution_mode !== 'synchronous' ||
    result.text !== submittedText ||
    !SHA256_SOURCE_VERSION_PATTERN.test(result.source_version) ||
    !isBoundedText(recheckGrant, MAX_RECHECK_GRANT_CODE_POINTS) ||
    recheckGrant.length === 0
  ) {
    return null
  }
  return Object.freeze({
    ...preparedSource,
    recheckGrant
  })
}

export function isWorkspaceExportAuthorityBoundToResult(
  authority: WorkspaceExportAuthority,
  result: VerificationResult
): boolean {
  const prepared = preparedExportAuthority(authority, result)
  return prepared !== undefined && prepared !== null
}

export function useWorkspaceSession(
  storage: Storage,
  workspace: VerificationWorkspace,
  limits: { maxRawBytes?: number } = {}
) {
  const warningState = ref<string | null>(null)
  const maxRawBytes =
    limits.maxRawBytes ?? MAX_WORKSPACE_SESSION_RAW_BYTES
  let savedRevision: string | null = null
  let savedResult: VerificationResult | null = null
  let savedIssueIds = new Set<string>()
  let lastUiRaw: string | null = null
  let savedDocumentBytes = 0

  function remember(prepared: PreparedSession): void {
    savedRevision = prepared.workspace.currentRevision.revision_id
    savedResult = workspace.result.value
    savedIssueIds = new Set(prepared.workspace.safeIssues.map((issue) => issue.issue_id))
    lastUiRaw = null
  }

  function prepareUi(value: unknown): Pick<WorkspaceSessionUiState, 'options' | 'filters' | 'viewMode' | 'ui'> | null {
    if (!isRecord(value) || !hasExactKeys(value, ['options', 'filters', 'viewMode', 'ui'])) return null
    const options = preparedOptions(value.options)
    if (
      options === null ||
      !isRecord(value.filters) || !hasExactKeys(value.filters, FILTER_KEYS) ||
      typeof value.filters.layer !== 'string' || !LAYERS.has(value.filters.layer) ||
      typeof value.filters.severity !== 'string' || !SEVERITIES.has(value.filters.severity) ||
      (value.viewMode !== 'sentence' && value.viewMode !== 'continuous') ||
      !isRecord(value.ui) || !hasExactKeys(value.ui, UI_KEYS) || !isUiState(value.ui) ||
      (value.ui.selectedIssueId !== null &&
        (workspace.requiresReverification.value || !savedIssueIds.has(value.ui.selectedIssueId)))
    ) return null
    return {
      options,
      filters: { layer: value.filters.layer as IssueLayerFilter, severity: value.filters.severity as WorkspaceSeverityFilter },
      viewMode: value.viewMode,
      ui: { ...value.ui }
    }
  }

  function saveUi(state: WorkspaceSessionUiState): boolean {
    if (workspace.result.value !== savedResult ||
      workspace.currentRevision.value?.revision_id !== savedRevision || savedResult === null) {
      return save(state)
    }
    const ui = prepareUi({ options: state.options, filters: state.filters, viewMode: state.viewMode, ui: state.ui })
    if (ui === null) {
      warningState.value = '当前工作区状态无效，无法保存会话。'
      return false
    }
    try {
      const raw = JSON.stringify({
        version: 1, documentId: savedResult.document_id,
        runId: savedResult.verification_run_id, revisionId: savedRevision, state: ui
      })
      if (!isWorkspaceSessionRawSizeAllowed(raw, Math.min(maxRawBytes - savedDocumentBytes, 128 * 1024))) {
        warningState.value = '当前工作区状态超过会话大小限制，无法保存会话。'
        return false
      }
      if (raw !== lastUiRaw) storage.setItem(WORKSPACE_SESSION_UI_KEY, raw)
      lastUiRaw = raw
      warningState.value = null
      return true
    } catch {
      warningState.value = '浏览器存储空间不足或不可用，无法保存会话；当前编辑仍保留在内存中。'
      return false
    }
  }

  function save(state: WorkspaceSessionUiState): boolean {
    const result = workspace.result.value
    const currentRevision = workspace.currentRevision.value
    if (result === null || currentRevision === null) {
      return false
    }
    const payload = {
      version: WORKSPACE_SESSION_VERSION,
      workspace: {
        result,
        currentRevision,
        revisionChain: workspace.revisionChain.value,
        requiresReverification: workspace.requiresReverification.value,
        issueStates: workspace.issueStates.value,
        selectedSuggestions: workspace.selectedSuggestions.value,
        textUndoHistory: workspace.textUndoHistory.value
      },
      ...state
    }
    if (!hasBoundedSessionPayload(payload)) {
      warningState.value = '当前工作区状态超过会话大小限制，无法保存会话。'
      return false
    }
    const prepared = prepareSession(payload, workspace)
    if (prepared === null) {
      warningState.value = '当前工作区状态无效，无法保存会话。'
      return false
    }
    try {
      const serialized = JSON.stringify({
        version: WORKSPACE_SESSION_VERSION,
        workspace: payload.workspace,
        ...prepared.state
      })
      if (!isWorkspaceSessionRawSizeAllowed(serialized, maxRawBytes)) {
        warningState.value = '当前工作区状态超过会话大小限制，无法保存会话。'
        return false
      }
      storage.removeItem(WORKSPACE_SESSION_UI_KEY)
      storage.setItem(
        WORKSPACE_SESSION_KEY,
        serialized
      )
      remember(prepared)
      savedDocumentBytes = new TextEncoder().encode(serialized).byteLength
      warningState.value = null
      return true
    } catch {
      warningState.value =
        '浏览器存储空间不足或不可用，无法保存会话；当前编辑仍保留在内存中。'
      return false
    }
  }

  function restore(): WorkspaceSessionUiState | null {
    let raw: string | null
    try {
      raw = storage.getItem(WORKSPACE_SESSION_KEY)
    } catch {
      warningState.value = '无法读取浏览器会话存储。'
      return null
    }
    if (raw === null) {
      return null
    }
    if (!isWorkspaceSessionRawSizeAllowed(raw, maxRawBytes)) {
      warningState.value = '已保存的工作区会话超过大小限制，未恢复任何状态。'
      removeInvalidSession(storage)
      return null
    }
    try {
      const parsed: unknown = JSON.parse(raw)
      if (!hasBoundedSessionPayload(parsed)) {
        warningState.value = '已保存的工作区会话超过大小限制，未恢复任何状态。'
        removeInvalidSession(storage)
        return null
      }
      const prepared =
        prepareSession(parsed, workspace) ??
        prepareVersion6Session(parsed, workspace) ??
        prepareVersion5Session(parsed, workspace) ??
        prepareVersion4Session(parsed, workspace) ??
        prepareVersion3Session(parsed, workspace) ??
        prepareLegacySession(parsed, workspace)
      if (prepared === null) {
        warningState.value = '已保存的工作区会话无效，未恢复任何状态。'
        removeInvalidSession(storage)
        return null
      }
      workspace.commitWorkspaceRestore(prepared.workspace)
      remember(prepared)
      savedDocumentBytes = new TextEncoder().encode(raw).byteLength
      warningState.value = null
      try {
        const uiRaw = storage.getItem(WORKSPACE_SESSION_UI_KEY)
        if (uiRaw !== null) {
          if (!isWorkspaceSessionRawSizeAllowed(uiRaw, Math.min(maxRawBytes - savedDocumentBytes, 128 * 1024))) throw new Error()
          const overlay: unknown = JSON.parse(uiRaw)
          if (!isRecord(overlay) ||
            !hasExactKeys(overlay, ['version', 'documentId', 'runId', 'revisionId', 'state']) ||
            overlay.version !== 1 || overlay.documentId !== savedResult?.document_id ||
            overlay.runId !== savedResult?.verification_run_id || overlay.revisionId !== savedRevision) throw new Error()
          const ui = prepareUi(overlay.state)
          if (ui === null) throw new Error()
          prepared.state = { ...prepared.state, ...ui }
          lastUiRaw = uiRaw
        }
      } catch {
        try { storage.removeItem(WORKSPACE_SESSION_UI_KEY) } catch { /* Keep the valid document snapshot. */ }
        warningState.value = '界面偏好记录无效或不可用，已恢复文档及上次保存的设置。'
      }
      return prepared.state
    } catch {
      warningState.value = '已保存的工作区会话损坏，未恢复任何状态。'
      removeInvalidSession(storage)
      return null
    }
  }

  function clear(): void {
    savedResult = null
    savedRevision = null
    lastUiRaw = null
    savedDocumentBytes = 0
    try {
      storage.removeItem(WORKSPACE_SESSION_KEY)
      storage.removeItem(WORKSPACE_SESSION_UI_KEY)
      warningState.value = null
    } catch {
      warningState.value = '无法清除浏览器会话存储。'
    }
  }

  return {
    warning: computed(() => warningState.value),
    save,
    saveUi,
    restore,
    clear
  }
}

export function isWorkspaceSessionRawSizeAllowed(
  raw: string,
  maxBytes: number = MAX_WORKSPACE_SESSION_RAW_BYTES
): boolean {
  if (
    !Number.isInteger(maxBytes) ||
    maxBytes < 0 ||
    raw.length > maxBytes
  ) {
    return false
  }
  return new TextEncoder().encode(raw).byteLength <= maxBytes
}

function hasBoundedSessionPayload(value: unknown): boolean {
  if (!isRecord(value)) {
    return false
  }
  if (
    Object.hasOwn(value, 'result') &&
    Object.hasOwn(value, 'workingText') &&
    !Object.hasOwn(value, 'currentRevision')
  ) {
    return (
      hasBoundedWorkspaceResult(value.result) &&
      isBoundedText(
        value.workingText,
        MAX_WORKSPACE_REVISION_CODE_POINTS
      ) &&
      hasBoundedRecord(value.issueStates, MAX_WORKSPACE_RESULT_ISSUES) &&
      hasBoundedRecord(
        value.selectedSuggestions,
        MAX_WORKSPACE_RESULT_ISSUES
      )
    )
  }
  const workspace = isRecord(value.workspace) ? value.workspace : value
  return (
    hasBoundedWorkspaceResult(workspace.result) &&
    hasBoundedRevision(workspace.currentRevision) &&
    Array.isArray(workspace.revisionChain) &&
    workspace.revisionChain.length <= MAX_WORKSPACE_REVISION_CHAIN &&
    workspace.revisionChain.every(hasBoundedRevision) &&
    (
      !Object.hasOwn(workspace, 'textUndoHistory') ||
      hasBoundedTextUndoHistory(workspace.textUndoHistory)
    ) &&
    hasBoundedRecord(workspace.issueStates, MAX_WORKSPACE_RESULT_ISSUES) &&
    hasBoundedRecord(
      workspace.selectedSuggestions,
      MAX_WORKSPACE_RESULT_ISSUES
    ) &&
    (
      !Object.hasOwn(value, 'options') ||
      hasBoundedOptions(value.options)
    )
  )
}

function hasBoundedTextUndoHistory(value: unknown): boolean {
  return (
    Array.isArray(value) &&
    value.length <= MAX_WORKSPACE_REVISION_CHAIN &&
    value.every((entry) =>
      isRecord(entry) &&
      (entry.revisionId === null || isBoundedText(entry.revisionId, 36)) &&
      (
        entry.reviewState === null ||
        (
          isRecord(entry.reviewState) &&
          hasBoundedRecord(entry.reviewState.issueStates, MAX_WORKSPACE_RESULT_ISSUES) &&
          hasBoundedRecord(entry.reviewState.selectedSuggestions, MAX_WORKSPACE_RESULT_ISSUES)
        )
      )
    )
  )
}

export function hasBoundedWorkspaceResult(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !isBoundedText(value.text, MAX_WORKSPACE_REVISION_CODE_POINTS) ||
    !Array.isArray(value.blocks) ||
    value.blocks.length > MAX_WORKSPACE_RESULT_BLOCKS ||
    !Array.isArray(value.issues) ||
    value.issues.length > MAX_WORKSPACE_RESULT_ISSUES
  ) {
    return false
  }
  return (
    value.blocks.every(
      (block) =>
        isRecord(block) &&
        isBoundedText(
          block.text,
          MAX_WORKSPACE_REVISION_CODE_POINTS
        )
    ) &&
    value.issues.every(hasBoundedIssue)
  )
}

function hasBoundedRevision(value: unknown): boolean {
  return (
    isRecord(value) &&
    isBoundedText(value.text, MAX_WORKSPACE_REVISION_CODE_POINTS)
  )
}

function hasBoundedIssue(value: unknown): boolean {
  const alternatives = isRecord(value)
    ? value.alternatives
    : undefined
  if (
    !isRecord(value) ||
    (
      alternatives !== undefined &&
      alternatives !== null &&
      !Array.isArray(alternatives)
    ) ||
    (
      Array.isArray(alternatives) &&
      alternatives.length > MAX_WORKSPACE_ISSUE_ALTERNATIVES
    )
  ) {
    return false
  }
  for (const key of [
    'original',
    'suggestion',
    'message',
    'description',
    'context',
    'review',
    'review_reason'
  ]) {
    const text = value[key]
    if (
      text !== null &&
      !isBoundedText(text, MAX_WORKSPACE_ISSUE_TEXT_CODE_POINTS)
    ) {
      return false
    }
  }
  return (alternatives ?? []).every((alternative) =>
    isBoundedText(alternative, MAX_WORKSPACE_ISSUE_TEXT_CODE_POINTS)
  )
}

function hasBoundedOptions(value: unknown): boolean {
  if (
    !isRecord(value) ||
    !Array.isArray(value.glossary) ||
    value.glossary.length > MAX_WORKSPACE_TERMINOLOGY_ITEMS ||
    !Array.isArray(value.bannedWords) ||
    value.bannedWords.length > MAX_WORKSPACE_TERMINOLOGY_ITEMS
  ) {
    return false
  }
  return (
    value.glossary.every(
      (term) =>
        isRecord(term) &&
        isBoundedText(
          term.original,
          MAX_WORKSPACE_TERMINOLOGY_CODE_POINTS
        ) &&
        isBoundedText(
          term.standard,
          MAX_WORKSPACE_TERMINOLOGY_CODE_POINTS
        )
    ) &&
    value.bannedWords.every((word) =>
      isBoundedText(word, MAX_WORKSPACE_TERMINOLOGY_CODE_POINTS)
    )
  )
}

function hasBoundedRecord(value: unknown, maxEntries: number): boolean {
  return isRecord(value) && Object.keys(value).length <= maxEntries
}

function isBoundedText(value: unknown, maxCodePoints: number): value is string {
  if (typeof value !== 'string') {
    return false
  }
  let codePoints = 0
  for (const _character of value) {
    codePoints += 1
    if (codePoints > maxCodePoints) {
      return false
    }
  }
  return true
}

function prepareLegacySession(
  value: unknown,
  workspace: VerificationWorkspace
): PreparedSession | null {
  const preparedWorkspace = workspace.prepareWorkspaceRestore(value)
  if (
    preparedWorkspace === null ||
    preparedWorkspace.result.execution_mode !== 'synchronous'
  ) {
    return null
  }
  return {
    workspace: preparedWorkspace,
    state: {
      options: {
        ...createDefaultAnalyzeOptions(),
        scenario: preparedWorkspace.result.scenario
      },
      filters: {
        layer: 'all',
        severity: 'all'
      },
      viewMode: 'sentence',
      ui: {
        settingsTab: 'settings',
        resultTab: 'issues',
        showFindReplace: false,
        trackChanges: false,
        selectedIssueId: null
      },
      jobId: null,
      exportAuthority: null
    }
  }
}

function removeInvalidSession(storage: Storage): void {
  try {
    storage.removeItem(WORKSPACE_SESSION_KEY)
    storage.removeItem(WORKSPACE_SESSION_UI_KEY)
  } catch {
    // The visible restore warning remains authoritative.
  }
}

function prepareSession(
  value: unknown,
  workspace: VerificationWorkspace
): PreparedSession | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, SESSION_KEYS) ||
    value.version !== WORKSPACE_SESSION_VERSION ||
    !isRecord(value.workspace) ||
    !hasExactKeys(value.workspace, [...WORKSPACE_KEYS, 'textUndoHistory'])
  ) {
    return null
  }
  return prepareSessionState(value, workspace, value.exportAuthority)
}

function prepareVersion6Session(
  value: unknown,
  workspace: VerificationWorkspace
): PreparedSession | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, SESSION_KEYS) ||
    value.version !== 6 ||
    !isRecord(value.workspace) ||
    !hasExactKeys(value.workspace, WORKSPACE_KEYS)
  ) {
    return null
  }
  return prepareSessionState(value, workspace, value.exportAuthority)
}

function prepareVersion3Session(
  value: unknown,
  workspace: VerificationWorkspace
): PreparedSession | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, VERSION_3_SESSION_KEYS) ||
    value.version !== 3 ||
    !isRecord(value.workspace) ||
    !hasExactKeys(value.workspace, WORKSPACE_KEYS)
  ) {
    return null
  }
  return prepareSessionState(value, workspace, null)
}

function prepareVersion4Session(
  value: unknown,
  workspace: VerificationWorkspace
): PreparedSession | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, VERSION_4_SESSION_KEYS) ||
    value.version !== 4 ||
    !isRecord(value.workspace) ||
    !hasExactKeys(value.workspace, WORKSPACE_KEYS) ||
    (
      value.exportAuthority !== null &&
      preparedLegacyExportAuthority(value.exportAuthority) === undefined
    )
  ) {
    return null
  }
  const prepared = prepareSessionState(value, workspace, null)
  if (
    prepared === null ||
    (
      prepared.workspace.result.execution_mode === 'asynchronous' &&
      value.exportAuthority !== null
    )
  ) {
    return null
  }
  return prepared
}

function prepareVersion5Session(
  value: unknown,
  workspace: VerificationWorkspace
): PreparedSession | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, VERSION_5_SESSION_KEYS) ||
    value.version !== 5 ||
    !isRecord(value.workspace) ||
    !hasExactKeys(value.workspace, WORKSPACE_KEYS) ||
    (
      value.exportAuthority !== null &&
      preparedVersion5ExportAuthority(value.exportAuthority) === undefined
    )
  ) {
    return null
  }
  return prepareSessionState(value, workspace, null)
}

function prepareSessionState(
  value: Record<string, unknown>,
  workspace: VerificationWorkspace,
  rawExportAuthority: unknown
): PreparedSession | null {
  const workspaceValue = value.workspace
  if (!isRecord(workspaceValue)) {
    return null
  }
  const preparedWorkspace = workspace.prepareWorkspaceRestore({
    version: 2,
    result: workspaceValue.result,
    currentRevision: workspaceValue.currentRevision,
    revisionChain: workspaceValue.revisionChain,
    requiresReverification: workspaceValue.requiresReverification,
    issueStates: workspaceValue.issueStates,
    selectedSuggestions: workspaceValue.selectedSuggestions,
    ...(Object.hasOwn(workspaceValue, 'textUndoHistory')
      ? { textUndoHistory: workspaceValue.textUndoHistory }
      : {})
  })
  if (
    preparedWorkspace === null ||
    !sameRecordKeys(
      workspaceValue.issueStates,
      preparedWorkspace.issueStates
    ) ||
    !sameRecordKeys(
      workspaceValue.selectedSuggestions,
      preparedWorkspace.selectedSuggestions
    )
  ) {
    return null
  }

  const options = preparedOptions(value.options)
  if (
    options === null ||
    !isRecord(value.filters) ||
    !hasExactKeys(value.filters, FILTER_KEYS) ||
    typeof value.filters.layer !== 'string' ||
    !LAYERS.has(value.filters.layer) ||
    typeof value.filters.severity !== 'string' ||
    !SEVERITIES.has(value.filters.severity) ||
    (value.viewMode !== 'sentence' && value.viewMode !== 'continuous') ||
    !isRecord(value.ui) ||
    !hasExactKeys(value.ui, UI_KEYS) ||
    !isUiState(value.ui)
  ) {
    return null
  }
  const jobId = value.jobId
  const exportAuthority = preparedExportAuthority(
    rawExportAuthority,
    preparedWorkspace.result
  )
  if (
    (jobId !== null &&
      (typeof jobId !== 'string' || !UUID_PATTERN.test(jobId))) ||
    (preparedWorkspace.result.execution_mode === 'asynchronous' &&
      jobId !== preparedWorkspace.result.document_id) ||
    (preparedWorkspace.result.execution_mode === 'synchronous' &&
      jobId !== null) ||
    exportAuthority === undefined ||
    (preparedWorkspace.result.execution_mode === 'asynchronous' &&
      exportAuthority !== null)
  ) {
    return null
  }
  const selectedIssueId = value.ui.selectedIssueId
  if (
    selectedIssueId !== null &&
    (preparedWorkspace.requiresReverification ||
      !preparedWorkspace.safeIssues.some(
        (issue) => issue.issue_id === selectedIssueId
      ))
  ) {
    return null
  }

  return {
    workspace: preparedWorkspace,
    state: {
      options,
      filters: {
        layer: value.filters.layer as IssueLayerFilter,
        severity: value.filters.severity as WorkspaceSeverityFilter
      },
      viewMode: value.viewMode,
      ui: {
        settingsTab: value.ui.settingsTab,
        resultTab: value.ui.resultTab,
        showFindReplace: value.ui.showFindReplace,
        trackChanges: value.ui.trackChanges,
        selectedIssueId
      },
      jobId,
      exportAuthority
    }
  }
}

function preparedExportAuthority(
  value: unknown,
  result: VerificationResult
): WorkspaceExportAuthority | null | undefined {
  if (value === null) {
    return null
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, EXPORT_AUTHORITY_KEYS) ||
    !isBoundedText(value.recheckGrant, MAX_RECHECK_GRANT_CODE_POINTS) ||
    value.recheckGrant.length === 0
  ) {
    return undefined
  }
  const source = preparedExportAuthoritySource(value)
  if (source === undefined) {
    return undefined
  }
  return bindWorkspaceExportAuthority(
    source,
    result,
    result.text,
    value.recheckGrant
  ) ?? undefined
}

function preparedVersion5ExportAuthority(
  value: unknown
): WorkspaceExportAuthoritySource | null | undefined {
  if (value === null) {
    return null
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      ...LEGACY_EXPORT_AUTHORITY_KEYS,
      'provenance'
    ]) ||
    !isRecord(value.provenance) ||
    !hasExactKeys(value.provenance, LEGACY_EXPORT_PROVENANCE_KEYS) ||
    !Object.values(value.provenance).every((item) =>
      isBoundedText(item, 1000)
    )
  ) {
    return undefined
  }
  return preparedExportAuthoritySource(value)
}

function preparedLegacyExportAuthority(
  value: unknown
): WorkspaceExportAuthoritySource | null | undefined {
  if (value === null) {
    return null
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, LEGACY_EXPORT_AUTHORITY_KEYS)
  ) {
    return undefined
  }
  return preparedExportAuthoritySource(value)
}

function preparedExportAuthoritySource(
  value: unknown
): WorkspaceExportAuthoritySource | undefined {
  if (
    !isRecord(value) ||
    typeof value.jobId !== 'string' ||
    !UUID_PATTERN.test(value.jobId) ||
    value.documentId !== value.jobId ||
    typeof value.verificationRunId !== 'string' ||
    !UUID_PATTERN.test(value.verificationRunId) ||
    !isBoundedText(value.sourceVersion, 500) ||
    typeof value.fileType !== 'string' ||
    !FILE_TYPES.has(value.fileType) ||
    typeof value.requiresOcrReconstruction !== 'boolean' ||
    !Number.isInteger(value.latestRevisionNumber) ||
    Number(value.latestRevisionNumber) < 0 ||
    (
      value.latestRevisionId !== null &&
      (
        typeof value.latestRevisionId !== 'string' ||
        !UUID_PATTERN.test(value.latestRevisionId)
      )
    ) ||
    (
      (value.latestRevisionId === null) !==
      (Number(value.latestRevisionNumber) === 0)
    ) ||
    (
      value.persistedText !== null &&
      !isBoundedText(
        value.persistedText,
        MAX_WORKSPACE_REVISION_CODE_POINTS
      )
    ) ||
    (
      (value.latestRevisionId === null) !==
      (value.persistedText === null)
    )
  ) {
    return undefined
  }
  return Object.freeze({
    jobId: value.jobId,
    documentId: value.documentId,
    verificationRunId: value.verificationRunId,
    sourceVersion: value.sourceVersion,
    fileType: value.fileType as FileType,
    requiresOcrReconstruction: value.requiresOcrReconstruction,
    latestRevisionId: value.latestRevisionId,
    latestRevisionNumber: Number(value.latestRevisionNumber),
    persistedText: value.persistedText
  })
}

function preparedOptions(value: unknown): AnalyzeOptions | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      ...OPTION_KEYS,
      ...('ocrLanguage' in value ? ['ocrLanguage'] : []),
      ...('enableExtendedRules' in value ? ['enableExtendedRules'] : []),
      ...('enableSemanticDiscovery' in value ? ['enableSemanticDiscovery'] : [])
    ]) ||
    !Array.isArray(value.glossary) ||
    !Array.isArray(value.bannedWords)
  ) {
    return null
  }
  try {
    const snapshot = createAnalyzeOptionsSnapshot(
      value as unknown as AnalyzeOptions,
      'persisted'
    )
    return OPTION_KEYS.every(
      (key) => JSON.stringify(value[key]) === JSON.stringify(snapshot[key])
    ) && value.ocrLanguage === snapshot.ocrLanguage &&
      value.enableExtendedRules === snapshot.enableExtendedRules &&
      value.enableSemanticDiscovery === snapshot.enableSemanticDiscovery
      ? snapshot
      : null
  } catch {
    return null
  }
}

function isUiState(value: Record<string, unknown>): value is {
  settingsTab: WorkspaceSettingsTab
  resultTab: WorkspaceResultTab
  showFindReplace: boolean
  trackChanges: boolean
  selectedIssueId: string | null
} {
  return (
    (value.settingsTab === 'settings' ||
      value.settingsTab === 'terms' ||
      value.settingsTab === 'banned') &&
    (value.resultTab === 'issues' || value.resultTab === 'summary') &&
    typeof value.showFindReplace === 'boolean' &&
    typeof value.trackChanges === 'boolean' &&
    (value.selectedIssueId === null ||
      (typeof value.selectedIssueId === 'string' &&
        UUID_PATTERN.test(value.selectedIssueId)))
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(
  value: Record<string, unknown>,
  keys: readonly string[]
): boolean {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  return (
    actual.length === expected.length &&
    actual.every((key, index) => key === expected[index])
  )
}

function sameRecordKeys(
  value: unknown,
  prepared: Readonly<Record<string, unknown>>
): boolean {
  return (
    isRecord(value) &&
    Object.keys(value).length === Object.keys(prepared).length &&
    Object.keys(value).every((key) => Object.hasOwn(prepared, key))
  )
}
