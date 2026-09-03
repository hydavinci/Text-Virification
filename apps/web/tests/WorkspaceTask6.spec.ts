import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { jobsApiKey, type JobsApi } from '../src/api/jobs'
import {
  verificationApiKey,
  type VerificationApi
} from '../src/api/verification'
import EditPreview from '../src/components/workspace/EditPreview.vue'
import { useWorkspaceSession } from '../src/composables/useWorkspaceSession'
import {
  createVerificationResultSnapshot,
  useVerificationWorkspace
} from '../src/composables/useVerificationWorkspace'
import type {
  DraftDocumentRevision,
  PersistedDocumentRevision,
  VerificationIssue,
  VerificationResult
} from '../src/types/verification'
import WorkspaceView from '../src/views/WorkspaceView.vue'
import scannedResult from './e2e/fixtures/scanned-result'

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
    exportJob: vi.fn(),
    ...overrides
  }
}

function seedSession(
  sessionResult: VerificationResult = result,
  sessionJobId: string | null = sessionResult.document_id
): void {
  const workspace = useVerificationWorkspace()
  workspace.loadResult(sessionResult)
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
      jobId: sessionJobId,
      exportAuthority: null
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

  it('does not synthesize compatibility file identity for canonical job results', () => {
    const {
      file_id: _fileId,
      file_ext: _fileExt,
      ...canonical
    } = result

    const snapshot = createVerificationResultSnapshot(canonical)

    expect(snapshot?.file_id).toBeNull()
    expect(snapshot?.file_ext).toBeNull()
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
    const exportJob = vi.fn()
    const wrapper = mountWorkspace(
      verificationApi({ persistRevision, exportJob })
    )
    await flushPromises()

    await wrapper.get('[data-action="accept-batch"]').trigger('click')
    await wrapper.get('[data-action="export-modified"]').trigger('click')
    await flushPromises()

    expect(persistRevision).toHaveBeenCalledTimes(1)
    expect(persistRevision.mock.calls[0]?.[0]).toBe(
      result.document_id
    )
    expect(persistRevision.mock.calls[0]?.[1]).toMatchObject({
      revision_number: null,
      persistence_state: 'draft',
      kind: 'review',
      text: '账号测试'
    })
    expect(exportJob).toHaveBeenCalledWith(
      result.document_id,
      'docx_reconstruction',
      persistRevision.mock.results[0]?.value
        ? expect.any(String)
        : null,
      true,
      expect.any(Function)
    )
    expect(wrapper.text()).toContain('重建 DOCX')
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
    const exportJob = vi.fn()
    const wrapper = mountWorkspace(
      verificationApi({ persistRevision, exportJob })
    )
    await flushPromises()

    wrapper.getComponent(EditPreview).vm.$emit('save', '手工修订')
    await flushPromises()
    await wrapper.get('[data-action="export-modified"]').trigger('click')

    expect(persistRevision).not.toHaveBeenCalled()
    expect(exportJob).not.toHaveBeenCalled()
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

  it('uses job-owned original-format export for an ordinary async DOCX', async () => {
    const docxResult: VerificationResult = {
      ...result,
      filename: 'sample.docx',
      source_name: 'sample.docx',
      file_type: 'docx',
      parser_name: 'docx',
      blocks: result.blocks.map((block) => ({ ...block, page: null, bbox: null }))
    }
    seedSession(docxResult)
    const exportOriginal = vi.fn()
    const exportJob = vi.fn()
    const wrapper = mountWorkspace(
      verificationApi({ exportOriginal, exportJob })
    )
    await flushPromises()

    await wrapper.get('[data-action="export-modified"]').trigger('click')
    await flushPromises()

    expect(exportOriginal).not.toHaveBeenCalled()
    expect(exportJob).toHaveBeenCalledWith(
      docxResult.document_id,
      'original_format',
      null,
      true,
      expect.any(Function)
    )
  })

  it.each([
    ['docx', 'original_format'],
    ['doc', 'original_format'],
    ['pdf', 'docx_reconstruction'],
    ['txt', 'original_format'],
    ['rtf', 'original_format'],
    ['md', 'original_format'],
    ['csv', 'original_format']
  ] as const)(
    'retains %s job export authority after manual text recheck',
    async (fileType, expectedFormat) => {
      const origin: VerificationResult = {
        ...result,
        filename: `source.${fileType}`,
        source_name: `source.${fileType}`,
        file_type: fileType,
        issues: [],
        summary: {
          total: 0,
          by_type: {},
          by_severity: {},
          by_rule: {},
          by_layer: {}
        }
      }
      const checked: VerificationResult = {
        ...origin,
        filename: 'direct.txt',
        source_name: 'direct.txt',
        file_type: 'txt',
        text: '手工修改文本',
        blocks: [
          {
            ...origin.blocks[0],
            text: '手工修改文本',
            global_end: 6,
            block_end: 6
          }
        ],
        document_id: '77777777-7777-4777-8777-777777777777',
        verification_run_id: '88888888-8888-4888-8888-888888888888',
        source_version:
          'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
        execution_mode: 'synchronous',
        stats: {
          ...origin.stats,
          char_count: 6,
          char_count_no_space: 6,
          primary_count: 6
        }
      }
      seedSession(origin)
      const persistRevision = vi.fn(async (_jobId, draft) => ({
        ...draft,
        revision_number: 1,
        created_at: '2026-09-03T06:00:00.000Z',
        persistence_state: 'persisted' as const
      }))
      const exportJob = vi.fn()
      const wrapper = mountWorkspace(
        verificationApi({
          analyzeText: vi.fn().mockResolvedValue(checked),
          persistRevision,
          exportJob
        })
      )
      await flushPromises()
      const editor = wrapper.getComponent(EditPreview)
      await editor.get('[data-action="start-edit"]').trigger('click')
      await editor.get('[data-edit-input]').setValue('手工修改文本')
      await editor.get('[data-action="save-edit"]').trigger('click')

      await wrapper.get('[data-action="recheck"]').trigger('click')
      await flushPromises()

      const current = (
        wrapper.vm as unknown as {
          $: {
            setupState: {
              verificationWorkspace: ReturnType<
                typeof useVerificationWorkspace
              >
            }
          }
        }
      ).$.setupState.verificationWorkspace.result.value
      expect(current).toMatchObject({
        document_id: checked.document_id,
        verification_run_id: checked.verification_run_id,
        source_version: checked.source_version,
        text: '手工修改文本'
      })

      await wrapper.get('[data-action="export-modified"]').trigger('click')
      await flushPromises()

      expect(persistRevision).toHaveBeenCalledWith(
        origin.document_id,
        expect.objectContaining({
          document_id: origin.document_id,
          verification_run_id: origin.verification_run_id,
          source_version: origin.source_version,
          parent_revision_id: null,
          kind: 'manual',
          text: '手工修改文本'
        })
      )
      const persistedDraft = persistRevision.mock.calls[0]?.[1]
      expect(exportJob).toHaveBeenCalledWith(
        origin.document_id,
        expectedFormat,
        persistedDraft?.revision_id,
        true,
        expect.any(Function)
      )
    }
  )

  it('rejects an unrelated synchronous result instead of binding retained job authority', async () => {
    const origin: VerificationResult = {
      ...result,
      filename: 'source.docx',
      source_name: 'source.docx',
      file_type: 'docx',
      issues: [],
      summary: {
        total: 0,
        by_type: {},
        by_severity: {},
        by_rule: {},
        by_layer: {}
      }
    }
    const unrelated: VerificationResult = {
      ...origin,
      filename: 'direct.txt',
      source_name: 'direct.txt',
      file_type: 'txt',
      text: '无关检查结果',
      blocks: [
        {
          ...origin.blocks[0],
          text: '无关检查结果',
          global_end: 6,
          block_end: 6
        }
      ],
      document_id: '77777777-7777-4777-8777-777777777777',
      verification_run_id: '88888888-8888-4888-8888-888888888888',
      source_version:
        'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      execution_mode: 'synchronous',
      stats: {
        ...origin.stats,
        char_count: 6,
        char_count_no_space: 6,
        primary_count: 6
      }
    }
    seedSession(origin)
    const persistRevision = vi.fn()
    const exportJob = vi.fn()
    const wrapper = mountWorkspace(
      verificationApi({
        analyzeText: vi.fn().mockResolvedValue(unrelated),
        persistRevision,
        exportJob
      })
    )
    await flushPromises()
    const editor = wrapper.getComponent(EditPreview)
    await editor.get('[data-action="start-edit"]').trigger('click')
    await editor.get('[data-edit-input]').setValue('手工修改文本')
    await editor.get('[data-action="save-edit"]').trigger('click')

    await wrapper.get('[data-action="recheck"]').trigger('click')
    await flushPromises()

    const workspace = (
      wrapper.vm as unknown as {
        $: {
          setupState: {
            verificationWorkspace: ReturnType<
              typeof useVerificationWorkspace
            >
          }
        }
      }
    ).$.setupState.verificationWorkspace
    expect(workspace.result.value).toMatchObject({
      document_id: origin.document_id,
      verification_run_id: origin.verification_run_id,
      source_version: origin.source_version
    })
    expect(wrapper.get('[data-review-execution-error]').text()).toContain(
      '重新检查结果'
    )
    expect(persistRevision).not.toHaveBeenCalled()
    expect(exportJob).not.toHaveBeenCalled()
  })

  it('keeps text-based async PDF export in the original PDF format', async () => {
    const rawTextPdf = structuredClone(scannedResult) as any
    rawTextPdf.metadata.pdf.pages[0].kind = 'text'
    rawTextPdf.metadata.pdf.pages[0].ocr_required = false
    rawTextPdf.metadata.pdf.warnings = []
    rawTextPdf.metadata.pdf.ocr_requirement = null
    rawTextPdf.ocr_requirement = null
    const textPdfResult = createVerificationResultSnapshot(rawTextPdf)
    if (textPdfResult === null) {
      throw new Error('Expected a canonical text PDF result.')
    }
    seedSession(textPdfResult)
    const exportJob = vi.fn()
    const wrapper = mountWorkspace(verificationApi({ exportJob }))
    await flushPromises()

    await wrapper.get('[data-action="export-modified"]').trigger('click')
    await flushPromises()

    expect(exportJob).toHaveBeenCalledWith(
      textPdfResult.document_id,
      'original_format',
      null,
      true,
      expect.any(Function)
    )
    expect(wrapper.text()).toContain('保留 PDF 格式')
  })

  it('invalidates a pending export when reset replaces the workspace', async () => {
    seedSession()
    let resolvePersist: (value: PersistedDocumentRevision) => void = () => {}
    const persistRevision = vi.fn(
      (
        _jobId: string,
        draft: DraftDocumentRevision
      ): Promise<PersistedDocumentRevision> =>
        new Promise<PersistedDocumentRevision>((resolve) => {
          resolvePersist = resolve
        })
    )
    const exportJob = vi.fn()
    const wrapper = mountWorkspace(
      verificationApi({ persistRevision, exportJob })
    )
    await flushPromises()
    await wrapper.get('[data-action="accept-batch"]').trigger('click')
    await wrapper.get('[data-action="export-modified"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-reset-workspace]').trigger('click')
    const pendingDraft = persistRevision.mock.calls[0]?.[1]
    if (pendingDraft === undefined) {
      throw new Error('Expected a pending revision draft.')
    }
    resolvePersist({
      ...pendingDraft,
      revision_number: 1,
      created_at: '2026-09-03T04:00:00.000Z',
      persistence_state: 'persisted'
    })
    await flushPromises()

    expect(exportJob).not.toHaveBeenCalled()
    expect(wrapper.find('[data-export-error]').exists()).toBe(false)
    expect(wrapper.find('.toast').exists()).toBe(false)
  })

  it('locks document mutations while revision persistence is pending', async () => {
    seedSession()
    const persistRevision = vi.fn(
      (): Promise<PersistedDocumentRevision> =>
        new Promise<PersistedDocumentRevision>(() => undefined)
    )
    const wrapper = mountWorkspace(
      verificationApi({ persistRevision, exportJob: vi.fn() })
    )
    await flushPromises()
    await wrapper.get('[data-action="accept-batch"]').trigger('click')
    await wrapper.get('[data-action="export-modified"]').trigger('click')
    await flushPromises()

    expect(
      wrapper.get<HTMLButtonElement>('[data-action="start-edit"]').element
        .disabled
    ).toBe(true)
    expect(
      wrapper.get<HTMLButtonElement>('[data-action="toggle-search-replace"]')
        .element.disabled
    ).toBe(true)
    expect(
      wrapper.get<HTMLInputElement>('[data-track-changes]').element.disabled
    ).toBe(true)
    expect(
      wrapper.get<HTMLButtonElement>('.issue-actions .accept').element.disabled
    ).toBe(true)
  })

  it('keeps export failures assertive until dismissed', async () => {
    seedSession()
    const wrapper = mountWorkspace(
      verificationApi({
        exportJob: vi.fn().mockRejectedValue(new Error('导出服务失败'))
      })
    )
    await flushPromises()

    await wrapper.get('[data-action="export-modified"]').trigger('click')
    await flushPromises()

    const alert = wrapper.get('[data-export-error]')
    expect(alert.attributes('role')).toBe('alert')
    expect(alert.attributes('aria-live')).toBe('assertive')
    expect(alert.text()).toContain('导出服务失败')
    expect(
      wrapper.get<HTMLButtonElement>('[data-action="export-modified"]').element
        .disabled
    ).toBe(false)
    await flushPromises()
    expect(wrapper.find('[data-export-error]').exists()).toBe(true)

    await wrapper.get('[data-dismiss-export-error]').trigger('click')
    expect(wrapper.find('[data-export-error]').exists()).toBe(false)
  })

  it('supersedes an old export alert when synchronous modified export starts and succeeds', async () => {
    const synchronousResult: VerificationResult = {
      ...result,
      filename: 'direct.txt',
      source_name: 'direct.txt',
      file_type: 'txt',
      execution_mode: 'synchronous',
      file_id: null,
      file_ext: null
    }
    seedSession(synchronousResult, null)
    const createObjectURL = vi.fn(() => 'blob:modified')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: createObjectURL
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: revokeObjectURL
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const wrapper = mountWorkspace(
      verificationApi({
        exportReport: vi.fn().mockRejectedValue(new Error('旧导出失败'))
      })
    )
    await flushPromises()

    await wrapper.get('[data-action="export-report"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-export-error]').text()).toContain('旧导出失败')

    await wrapper.get('[data-action="export-modified"]').trigger('click')

    expect(wrapper.find('[data-export-error]').exists()).toBe(false)
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:modified')
  })

  it('invalidates the export guard when the workspace unmounts', async () => {
    seedSession()
    let releaseExport: () => void = () => {}
    let downloadCount = 0
    const exportJob = vi.fn(
      async (
        _jobId,
        _format,
        _revisionId,
        _trackChanges,
        isCurrent: () => boolean
      ) => {
        await new Promise<void>((resolve) => {
          releaseExport = resolve
        })
        if (isCurrent()) {
          downloadCount += 1
        }
      }
    )
    const wrapper = mountWorkspace(verificationApi({ exportJob }))
    await flushPromises()

    await wrapper.get('[data-action="export-modified"]').trigger('click')
    await flushPromises()
    wrapper.unmount()
    releaseExport()
    await flushPromises()

    expect(downloadCount).toBe(0)
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
