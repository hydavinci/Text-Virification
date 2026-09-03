import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { jobsApiKey, type JobsApi } from '../src/api/jobs'
import {
  verificationApiKey,
  type VerificationApi
} from '../src/api/verification'
import EditPreview from '../src/components/workspace/EditPreview.vue'
import { useWorkspaceSession } from '../src/composables/useWorkspaceSession'
import { useVerificationWorkspace } from '../src/composables/useVerificationWorkspace'
import type {
  VerificationIssue,
  VerificationResult
} from '../src/types/verification'
import WorkspaceView from '../src/views/WorkspaceView.vue'

const themeValues = new Map<string, string>()
const themeStorage: Storage = {
  get length() {
    return themeValues.size
  },
  clear() {
    themeValues.clear()
  },
  getItem(key) {
    return themeValues.get(key) ?? null
  },
  key(index) {
    return [...themeValues.keys()][index] ?? null
  },
  removeItem(key) {
    themeValues.delete(key)
  },
  setItem(key, value) {
    themeValues.set(key, value)
  }
}
Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: themeStorage
})
Object.defineProperty(window, 'localStorage', {
  configurable: true,
  value: themeStorage
})
const browserSessionStorage = window.sessionStorage

const issue: VerificationIssue = {
  issue_id: '33333333-3333-4333-8333-333333333333',
  document_id: '11111111-1111-4111-8111-111111111111',
  verification_run_id: '22222222-2222-4222-8222-222222222222',
  block_id: 'p-0',
  page: 1,
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
  document_id: issue.document_id,
  verification_run_id: issue.verification_run_id,
  source_version:
    'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
  execution_mode: 'asynchronous',
  analysis_mode: 'local_only',
  dictionary_versions: {},
  degradation: { is_degraded: false, reasons: [] },
  scenario: 'technical'
}

function jobsApi(): JobsApi {
  return {
    createJob: vi.fn(),
    getResult: vi.fn(),
    subscribe: vi.fn()
  }
}

function verificationApi(
  overrides: Partial<VerificationApi> = {}
): VerificationApi {
  return {
    analyzeFile: vi.fn(),
    analyzeText: vi.fn(),
    exportReport: vi.fn(),
    exportOriginal: vi.fn(),
    persistRevision: vi.fn(),
    exportReconstruction: vi.fn(),
    ...overrides
  }
}

function seedSession(): void {
  const workspace = useVerificationWorkspace()
  workspace.loadResult(result)
  const session = useWorkspaceSession(window.sessionStorage, workspace)
  expect(
    session.save({
      options: {
        scenario: 'technical',
        enableSecurity: true,
        enableSensitive: false,
        enableAdExtreme: true,
        glossary: [{ original: 'AI', standard: '人工智能' }],
        bannedWords: ['最好']
      },
      filters: { layer: 'all', severity: 'all' },
      viewMode: 'continuous',
      ui: {
        settingsTab: 'terms',
        resultTab: 'issues',
        showFindReplace: false,
        trackChanges: true,
        selectedIssueId: null
      },
      jobId: '44444444-4444-4444-8444-444444444444'
    })
  ).toBe(true)
}

function mountWorkspace(api: VerificationApi) {
  return mount(WorkspaceView, {
    global: {
      provide: {
        [jobsApiKey as symbol]: jobsApi(),
        [verificationApiKey as symbol]: api
      }
    }
  })
}

describe('WorkspaceView Task 6 integration', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      value: browserSessionStorage
    })
    window.sessionStorage.clear()
    window.localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('persists the draft chain before revision-keyed reconstruction export', async () => {
    seedSession()
    expect(
      window.sessionStorage.getItem('text-verification-session')
    ).not.toBeNull()
    const probeWorkspace = useVerificationWorkspace()
    expect(
      useWorkspaceSession(window.sessionStorage, probeWorkspace).restore()
    ).not.toBeNull()
    const persistRevision = vi.fn(async (_jobId, draft) => ({
      ...draft,
      revision_number: 1,
      created_at: '2026-09-03T04:00:00.000Z',
      persistence_state: 'persisted' as const
    }))
    const exportReconstruction = vi.fn()
    const wrapper = mountWorkspace(
      verificationApi({ persistRevision, exportReconstruction })
    )
    await flushPromises()

    await wrapper.get('[data-action="accept-batch"]').trigger('click')
    await wrapper.get('[data-action="export-modified"]').trigger('click')
    await flushPromises()

    expect(persistRevision).toHaveBeenCalledTimes(1)
    expect(persistRevision.mock.calls[0]?.[0]).toBe(
      '44444444-4444-4444-8444-444444444444'
    )
    expect(persistRevision.mock.calls[0]?.[1]).toMatchObject({
      revision_number: null,
      persistence_state: 'draft',
      kind: 'review',
      text: '账号测试'
    })
    expect(exportReconstruction).toHaveBeenCalledWith(
      '44444444-4444-4444-8444-444444444444',
      persistRevision.mock.results[0]?.value
        ? expect.any(String)
        : null
    )
    expect(
      (
        wrapper.vm as unknown as {
          verificationWorkspace: ReturnType<typeof useVerificationWorkspace>
        }
      ).verificationWorkspace.currentRevision.value
    ).toMatchObject({
      revision_number: 1,
      persistence_state: 'persisted'
    })
  })

  it('blocks export after free editing until re-verification', async () => {
    seedSession()
    const persistRevision = vi.fn()
    const exportReconstruction = vi.fn()
    const wrapper = mountWorkspace(
      verificationApi({ persistRevision, exportReconstruction })
    )
    await flushPromises()

    wrapper.getComponent(EditPreview).vm.$emit('save', '手工修订')
    await flushPromises()
    await wrapper.get('[data-action="export-modified"]').trigger('click')

    expect(persistRevision).not.toHaveBeenCalled()
    expect(exportReconstruction).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('重新检查后再导出')
  })

  it('shows an assertive session warning when browser storage writes fail', async () => {
    seedSession()
    const saved = window.sessionStorage.getItem('text-verification-session')
    const failingStorage: Storage = {
      get length() {
        return saved === null ? 0 : 1
      },
      clear() {},
      getItem(key) {
        return key === 'text-verification-session' ? saved : null
      },
      key(index) {
        return index === 0 && saved !== null
          ? 'text-verification-session'
          : null
      },
      removeItem() {},
      setItem() {
        throw new DOMException('quota', 'QuotaExceededError')
      }
    }
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      value: failingStorage
    })
    const wrapper = mountWorkspace(verificationApi())
    await flushPromises()

    await wrapper.get('[data-action="accept-batch"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-session-warning]').attributes('role')).toBe(
      'alert'
    )
    expect(wrapper.get('[data-session-warning]').text()).toContain('内存')
  })

  it('persists and applies theme while keeping a polite status region mounted', async () => {
    const wrapper = mountWorkspace(verificationApi())

    expect(wrapper.get('[data-workspace-status]').attributes('aria-live')).toBe(
      'polite'
    )
    await wrapper.get('[data-toggle-theme]').trigger('click')

    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(window.localStorage.getItem('text-verification-theme')).toBe('dark')
  })

  it('persists directly required view, selection, tab, and export UI state', async () => {
    seedSession()
    const wrapper = mountWorkspace(verificationApi())
    await flushPromises()

    await wrapper.get('[aria-pressed="false"].btn.small').trigger('click')
    await wrapper.get('.compact-tabs button:nth-child(2)').trigger('click')
    await wrapper
      .get(`[data-issue-id="${issue.issue_id}"][data-issue-role="source"]`)
      .trigger('click')
    await wrapper.get<HTMLInputElement>('[data-track-changes]').setValue(false)
    await flushPromises()

    const saved = JSON.parse(
      window.sessionStorage.getItem('text-verification-session') ?? '{}'
    )
    expect(saved.viewMode).toBe('sentence')
    expect(saved.ui).toMatchObject({
      resultTab: 'summary',
      trackChanges: false,
      selectedIssueId: issue.issue_id
    })
  })
})
