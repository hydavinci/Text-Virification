import { describe, expect, it } from 'vitest'

import {
  WORKSPACE_SESSION_VERSION,
  useWorkspaceSession
} from '../src/composables/useWorkspaceSession'
import { useVerificationWorkspace } from '../src/composables/useVerificationWorkspace'
import type {
  AnalyzeOptions,
  VerificationIssue,
  VerificationResult
} from '../src/types/verification'

const issue: VerificationIssue = {
  issue_id: '33333333-3333-4333-8333-333333333333',
  document_id: '11111111-1111-4111-8111-111111111111',
  verification_run_id: '22222222-2222-4222-8222-222222222222',
  block_id: 'p-0',
  page: null,
  start: 0,
  end: 2,
  block_start: 0,
  block_end: 2,
  position: 0,
  end_position: 2,
  original: '帐号',
  suggestion: '账号',
  alternatives: ['账号'],
  type: 'typo',
  severity: 'warning',
  layer: 'character',
  message: '疑似错别字',
  description: '疑似错别字',
  rule_id: 'cn_typo',
  rule_version: '1',
  source: 'test',
  source_version: '1',
  confidence: 0.9,
  auto_fixable: true,
  context: '帐号测试',
  review: null,
  review_reason: null
}

const result: VerificationResult = {
  success: true,
  filename: 'sample.pdf',
  source_name: 'sample.pdf',
  file_type: 'pdf',
  text: '帐号测试',
  blocks: [
    {
      block_id: 'p-0',
      kind: 'paragraph',
      text: '帐号测试',
      global_start: 0,
      global_end: 4,
      block_start: 0,
      block_end: 4,
      page: 1,
      paragraph_index: 0,
      table_index: null,
      row_index: null,
      cell_index: null,
      bbox: [0, 0, 100, 20],
      parent_id: null,
      style: {},
      source_locator: { page: 1, paragraph_index: 0 }
    }
  ],
  parser_name: 'pdf-layout',
  parser_version: '1',
  stats: {
    char_count: 4,
    char_count_no_space: 4,
    line_count: 1,
    paragraph_count: 1,
    language: 'zh',
    primary_count: 4,
    primary_label: '总字数'
  },
  issues: [issue],
  summary: {
    total: 1,
    by_type: { typo: 1 },
    by_severity: { warning: 1 },
    by_rule: { cn_typo: 1 },
    by_layer: { character: 1 }
  },
  file_id: null,
  file_ext: null,
  document_id: '11111111-1111-4111-8111-111111111111',
  verification_run_id: '22222222-2222-4222-8222-222222222222',
  source_version:
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  execution_mode: 'asynchronous',
  analysis_mode: 'local_only',
  dictionary_versions: {},
  degradation: { is_degraded: false, reasons: [] },
  scenario: 'technical'
}

const options: AnalyzeOptions = {
  scenario: 'technical',
  enableSecurity: true,
  enableSensitive: false,
  enableAdExtreme: true,
  glossary: [{ original: 'AI', standard: '人工智能' }],
  bannedWords: ['最好']
}

class MemoryStorage implements Storage {
  readonly values = new Map<string, string>()
  readonly length = 0
  failWrites = false

  clear(): void {
    this.values.clear()
  }

  getItem(key: string): string | null {
    return this.values.get(key) ?? null
  }

  key(index: number): string | null {
    return [...this.values.keys()][index] ?? null
  }

  removeItem(key: string): void {
    this.values.delete(key)
  }

  setItem(key: string, value: string): void {
    if (this.failWrites) {
      throw new DOMException('quota', 'QuotaExceededError')
    }
    this.values.set(key, value)
  }
}

function uiState() {
  return {
    options,
    filters: { layer: 'security' as const, severity: 'warning' as const },
    viewMode: 'continuous' as const,
    ui: {
      settingsTab: 'terms' as const,
      resultTab: 'summary' as const,
      showFindReplace: true,
      trackChanges: false,
      selectedIssueId: issue.issue_id
    },
    jobId: '44444444-4444-4444-8444-444444444444'
  }
}

describe('useWorkspaceSession', () => {
  it('round-trips the complete versioned workspace and UI state', () => {
    const storage = new MemoryStorage()
    const original = useVerificationWorkspace()
    original.loadResult(result)
    original.acceptIssue(issue.issue_id)
    const session = useWorkspaceSession(storage, original)

    expect(session.save(uiState())).toBe(true)
    expect(
      JSON.parse(storage.getItem('text-verification-session') ?? '{}').version
    ).toBe(WORKSPACE_SESSION_VERSION)

    const restoredWorkspace = useVerificationWorkspace()
    const restoredSession = useWorkspaceSession(storage, restoredWorkspace)
    const restored = restoredSession.restore()

    expect(restored).toEqual(uiState())
    expect(restoredWorkspace.result.value).toEqual(result)
    expect(restoredWorkspace.issueStates.value).toEqual({
      [issue.issue_id]: 'accepted'
    })
    expect(restoredWorkspace.revisionChain.value).toEqual(
      original.revisionChain.value
    )
  })

  it('leaves current state unchanged for partial, foreign, or corrupt payloads', () => {
    const storage = new MemoryStorage()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(result)
    workspace.acceptIssue(issue.issue_id)
    const currentResult = workspace.result.value
    const currentRevision = workspace.currentRevision.value
    const session = useWorkspaceSession(storage, workspace)
    expect(session.save(uiState())).toBe(true)
    const valid = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )

    for (const invalid of [
      { ...valid, options: undefined },
      {
        ...valid,
        workspace: {
          ...valid.workspace,
          revisionChain: valid.workspace.revisionChain.map(
            (revision: Record<string, unknown>, index: number) =>
              index === 1
                ? { ...revision, document_id: crypto.randomUUID() }
                : revision
          )
        }
      },
      {
        ...valid,
        options: {
          ...valid.options,
          bannedWords: [' 最好 ']
        }
      },
      '{not-json'
    ]) {
      storage.setItem(
        'text-verification-session',
        typeof invalid === 'string' ? invalid : JSON.stringify(invalid)
      )
      expect(session.restore()).toBeNull()
      expect(workspace.result.value).toBe(currentResult)
      expect(workspace.currentRevision.value).toBe(currentRevision)
      expect(workspace.issueStates.value).toEqual({
        [issue.issue_id]: 'accepted'
      })
    }
  })

  it('reports storage quota failures without changing in-memory state', () => {
    const storage = new MemoryStorage()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(result)
    workspace.acceptIssue(issue.issue_id)
    const revision = workspace.currentRevision.value
    storage.failWrites = true
    const session = useWorkspaceSession(storage, workspace)

    expect(session.save(uiState())).toBe(false)
    expect(session.warning.value).toContain('无法保存')
    expect(workspace.currentRevision.value).toBe(revision)
    expect(workspace.modifiedText.value).toBe('账号测试')
  })
})
