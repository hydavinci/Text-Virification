import { computed, ref } from 'vue'

import { createAnalyzeOptionsSnapshot } from '../api/analyzeOptions'
import type {
  AnalyzeOptions,
  IssueSeverity
} from '../types/verification'
import type { IssueLayerFilter } from './useIssueNavigation'
import {
  type PreparedWorkspaceRestore,
  type useVerificationWorkspace
} from './useVerificationWorkspace'

export const WORKSPACE_SESSION_VERSION = 3
export const WORKSPACE_SESSION_KEY = 'text-verification-session'

export type WorkspaceViewMode = 'sentence' | 'continuous'
export type WorkspaceSettingsTab = 'settings' | 'terms' | 'banned'
export type WorkspaceResultTab = 'issues' | 'summary'
export type WorkspaceSeverityFilter = 'all' | IssueSeverity

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
  'jobId'
] as const
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
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function useWorkspaceSession(
  storage: Storage,
  workspace: VerificationWorkspace
) {
  const warningState = ref<string | null>(null)

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
        selectedSuggestions: workspace.selectedSuggestions.value
      },
      ...state
    }
    const prepared = prepareSession(payload, workspace)
    if (prepared === null) {
      warningState.value = '当前工作区状态无效，无法保存会话。'
      return false
    }
    try {
      storage.setItem(
        WORKSPACE_SESSION_KEY,
        JSON.stringify({
          version: WORKSPACE_SESSION_VERSION,
          workspace: payload.workspace,
          ...prepared.state
        })
      )
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
    try {
      const parsed: unknown = JSON.parse(raw)
      const prepared =
        prepareSession(parsed, workspace) ??
        prepareLegacySession(parsed, workspace)
      if (prepared === null) {
        warningState.value = '已保存的工作区会话无效，未恢复任何状态。'
        removeInvalidSession(storage)
        return null
      }
      workspace.commitWorkspaceRestore(prepared.workspace)
      warningState.value = null
      return prepared.state
    } catch {
      warningState.value = '已保存的工作区会话损坏，未恢复任何状态。'
      removeInvalidSession(storage)
      return null
    }
  }

  function clear(): void {
    try {
      storage.removeItem(WORKSPACE_SESSION_KEY)
      warningState.value = null
    } catch {
      warningState.value = '无法清除浏览器会话存储。'
    }
  }

  return {
    warning: computed(() => warningState.value),
    save,
    restore,
    clear
  }
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
        scenario: preparedWorkspace.result.scenario,
        enableSecurity: true,
        enableSensitive: true,
        enableAdExtreme: false,
        glossary: [],
        bannedWords: []
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
        trackChanges: true,
        selectedIssueId: null
      },
      jobId: null
    }
  }
}

function removeInvalidSession(storage: Storage): void {
  try {
    storage.removeItem(WORKSPACE_SESSION_KEY)
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
    !hasExactKeys(value.workspace, WORKSPACE_KEYS)
  ) {
    return null
  }
  const preparedWorkspace = workspace.prepareWorkspaceRestore({
    version: 2,
    result: value.workspace.result,
    currentRevision: value.workspace.currentRevision,
    revisionChain: value.workspace.revisionChain,
    requiresReverification: value.workspace.requiresReverification,
    issueStates: value.workspace.issueStates,
    selectedSuggestions: value.workspace.selectedSuggestions
  })
  if (
    preparedWorkspace === null ||
    !sameRecordKeys(
      value.workspace.issueStates,
      preparedWorkspace.issueStates
    ) ||
    !sameRecordKeys(
      value.workspace.selectedSuggestions,
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
  if (
    (jobId !== null &&
      (typeof jobId !== 'string' || !UUID_PATTERN.test(jobId))) ||
    (preparedWorkspace.result.execution_mode === 'asynchronous' &&
      jobId !== preparedWorkspace.result.document_id) ||
    (preparedWorkspace.result.execution_mode === 'synchronous' &&
      jobId !== null)
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
      jobId
    }
  }
}

function preparedOptions(value: unknown): AnalyzeOptions | null {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, OPTION_KEYS) ||
    !Array.isArray(value.glossary) ||
    !Array.isArray(value.bannedWords)
  ) {
    return null
  }
  try {
    const snapshot = createAnalyzeOptionsSnapshot(
      value as unknown as AnalyzeOptions
    )
    return JSON.stringify(value) === JSON.stringify(snapshot)
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
