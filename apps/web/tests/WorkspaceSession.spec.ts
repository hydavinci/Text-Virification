import { describe, expect, it, vi } from 'vitest'

import {
  MAX_WORKSPACE_RESULT_BLOCKS,
  MAX_WORKSPACE_REVISION_CODE_POINTS,
  WORKSPACE_SESSION_VERSION,
  bindWorkspaceExportAuthority,
  isWorkspaceSessionRawSizeAllowed,
  type WorkspaceExportAuthoritySource,
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
    jobId: result.document_id,
    exportAuthority: null
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

  it('round-trips validated file export authority for a rechecked synchronous result', () => {
    const storage = new MemoryStorage()
    const rechecked = {
      ...result,
      document_id: '77777777-7777-4777-8777-777777777777',
      verification_run_id: '88888888-8888-4888-8888-888888888888',
      source_version:
        'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      execution_mode: 'synchronous' as const,
      issues: [],
      summary: {
        total: 0,
        by_type: {},
        by_severity: {},
        by_rule: {},
        by_layer: {}
      }
    }
    const workspace = useVerificationWorkspace()
    workspace.loadResult(rechecked)
    const session = useWorkspaceSession(storage, workspace)
    const authoritySource: WorkspaceExportAuthoritySource = {
      jobId: result.document_id,
      documentId: result.document_id,
      verificationRunId: result.verification_run_id,
      sourceVersion: result.source_version,
      fileType: 'docx',
      requiresOcrReconstruction: false,
      latestRevisionId: null,
      latestRevisionNumber: 0,
      persistedText: null
    }
    const exportAuthority = bindWorkspaceExportAuthority(
      authoritySource,
      rechecked,
      rechecked.text,
      'server-issued-opaque-grant'
    )
    expect(exportAuthority).not.toBeNull()
    const state = {
      ...uiState(),
      jobId: null,
      ui: {
        ...uiState().ui,
        selectedIssueId: null
      },
      exportAuthority
    }

    expect(session.save(state), session.warning.value ?? '').toBe(true)
    const restoredWorkspace = useVerificationWorkspace()
    const restored = useWorkspaceSession(
      storage,
      restoredWorkspace
    ).restore()

    expect(restored).toEqual(state)
    expect(restoredWorkspace.result.value).toEqual(rechecked)
  })

  it('persists only the bounded opaque server grant for rechecked export authority', () => {
    const storage = new MemoryStorage()
    const rechecked = {
      ...result,
      document_id: '77777777-7777-4777-8777-777777777777',
      verification_run_id: '88888888-8888-4888-8888-888888888888',
      source_version:
        'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      execution_mode: 'synchronous' as const,
      issues: [],
      summary: {
        total: 0,
        by_type: {},
        by_severity: {},
        by_rule: {},
        by_layer: {}
      }
    }
    const workspace = useVerificationWorkspace()
    workspace.loadResult(rechecked)
    const session = useWorkspaceSession(storage, workspace)
    const exportAuthority = bindWorkspaceExportAuthority(
      {
        jobId: result.document_id,
        documentId: result.document_id,
        verificationRunId: result.verification_run_id,
        sourceVersion: result.source_version,
        fileType: 'docx',
        requiresOcrReconstruction: false,
        latestRevisionId: null,
        latestRevisionNumber: 0,
        persistedText: null
      },
      rechecked,
      rechecked.text,
      'server-issued-opaque-grant'
    )
    expect(exportAuthority).not.toBeNull()
    expect(exportAuthority).toMatchObject({
      recheckGrant: 'server-issued-opaque-grant'
    })
    expect(exportAuthority).not.toHaveProperty('provenance')

    expect(
      session.save({
        ...uiState(),
        jobId: null,
        ui: { ...uiState().ui, selectedIssueId: null },
        exportAuthority
      })
    ).toBe(true)
    const saved = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )
    expect(saved.version).toBe(6)
    expect(saved.exportAuthority.recheckGrant).toBe(
      'server-issued-opaque-grant'
    )
    expect(saved.exportAuthority).not.toHaveProperty('provenance')

    const restoredWorkspace = useVerificationWorkspace()
    const restored = useWorkspaceSession(
      storage,
      restoredWorkspace
    ).restore()

    expect(restored?.exportAuthority).toEqual(exportAuthority)
  })

  it('restores cross-job opaque authority for backend validation', () => {
    const storage = new MemoryStorage()
    const rechecked = {
      ...result,
      document_id: '77777777-7777-4777-8777-777777777777',
      verification_run_id: '88888888-8888-4888-8888-888888888888',
      source_version:
        'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      execution_mode: 'synchronous' as const,
      issues: [],
      summary: {
        total: 0,
        by_type: {},
        by_severity: {},
        by_rule: {},
        by_layer: {}
      }
    }
    const workspace = useVerificationWorkspace()
    workspace.loadResult(rechecked)
    const session = useWorkspaceSession(storage, workspace)
    const exportAuthority = bindWorkspaceExportAuthority(
      {
        jobId: result.document_id,
        documentId: result.document_id,
        verificationRunId: result.verification_run_id,
        sourceVersion: result.source_version,
        fileType: 'docx',
        requiresOcrReconstruction: false,
        latestRevisionId: null,
        latestRevisionNumber: 0,
        persistedText: null
      },
      rechecked,
      rechecked.text,
      'server-issued-opaque-grant'
    )
    expect(exportAuthority).not.toBeNull()
    expect(
      session.save({
        ...uiState(),
        jobId: null,
        ui: { ...uiState().ui, selectedIssueId: null },
        exportAuthority
      })
    ).toBe(true)
    const saved = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )
    saved.exportAuthority.jobId =
      '99999999-9999-4999-8999-999999999999'
    saved.exportAuthority.documentId =
      '99999999-9999-4999-8999-999999999999'
    storage.setItem('text-verification-session', JSON.stringify(saved))

    const current = useVerificationWorkspace()
    current.loadResult(result)
    current.acceptIssue(issue.issue_id)
    const restored = useWorkspaceSession(storage, current).restore()

    expect(restored?.exportAuthority).toMatchObject({
      jobId: '99999999-9999-4999-8999-999999999999',
      recheckGrant: 'server-issued-opaque-grant'
    })
    expect(current.result.value).toEqual(rechecked)
  })

  it('rejects a tampered recheck result bound to retained authority atomically', () => {
    const storage = new MemoryStorage()
    const rechecked = {
      ...result,
      document_id: '77777777-7777-4777-8777-777777777777',
      verification_run_id: '88888888-8888-4888-8888-888888888888',
      source_version:
        'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      execution_mode: 'synchronous' as const,
      issues: [],
      summary: {
        total: 0,
        by_type: {},
        by_severity: {},
        by_rule: {},
        by_layer: {}
      }
    }
    const workspace = useVerificationWorkspace()
    workspace.loadResult(rechecked)
    const session = useWorkspaceSession(storage, workspace)
    const exportAuthority = bindWorkspaceExportAuthority(
      {
        jobId: result.document_id,
        documentId: result.document_id,
        verificationRunId: result.verification_run_id,
        sourceVersion: result.source_version,
        fileType: 'docx',
        requiresOcrReconstruction: false,
        latestRevisionId: null,
        latestRevisionNumber: 0,
        persistedText: null
      },
      rechecked,
      rechecked.text,
      'server-issued-opaque-grant'
    )
    expect(exportAuthority).not.toBeNull()
    expect(
      session.save({
        ...uiState(),
        jobId: null,
        ui: { ...uiState().ui, selectedIssueId: null },
        exportAuthority
      })
    ).toBe(true)
    const saved = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )
    saved.workspace.result.text = '篡号测试'
    saved.workspace.result.blocks[0].text = '篡号测试'
    storage.setItem('text-verification-session', JSON.stringify(saved))

    const current = useVerificationWorkspace()
    current.loadResult(result)
    const currentResult = current.result.value
    const restored = useWorkspaceSession(storage, current).restore()

    expect(restored).toBeNull()
    expect(current.result.value).toBe(currentResult)
  })

  it('migrates valid version-4 state but drops unprovable retained authority', () => {
    const storage = new MemoryStorage()
    const rechecked = {
      ...result,
      document_id: '77777777-7777-4777-8777-777777777777',
      verification_run_id: '88888888-8888-4888-8888-888888888888',
      source_version:
        'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      execution_mode: 'synchronous' as const,
      issues: [],
      summary: {
        total: 0,
        by_type: {},
        by_severity: {},
        by_rule: {},
        by_layer: {}
      }
    }
    const workspace = useVerificationWorkspace()
    workspace.loadResult(rechecked)
    const session = useWorkspaceSession(storage, workspace)
    const exportAuthority = bindWorkspaceExportAuthority(
      {
        jobId: result.document_id,
        documentId: result.document_id,
        verificationRunId: result.verification_run_id,
        sourceVersion: result.source_version,
        fileType: 'docx',
        requiresOcrReconstruction: false,
        latestRevisionId: null,
        latestRevisionNumber: 0,
        persistedText: null
      },
      rechecked,
      rechecked.text,
      'server-issued-opaque-grant'
    )
    expect(exportAuthority).not.toBeNull()
    expect(
      session.save({
        ...uiState(),
        jobId: null,
        ui: { ...uiState().ui, selectedIssueId: null },
        exportAuthority
      })
    ).toBe(true)
    const saved = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )
    saved.version = 4
    delete saved.exportAuthority.recheckGrant
    storage.setItem('text-verification-session', JSON.stringify(saved))

    const restoredWorkspace = useVerificationWorkspace()
    const restored = useWorkspaceSession(
      storage,
      restoredWorkspace
    ).restore()

    expect(restored?.exportAuthority).toBeNull()
    expect(restoredWorkspace.result.value).toEqual(rechecked)
  })

  it('migrates version-5 client provenance without trusting its authority', () => {
    const storage = new MemoryStorage()
    const rechecked = {
      ...result,
      document_id: '77777777-7777-4777-8777-777777777777',
      verification_run_id: '88888888-8888-4888-8888-888888888888',
      source_version:
        'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      execution_mode: 'synchronous' as const,
      issues: [],
      summary: {
        total: 0,
        by_type: {},
        by_severity: {},
        by_rule: {},
        by_layer: {}
      }
    }
    const workspace = useVerificationWorkspace()
    workspace.loadResult(rechecked)
    const session = useWorkspaceSession(storage, workspace)
    const legacyAuthority = bindWorkspaceExportAuthority(
      {
        jobId: result.document_id,
        documentId: result.document_id,
        verificationRunId: result.verification_run_id,
        sourceVersion: result.source_version,
        fileType: 'docx',
        requiresOcrReconstruction: false,
        latestRevisionId: null,
        latestRevisionNumber: 0,
        persistedText: null
      },
      rechecked,
      rechecked.text,
      'server-issued-opaque-grant'
    )
    expect(legacyAuthority).not.toBeNull()
    expect(
      session.save({
        ...uiState(),
        jobId: null,
        ui: { ...uiState().ui, selectedIssueId: null },
        exportAuthority: legacyAuthority
      })
    ).toBe(true)
    const saved = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )
    saved.version = 5
    delete saved.exportAuthority.recheckGrant
    saved.exportAuthority.provenance = {
      resultDocumentId: rechecked.document_id,
      resultVerificationRunId: rechecked.verification_run_id,
      resultSourceVersion: rechecked.source_version,
      resultTextFingerprint: 'textfp-v1:12:7880a927d855313b',
      binding: 'textfp-v1:401:8695ff8d2837fdc9'
    }
    storage.setItem('text-verification-session', JSON.stringify(saved))

    const restoredWorkspace = useVerificationWorkspace()
    const restored = useWorkspaceSession(
      storage,
      restoredWorkspace
    ).restore()

    expect(restored?.exportAuthority).toBeNull()
    expect(restoredWorkspace.result.value).toEqual(rechecked)
  })

  it('migrates a valid version-3 session with no retained export authority', () => {
    const storage = new MemoryStorage()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(result)
    const session = useWorkspaceSession(storage, workspace)
    expect(session.save(uiState())).toBe(true)
    const saved = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )
    saved.version = 3
    delete saved.exportAuthority
    storage.setItem('text-verification-session', JSON.stringify(saved))

    const restoredWorkspace = useVerificationWorkspace()
    const restored = useWorkspaceSession(
      storage,
      restoredWorkspace
    ).restore()

    expect(restored).toEqual(uiState())
    expect(restored?.exportAuthority).toBeNull()
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

  it('rejects an async session whose job identity is foreign to the result', () => {
    const storage = new MemoryStorage()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(result)
    const session = useWorkspaceSession(storage, workspace)
    expect(session.save(uiState())).toBe(true)
    const saved = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )
    saved.jobId = '44444444-4444-4444-8444-444444444444'
    storage.setItem('text-verification-session', JSON.stringify(saved))

    const restoredWorkspace = useVerificationWorkspace()
    const restoredSession = useWorkspaceSession(storage, restoredWorkspace)

    expect(restoredSession.restore()).toBeNull()
    expect(restoredWorkspace.result.value).toBeNull()
  })

  it('rejects persisted revision gaps, duplicates, and persisted-after-draft order', () => {
    const storage = new MemoryStorage()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(result)
    workspace.acceptIssue(issue.issue_id)
    const firstDraft = workspace.currentRevision.value
    expect(firstDraft?.persistence_state).toBe('draft')
    expect(
      workspace.hydratePersistedRevision({
        ...firstDraft,
        revision_number: 1,
        created_at: '2026-09-03T04:00:00.000Z',
        persistence_state: 'persisted'
      })
    ).toBe(true)
    workspace.rejectIssue(issue.issue_id)
    const secondDraft = workspace.currentRevision.value
    expect(secondDraft?.persistence_state).toBe('draft')
    expect(
      workspace.hydratePersistedRevision({
        ...secondDraft,
        revision_number: 2,
        created_at: '2026-09-03T04:01:00.000Z',
        persistence_state: 'persisted'
      })
    ).toBe(true)
    const session = useWorkspaceSession(storage, workspace)
    expect(session.save(uiState())).toBe(true)
    const valid = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )

    for (const mutate of [
      (saved: Record<string, any>) => {
        saved.workspace.revisionChain[2].revision_number = 3
        saved.workspace.currentRevision.revision_number = 3
      },
      (saved: Record<string, any>) => {
        saved.workspace.revisionChain[2].revision_number = 1
        saved.workspace.currentRevision.revision_number = 1
      },
      (saved: Record<string, any>) => {
        saved.workspace.revisionChain[1].persistence_state = 'draft'
        saved.workspace.revisionChain[1].revision_number = null
      }
    ]) {
      const invalid = structuredClone(valid)
      mutate(invalid)
      storage.setItem(
        'text-verification-session',
        JSON.stringify(invalid)
      )
      const candidate = useVerificationWorkspace()
      expect(useWorkspaceSession(storage, candidate).restore()).toBeNull()
      expect(candidate.result.value).toBeNull()
    }
  })

  it('checks the raw UTF-8 payload boundary before JSON parsing', () => {
    expect(isWorkspaceSessionRawSizeAllowed('😀', 4)).toBe(true)
    expect(isWorkspaceSessionRawSizeAllowed('😀a', 4)).toBe(false)

    const storage = new MemoryStorage()
    const workspace = useVerificationWorkspace()
    const parse = vi.spyOn(JSON, 'parse')
    storage.setItem('text-verification-session', 'a'.repeat(5))

    expect(
      useWorkspaceSession(storage, workspace, { maxRawBytes: 4 }).restore()
    ).toBeNull()
    expect(parse).not.toHaveBeenCalled()
    parse.mockRestore()
  })

  it('rejects oversized nested block arrays before workspace cloning', () => {
    const storage = new MemoryStorage()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(result)
    const session = useWorkspaceSession(storage, workspace)
    expect(session.save(uiState())).toBe(true)
    const saved = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )
    saved.workspace.result.blocks = Array.from(
      { length: MAX_WORKSPACE_RESULT_BLOCKS + 1 },
      () => saved.workspace.result.blocks[0]
    )
    storage.setItem('text-verification-session', JSON.stringify(saved))
    const prepare = vi.spyOn(workspace, 'prepareWorkspaceRestore')

    expect(session.restore()).toBeNull()
    expect(prepare).not.toHaveBeenCalled()
  })

  it('allows the exact nested block boundary to reach canonical validation', () => {
    const storage = new MemoryStorage()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(result)
    const session = useWorkspaceSession(storage, workspace)
    expect(session.save(uiState())).toBe(true)
    const saved = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )
    saved.workspace.result.blocks = Array.from(
      { length: MAX_WORKSPACE_RESULT_BLOCKS },
      () => saved.workspace.result.blocks[0]
    )
    storage.setItem('text-verification-session', JSON.stringify(saved))
    const prepare = vi.spyOn(workspace, 'prepareWorkspaceRestore')

    expect(session.restore()).toBeNull()
    expect(prepare).toHaveBeenCalled()
  })

  it('rejects oversized revision text before workspace cloning', () => {
    const storage = new MemoryStorage()
    const workspace = useVerificationWorkspace()
    workspace.loadResult(result)
    const session = useWorkspaceSession(storage, workspace)
    expect(session.save(uiState())).toBe(true)
    const saved = JSON.parse(
      storage.getItem('text-verification-session') ?? '{}'
    )
    const oversized = 'a'.repeat(MAX_WORKSPACE_REVISION_CODE_POINTS + 1)
    saved.workspace.currentRevision.text = oversized
    saved.workspace.revisionChain[0].text = oversized
    storage.setItem('text-verification-session', JSON.stringify(saved))
    const prepare = vi.spyOn(workspace, 'prepareWorkspaceRestore')

    expect(session.restore()).toBeNull()
    expect(prepare).not.toHaveBeenCalled()
  })
})
