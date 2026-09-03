import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { jobsApiKey, type JobsApi } from '../src/api/jobs'
import { verificationApiKey } from '../src/api/verification'
import SourceInputPanel from '../src/components/workspace/SourceInputPanel.vue'
import DocumentViewer from '../src/components/workspace/DocumentViewer.vue'
import EditPreview from '../src/components/workspace/EditPreview.vue'
import IssueList from '../src/components/workspace/IssueList.vue'
import ReviewActions from '../src/components/workspace/ReviewActions.vue'
import SearchReplacePanel from '../src/components/workspace/SearchReplacePanel.vue'
import TerminologyEditor from '../src/components/workspace/TerminologyEditor.vue'
import VerificationSettings from '../src/components/workspace/VerificationSettings.vue'
import type {
  AnalyzeOptions,
  VerificationIssue,
  VerificationResult
} from '../src/types/verification'
import WorkspaceView from '../src/views/WorkspaceView.vue'

function buildJobRead(overrides: Partial<Awaited<ReturnType<JobsApi['createJob']>>> = {}) {
  return {
    job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
    source_name: 'sample.txt',
    file_type: 'txt' as const,
    size_bytes: 6,
    status: 'queued' as const,
    progress: 0,
    error_code: null,
    error_message: null,
    created_at: '2026-08-14T00:00:00Z',
    expires_at: '2026-08-15T00:00:00Z',
    ...overrides
  }
}

async function selectFile(wrapper: ReturnType<typeof mount>, file: File) {
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', {
    configurable: true,
    value: [file]
  })
  await input.trigger('change')
}

async function emitUpload(wrapper: ReturnType<typeof mount>, file: File) {
  wrapper.getComponent(SourceInputPanel).vm.$emit('submit-file', file)
  await flushPromises()
}

function createDeferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((innerResolve, innerReject) => {
    resolve = innerResolve
    reject = innerReject
  })

  return { promise, resolve, reject }
}

function buildWorkspaceIssue(
  overrides: Partial<VerificationIssue> = {}
): VerificationIssue {
  return {
    issue_id: '33333333-3333-3333-3333-333333333333',
    document_id: '11111111-1111-1111-1111-111111111111',
    verification_run_id: '22222222-2222-2222-2222-222222222222',
    block_id: 'p-0',
    page: null,
    start: 0,
    end: 3,
    block_start: 0,
    block_end: 3,
    type: 'typo',
    severity: 'warning',
    original: '甲乙丙',
    suggestion: '修改',
    alternatives: ['备选'],
    layer: 'character',
    message: '疑似错别字',
    description: '疑似错别字',
    rule_id: 'cn_typo',
    rule_version: '1',
    source: 'test',
    source_version: '1',
    confidence: 0.8,
    auto_fixable: true,
    context: '甲乙丙丁',
    position: 99,
    end_position: 100,
    review: null,
    review_reason: null,
    ...overrides
  }
}

function buildWorkspaceResult(
  issues: VerificationIssue[],
  text = '甲乙丙丁',
  overrides: Partial<VerificationResult> = {}
): VerificationResult {
  const length = Array.from(text).length
  return {
    success: true,
    filename: 'direct.txt',
    source_name: 'direct.txt',
    file_type: 'txt',
    text,
    blocks: [
      {
        block_id: 'p-0',
        kind: 'paragraph',
        text,
        global_start: 0,
        global_end: length,
        block_start: 0,
        block_end: length,
        page: null,
        paragraph_index: 0,
        table_index: null,
        row_index: null,
        cell_index: null,
        bbox: null,
        parent_id: null,
        style: {},
        source_locator: { paragraph_index: 0 }
      }
    ],
    parser_name: 'compatibility-flat-text',
    parser_version: '1',
    stats: {
      char_count: length,
      char_count_no_space: length,
      line_count: 1,
      paragraph_count: 1,
      language: 'zh',
      primary_count: length,
      primary_label: '总字数'
    },
    issues,
    summary: {
      total: issues.length,
      by_type: { typo: issues.length },
      by_severity: { warning: issues.length },
      by_rule: { cn_typo: issues.length },
      by_layer: { character: issues.length }
    },
    file_id: null,
    file_ext: null,
    document_id: '11111111-1111-1111-1111-111111111111',
    verification_run_id: '22222222-2222-2222-2222-222222222222',
    source_version: 'sha256:source',
    execution_mode: 'synchronous',
    analysis_mode: 'local_only',
    dictionary_versions: {},
    degradation: { is_degraded: false, reasons: [] },
    scenario: 'general',
    ...overrides
  }
}

function buildConflictIssues(
  kind: 'crossing' | 'nested' | 'identical'
): VerificationIssue[] {
  const ranges = {
    crossing: [
      { start: 0, end: 3, original: 'abc' },
      { start: 2, end: 5, original: 'cde' }
    ],
    nested: [
      { start: 0, end: 5, original: 'abcde' },
      { start: 1, end: 4, original: 'bcd' }
    ],
    identical: [
      { start: 1, end: 4, original: 'bcd' },
      { start: 1, end: 4, original: 'bcd' }
    ]
  }[kind]
  return ranges.map((range, index) =>
    buildWorkspaceIssue({
      issue_id:
        index === 0
          ? '33333333-3333-3333-3333-333333333333'
          : '44444444-4444-4444-4444-444444444444',
      start: range.start,
      end: range.end,
      block_start: range.start,
      block_end: range.end,
      original: range.original,
      suggestion: index === 0 ? 'X' : 'Y',
      context: 'abcdef'
    })
  )
}

function canonicalWorkspace(wrapper: ReturnType<typeof mount>) {
  return (
    wrapper.vm as unknown as {
      verificationWorkspace: {
        currentRevision: { readonly value: unknown }
        modifiedText: { readonly value: string }
        issueStates: {
          readonly value: Readonly<Record<string, string>>
        }
        selectedSuggestions: {
          readonly value: Readonly<Record<string, string | null>>
        }
        hasReplacementConflicts: { readonly value: boolean }
        canUndoLastBatch: { readonly value: boolean }
        requiresReverification: { readonly value: boolean }
        visibleIssues: { readonly value: readonly VerificationIssue[] }
      }
    }
  ).verificationWorkspace
}

describe('WorkspaceView', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('connects source and issue-list selection through stable issue ids', async () => {
    const first = buildWorkspaceIssue()
    const second = buildWorkspaceIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 2,
      end: 4,
      block_start: 2,
      block_end: 4,
      original: '丙丁',
      severity: 'error',
      layer: 'security'
    })
    const analyzeText = vi
      .fn()
      .mockResolvedValue(buildWorkspaceResult([first, second]))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn()
    })
    const wrapper = mount(WorkspaceView, {
      attachTo: document.body,
      global: {
        provide: {
          [jobsApiKey as symbol]: {
            createJob: vi.fn(),
            subscribe: vi.fn(() => vi.fn())
          },
          [verificationApiKey as symbol]: {
            analyzeFile: vi.fn(),
            analyzeText,
            exportReport: vi.fn(),
            exportOriginal: vi.fn()
          }
        }
      }
    })

    const input = wrapper.getComponent(SourceInputPanel)
    input.vm.$emit('submit-text', '甲乙丙丁')
    await flushPromises()

    const viewer = wrapper.getComponent(DocumentViewer)
    const list = wrapper.getComponent(IssueList)
    await viewer.get(`[data-issue-id="${first.issue_id}"]`).trigger('click')
    expect(
      list.get(`[data-issue-id="${first.issue_id}"]`).attributes('aria-current')
    ).toBe('true')

    await list.get(`[data-issue-id="${second.issue_id}"]`).trigger('click')
    expect(
      viewer
        .get(`[data-issue-id="${second.issue_id}"]`)
        .attributes('aria-current')
    ).toBe('true')

    await list.get('[aria-label="问题级别"]').setValue('warning')
    expect(
      wrapper
        .getComponent(IssueList)
        .get(`[data-issue-id="${first.issue_id}"]`)
        .attributes('aria-current')
    ).toBe('true')
    wrapper.unmount()
  })

  it('submits direct text with the complete settings and terminology snapshot', async () => {
    const analyzeText = vi.fn().mockRejectedValue(new Error('stop after contract check'))
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: {
            createJob: vi.fn(),
            subscribe: vi.fn(() => vi.fn())
          },
          [verificationApiKey as symbol]: {
            analyzeFile: vi.fn(),
            analyzeText,
            exportReport: vi.fn(),
            exportOriginal: vi.fn()
          }
        }
      }
    })

    await wrapper.getComponent(VerificationSettings).get('[data-scenario="academic"]').trigger('click')
    const settings = wrapper.getComponent(VerificationSettings)
    await settings.get('#enable-security').setValue(false)
    await settings.get('#enable-sensitive').setValue(false)
    await settings.get('#enable-ad-extreme').setValue(true)

    await wrapper.get('.side-tabs button:nth-child(2)').trigger('click')
    const glossary = wrapper.getComponent(TerminologyEditor)
    await glossary.get('#term-original').setValue('AI')
    await glossary.get('#term-standard').setValue('人工智能')
    await glossary.get('[data-action="add-glossary"]').trigger('click')

    await wrapper.get('.side-tabs button:nth-child(3)').trigger('click')
    const banned = wrapper.getComponent(TerminologyEditor)
    await banned.get('#banned-word').setValue('最好')
    await banned.get('[data-action="add-banned"]').trigger('click')

    const input = wrapper.getComponent(SourceInputPanel)
    await input.get('[data-mode="text"]').trigger('click')
    await input.get('textarea').setValue('检查文本')
    await input.get('textarea').trigger('keydown', {
      key: 'Enter',
      ctrlKey: true
    })
    await flushPromises()

    expect(analyzeText).toHaveBeenCalledWith('检查文本', {
      scenario: 'academic',
      enableSecurity: false,
      enableSensitive: false,
      enableAdExtreme: true,
      glossary: [{ original: 'AI', standard: '人工智能' }],
      bannedWords: ['最好']
    } satisfies AnalyzeOptions)
  })

  it('synchronously ignores a second text submission while analysis is pending', async () => {
    const pending = createDeferred<VerificationResult>()
    const analyzeText = vi.fn().mockReturnValue(pending.promise)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: {
            createJob: vi.fn(),
            subscribe: vi.fn(() => vi.fn())
          },
          [verificationApiKey as symbol]: {
            analyzeFile: vi.fn(),
            analyzeText,
            exportReport: vi.fn(),
            exportOriginal: vi.fn()
          }
        }
      }
    })
    const input = wrapper.getComponent(SourceInputPanel)

    input.vm.$emit('submit-text', '检查文本')
    input.vm.$emit('submit-text', '第二次')
    await flushPromises()

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(analyzeText).toHaveBeenCalledTimes(1)
    expect(analyzeText).toHaveBeenCalledWith(
      '检查文本',
      expect.any(Object)
    )

    pending.reject(new Error('finish'))
    await flushPromises()
  })

  it('synchronously ignores a second file submission while direct analysis is pending', async () => {
    const pending = createDeferred<VerificationResult>()
    const analyzeFile = vi.fn().mockReturnValue(pending.promise)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: {
            createJob: vi.fn(),
            subscribe: vi.fn(() => vi.fn())
          },
          [verificationApiKey as symbol]: {
            analyzeFile,
            analyzeText: vi.fn(),
            exportReport: vi.fn(),
            exportOriginal: vi.fn()
          }
        }
      }
    })
    const first = new File(['first'], 'first.txt')
    const second = new File(['second'], 'second.txt')
    const input = wrapper.getComponent(SourceInputPanel)

    input.vm.$emit('submit-file', first)
    input.vm.$emit('submit-file', second)
    await flushPromises()

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(analyzeFile).toHaveBeenCalledTimes(1)
    expect(analyzeFile).toHaveBeenCalledWith(first, expect.any(Object))

    pending.reject(new Error('finish'))
    await flushPromises()
  })

  it('uploads an allowed file and displays durable progress', async () => {
    const createJob = vi.fn().mockResolvedValue(buildJobRead())
    const subscribe = vi.fn((_jobId, onEvent) => {
      onEvent({
        sequence: 2,
        status: 'parsing',
        progress: 25,
        message: '开始解析',
        created_at: '2026-08-14T00:01:00Z'
      })
      onEvent({
        sequence: 3,
        status: 'completed',
        progress: 100,
        message: '处理完成',
        created_at: '2026-08-14T00:02:00Z'
      })
      return vi.fn()
    })
    const wrapper = mount(WorkspaceView, {
      global: { provide: { [jobsApiKey as symbol]: { createJob, subscribe } } }
    })
    const file = new File(['检查'], 'sample.txt', { type: 'text/plain' })

    await selectFile(wrapper, file)
    await flushPromises()

    expect(createJob).toHaveBeenCalledWith(file)
    expect(wrapper.text()).toContain('sample.txt')
    expect(wrapper.text()).toContain('100%')
    expect(wrapper.text()).toContain('处理完成')
    expect(wrapper.text()).toContain('completed')
    expect(wrapper.get('progress').attributes('aria-label')).toBe('Job progress')
    expect(wrapper.get('[role="status"]').attributes('aria-live')).toBe('polite')
  })

  it('accepts files that are exactly 25 MiB', async () => {
    const createJob = vi.fn().mockResolvedValue(
      buildJobRead({
        source_name: 'limit.txt',
        size_bytes: 25 * 1024 * 1024
      })
    )
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe: vi.fn(() => vi.fn()) }
        }
      }
    })
    const exactLimit = new File([new Uint8Array(25 * 1024 * 1024)], 'limit.txt', {
      type: 'text/plain'
    })

    await selectFile(wrapper, exactLimit)
    await flushPromises()

    expect(createJob).toHaveBeenCalledWith(exactLimit)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('rejects unsupported extensions before upload', async () => {
    const createJob = vi.fn()
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe: vi.fn(() => vi.fn()) }
        }
      }
    })

    await selectFile(wrapper, new File(['MZ'], 'sample.exe'))

    expect(createJob).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('DOCX、PDF 或 TXT')
  })

  it('rejects files larger than 25 MiB before upload', async () => {
    const createJob = vi.fn()
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe: vi.fn(() => vi.fn()) }
        }
      }
    })
    const oversized = new File([new Uint8Array(25 * 1024 * 1024 + 1)], 'large.txt', {
      type: 'text/plain'
    })

    await selectFile(wrapper, oversized)

    expect(createJob).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('25 MiB')
  })

  it('closes the prior subscription before a new upload and on unmount', async () => {
    const createJob = vi
      .fn()
      .mockResolvedValueOnce(buildJobRead({ job_id: 'job-1' }))
      .mockResolvedValueOnce(
        buildJobRead({
          job_id: 'job-2',
          source_name: 'second.pdf',
          file_type: 'pdf'
        })
      )
    const firstClose = vi.fn()
    const secondClose = vi.fn()
    const subscribe = vi
      .fn()
      .mockImplementationOnce(() => firstClose)
      .mockImplementationOnce(() => secondClose)
    const wrapper = mount(WorkspaceView, {
      global: { provide: { [jobsApiKey as symbol]: { createJob, subscribe } } }
    })

    await selectFile(wrapper, new File(['first'], 'first.txt', { type: 'text/plain' }))
    await flushPromises()
    await selectFile(wrapper, new File(['second'], 'second.pdf', { type: 'application/pdf' }))
    await flushPromises()

    expect(firstClose).toHaveBeenCalledTimes(1)

    wrapper.unmount()

    expect(secondClose).toHaveBeenCalledTimes(1)
  })

  it('retains the terminal state when a late subscription error arrives', async () => {
    const createJob = vi.fn().mockResolvedValue(buildJobRead())
    const subscribe = vi.fn((_jobId, onEvent, onError) => {
      onEvent({
        sequence: 2,
        status: 'completed',
        progress: 100,
        message: '处理完成',
        created_at: '2026-08-14T00:02:00Z'
      })
      onError('无法接收任务进度，请稍后重试。')
      return vi.fn()
    })
    const wrapper = mount(WorkspaceView, {
      global: { provide: { [jobsApiKey as symbol]: { createJob, subscribe } } }
    })

    await selectFile(wrapper, new File(['done'], 'done.txt', { type: 'text/plain' }))
    await flushPromises()

    expect(wrapper.text()).toContain('处理完成')
    expect(wrapper.text()).toContain('completed')
    expect(wrapper.text()).not.toContain('无法接收任务进度，请稍后重试。')
  })

  it('shows a temporary connection notice and clears it on the next progress event', async () => {
    const createJob = vi.fn().mockResolvedValue(buildJobRead())
    const subscribe = vi.fn((_jobId, onEvent, onError) => {
      onError('Connection interrupted. Waiting to reconnect…')
      onEvent({
        sequence: 2,
        status: 'parsing',
        progress: 25,
        message: '开始解析',
        created_at: '2026-08-14T00:01:00Z'
      })
      return vi.fn()
    })
    const wrapper = mount(WorkspaceView, {
      global: { provide: { [jobsApiKey as symbol]: { createJob, subscribe } } }
    })

    await selectFile(wrapper, new File(['progress'], 'progress.txt', { type: 'text/plain' }))
    await flushPromises()

    expect(wrapper.text()).toContain('开始解析')
    expect(wrapper.text()).not.toContain('Connection interrupted. Waiting to reconnect…')
  })

  it('synchronously ignores a second upload while create-job is pending', async () => {
    const pending = createDeferred<Awaited<ReturnType<JobsApi['createJob']>>>()
    const createJob = vi.fn().mockReturnValue(pending.promise)
    const subscribe = vi.fn(() => vi.fn())
    const wrapper = mount(WorkspaceView, {
      global: { provide: { [jobsApiKey as symbol]: { createJob, subscribe } } }
    })
    const first = new File(['first'], 'first.txt', { type: 'text/plain' })
    const second = new File(['second'], 'second.txt', { type: 'text/plain' })
    const input = wrapper.getComponent(SourceInputPanel)

    input.vm.$emit('submit-file', first)
    input.vm.$emit('submit-file', second)
    await flushPromises()

    expect(createJob).toHaveBeenCalledTimes(1)
    expect(createJob).toHaveBeenCalledWith(first)
    expect(subscribe).not.toHaveBeenCalled()

    pending.resolve(buildJobRead({ source_name: 'first.txt' }))
    await flushPromises()

    expect(subscribe).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('first.txt')
  })

  it('ignores an unresolved create-job response after unmount', async () => {
    const pending = createDeferred<Awaited<ReturnType<JobsApi['createJob']>>>()
    const createJob = vi.fn().mockReturnValue(pending.promise)
    const subscribe = vi.fn()
    const wrapper = mount(WorkspaceView, {
      global: { provide: { [jobsApiKey as symbol]: { createJob, subscribe } } }
    })

    await emitUpload(wrapper, new File(['late'], 'late.txt', { type: 'text/plain' }))
    wrapper.unmount()
    pending.resolve(buildJobRead())
    await flushPromises()

    expect(subscribe).not.toHaveBeenCalled()
  })

  it('announces backend job failures as alerts', async () => {
    const createJob = vi.fn().mockResolvedValue(buildJobRead())
    const subscribe = vi.fn((_jobId, onEvent) => {
      onEvent({
        sequence: 2,
        status: 'failed',
        progress: 40,
        message: '处理失败',
        created_at: '2026-08-14T00:01:00Z'
      })
      return vi.fn()
    })
    const wrapper = mount(WorkspaceView, {
      global: { provide: { [jobsApiKey as symbol]: { createJob, subscribe } } }
    })

    await selectFile(wrapper, new File(['failed'], 'failed.txt', { type: 'text/plain' }))
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('处理失败')
  })

  it('shows backend create-job errors', async () => {
    const createJob = vi.fn().mockRejectedValue(new Error('Upload exceeds the configured maximum size.'))
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe: vi.fn(() => vi.fn()) }
        }
      }
    })

    await selectFile(wrapper, new File(['limit'], 'large.txt', { type: 'text/plain' }))
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain(
      'Upload exceeds the configured maximum size.'
    )
  })

  it('keeps a nullable suggestion as manual-only rather than deleting source text', async () => {
    const payload = buildWorkspaceResult(
      [
        buildWorkspaceIssue({
          original: '禁用词',
          type: 'banned_word',
          severity: 'error',
          suggestion: null,
          alternatives: null,
          layer: 'discourse',
          message: '禁用词',
          description: '请人工处理',
          rule_id: 'banned_word',
          context: '禁用词',
          auto_fixable: false
        })
      ],
      '禁用词'
    )
    const analyzeText = vi.fn().mockResolvedValue(payload)
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: {
            createJob: vi.fn(),
            subscribe: vi.fn(() => vi.fn())
          },
          [verificationApiKey as symbol]: {
            analyzeFile: vi.fn(),
            analyzeText,
            exportReport: vi.fn(),
            exportOriginal: vi.fn()
          }
        }
      }
    })

    await wrapper.get('.mode-tabs button:nth-child(2)').trigger('click')
    await wrapper.get('.text-mode textarea').setValue('禁用词')
    await wrapper.get('.text-mode button').trigger('click')
    await flushPromises()
    await wrapper.get('.issue-actions .accept').trigger('click')
    await wrapper.get('[data-action="toggle-preview"]').trigger('click')

    expect(wrapper.get('.document-content.preview').text()).toBe('禁用词')
    expect(wrapper.text()).toContain('无自动建议')
    expect(wrapper.text()).not.toContain('null')
    confirm.mockRestore()
  })

  it('creates one canonical manual revision for a replace-all action and invalidates stale navigation', async () => {
    const issue = buildWorkspaceIssue({
      start: 0,
      end: 2,
      block_start: 0,
      block_end: 2,
      original: 'Aa',
      context: 'Aa😀aa'
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: {
            createJob: vi.fn(),
            subscribe: vi.fn(() => vi.fn())
          },
          [verificationApiKey as symbol]: {
            analyzeFile: vi.fn(),
            analyzeText: vi
              .fn()
              .mockResolvedValue(buildWorkspaceResult([issue], 'Aa😀aa')),
            exportReport: vi.fn(),
            exportOriginal: vi.fn()
          }
        }
      }
    })
    wrapper
      .getComponent(SourceInputPanel)
      .vm.$emit('submit-text', 'Aa😀aa')
    await flushPromises()
    wrapper.getComponent(DocumentViewer).vm.$emit('select-issue', issue.issue_id)
    await wrapper.get('[data-action="toggle-search-replace"]').trigger('click')
    const search = wrapper.getComponent(SearchReplacePanel)
    await search.get('[data-search-input]').setValue('aa')
    await search.get('[data-replacement-input]').setValue('X')
    await search.get('[data-action="replace-all"]').trigger('click')
    await flushPromises()

    const workspace = canonicalWorkspace(wrapper)
    expect(workspace.currentRevision.value).toMatchObject({
      kind: 'manual',
      text: 'X😀X',
      revision_number: null
    })
    expect(workspace.requiresReverification.value).toBe(true)
    expect(workspace.visibleIssues.value).toEqual([])
    expect(wrapper.getComponent(ReviewActions).props('selectedIssueId')).toBeNull()
    expect(wrapper.findAll('[data-issue-id]')).toHaveLength(0)
    expect(wrapper.text()).toContain('X😀X')
    wrapper.unmount()
  })

  it('saves, serializes, and restores a free edit as the only post-edit text source', async () => {
    const issue = buildWorkspaceIssue()
    const payload = buildWorkspaceResult([issue])
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const global = {
      provide: {
        [jobsApiKey as symbol]: {
          createJob: vi.fn(),
          subscribe: vi.fn(() => vi.fn())
        },
        [verificationApiKey as symbol]: {
          analyzeFile: vi.fn(),
          analyzeText: vi.fn().mockResolvedValue(payload),
          exportReport: vi.fn(),
          exportOriginal: vi.fn()
        }
      }
    }
    const first = mount(WorkspaceView, { global })
    first.getComponent(SourceInputPanel).vm.$emit('submit-text', payload.text)
    await flushPromises()
    const editor = first.getComponent(EditPreview)
    await editor.get('[data-action="start-edit"]').trigger('click')
    await editor.get('[data-edit-input]').setValue('手工修改后的全文')
    await editor.get('[data-action="save-edit"]').trigger('click')
    await flushPromises()

    const saved = JSON.parse(
      sessionStorage.getItem('text-verification-session') ?? 'null'
    )
    expect(saved).toMatchObject({
      version: 2,
      requiresReverification: true,
      currentRevision: {
        kind: 'manual',
        text: '手工修改后的全文'
      }
    })
    first.unmount()

    const restored = mount(WorkspaceView, { global })
    await flushPromises()
    const workspace = canonicalWorkspace(restored)
    expect(workspace.currentRevision.value).toEqual(saved.currentRevision)
    expect(workspace.requiresReverification.value).toBe(true)
    expect(workspace.visibleIssues.value).toEqual([])
    expect(restored.text()).toContain('手工修改后的全文')
    expect(restored.findAll('[data-issue-id]')).toHaveLength(0)
    restored.unmount()
  })

  it('exports the current manual revision through the text fallback without stale issue offsets', async () => {
    const exportOriginal = vi.fn()
    let exportedBlob: Blob | null = null
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn((blob: Blob) => {
        exportedBlob = blob
        return 'blob:manual'
      })
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn()
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const payload = buildWorkspaceResult([buildWorkspaceIssue()], '甲乙丙丁', {
      file_id: '66666666-6666-4666-8666-666666666666',
      file_ext: 'txt'
    })
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: {
            createJob: vi.fn(),
            subscribe: vi.fn(() => vi.fn())
          },
          [verificationApiKey as symbol]: {
            analyzeFile: vi.fn(),
            analyzeText: vi.fn().mockResolvedValue(payload),
            exportReport: vi.fn(),
            exportOriginal
          }
        }
      }
    })
    wrapper.getComponent(SourceInputPanel).vm.$emit('submit-text', payload.text)
    await flushPromises()
    const editor = wrapper.getComponent(EditPreview)
    await editor.get('[data-action="start-edit"]').trigger('click')
    await editor.get('[data-edit-input]').setValue('最终手工文本')
    await editor.get('[data-action="save-edit"]').trigger('click')
    await wrapper.get('.top-actions .btn.primary').trigger('click')

    expect(exportOriginal).not.toHaveBeenCalled()
    expect(exportedBlob).not.toBeNull()
    const blob = exportedBlob
    if (blob === null) {
      throw new Error('Expected a manual revision fallback Blob.')
    }
    const exportedText = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.addEventListener('load', () => resolve(String(reader.result)))
      reader.addEventListener('error', () => reject(reader.error))
      reader.readAsText(blob)
    })
    expect(exportedText).toBe('最终手工文本')
    wrapper.unmount()
  })

  it('accepts an overlapping batch atomically and undoes the exact batch', async () => {
    const payload = buildWorkspaceResult(
      buildConflictIssues('crossing'),
      'abcdef'
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: {
            createJob: vi.fn(),
            subscribe: vi.fn(() => vi.fn())
          },
          [verificationApiKey as symbol]: {
            analyzeFile: vi.fn(),
            analyzeText: vi.fn().mockResolvedValue(payload),
            exportReport: vi.fn(),
            exportOriginal: vi.fn()
          }
        }
      }
    })
    wrapper
      .getComponent(SourceInputPanel)
      .vm.$emit('submit-text', 'abcdef')
    await flushPromises()
    const workspace = canonicalWorkspace(wrapper)
    const sourceRevision = workspace.currentRevision.value

    await wrapper.get('[data-action="accept-batch"]').trigger('click')

    expect(workspace.currentRevision.value).toBe(sourceRevision)
    expect(workspace.modifiedText.value).toBe('abcdef')
    expect(workspace.hasReplacementConflicts.value).toBe(true)
    expect(workspace.canUndoLastBatch.value).toBe(true)
    expect(wrapper.text()).toContain('撤销批量操作')

    const undo = wrapper
      .findAll('button')
      .find((button) => button.text() === '撤销批量操作')
    if (!undo) {
      throw new Error('Expected canonical batch undo control.')
    }
    await undo.trigger('click')

    expect(workspace.issueStates.value).toEqual({})
    expect(workspace.currentRevision.value).toBe(sourceRevision)
    expect(workspace.hasReplacementConflicts.value).toBe(false)
    expect(workspace.canUndoLastBatch.value).toBe(false)
    expect(
      wrapper.get('[data-action="undo-batch"]').attributes('disabled')
    ).toBeDefined()
  })

  it('undoes reset-all before the preceding accept-all batch', async () => {
    const first = buildWorkspaceIssue({
      start: 0,
      end: 1,
      block_start: 0,
      block_end: 1,
      original: '甲',
      suggestion: 'A'
    })
    const second = buildWorkspaceIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: '丙',
      suggestion: 'C'
    })
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: {
            createJob: vi.fn(),
            subscribe: vi.fn(() => vi.fn())
          },
          [verificationApiKey as symbol]: {
            analyzeFile: vi.fn(),
            analyzeText: vi
              .fn()
              .mockResolvedValue(buildWorkspaceResult([first, second])),
            exportReport: vi.fn(),
            exportOriginal: vi.fn()
          }
        }
      }
    })
    wrapper
      .getComponent(SourceInputPanel)
      .vm.$emit('submit-text', '甲乙丙丁')
    await flushPromises()
    const workspace = canonicalWorkspace(wrapper)

    await wrapper.get('[data-action="accept-batch"]').trigger('click')
    const reset = wrapper
      .findAll('button')
      .find((button) => button.text() === '重置状态')
    if (!reset) {
      throw new Error('Expected reset-all control.')
    }
    await reset.trigger('click')

    expect(workspace.issueStates.value).toEqual({
      [first.issue_id]: 'pending',
      [second.issue_id]: 'pending'
    })

    const undo = wrapper
      .findAll('button')
      .find((button) => button.text() === '撤销批量操作')
    if (!undo) {
      throw new Error('Expected canonical batch undo control.')
    }
    await undo.trigger('click')

    expect(workspace.issueStates.value).toEqual({
      [first.issue_id]: 'accepted',
      [second.issue_id]: 'accepted'
    })
    expect(workspace.canUndoLastBatch.value).toBe(true)
    wrapper.unmount()
  })

  it('restores session decisions without restoring batch undo eligibility', async () => {
    const issue = buildWorkspaceIssue({
      start: 1,
      end: 2,
      block_start: 1,
      block_end: 2,
      original: 'b'
    })
    const payload = buildWorkspaceResult([issue], 'abc')
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const api = {
      analyzeFile: vi.fn(),
      analyzeText: vi.fn().mockResolvedValue(payload),
      exportReport: vi.fn(),
      exportOriginal: vi.fn()
    }
    const global = {
      provide: {
        [jobsApiKey as symbol]: {
          createJob: vi.fn(),
          subscribe: vi.fn(() => vi.fn())
        },
        [verificationApiKey as symbol]: api
      }
    }
    const first = mount(WorkspaceView, { global })
    first
      .getComponent(SourceInputPanel)
      .vm.$emit('submit-text', 'abc')
    await flushPromises()
    await first.get('[data-action="accept-batch"]').trigger('click')
    expect(canonicalWorkspace(first).canUndoLastBatch.value).toBe(true)
    first.unmount()

    const restored = mount(WorkspaceView, { global })
    await flushPromises()

    expect(canonicalWorkspace(restored).issueStates.value).toEqual({
      [issue.issue_id]: 'accepted'
    })
    expect(canonicalWorkspace(restored).canUndoLastBatch.value).toBe(false)
    expect(
      restored.get('[data-action="undo-batch"]').attributes('disabled')
    ).toBeDefined()
    restored.unmount()
  })

  it.each(['crossing', 'nested'] as const)(
    'restores %s accepted conflicts without publishing a partial revision',
    async (kind) => {
      const issues = buildConflictIssues(kind)
      const payload = buildWorkspaceResult(issues, 'abcdef')
      sessionStorage.setItem(
        'text-verification-session',
        JSON.stringify({
          result: payload,
          workingText: payload.text,
          issueStates: Object.fromEntries(
            issues.map((issue) => [issue.issue_id, 'accepted'])
          ),
          selectedSuggestions: {}
        })
      )
      const wrapper = mount(WorkspaceView, {
        global: {
          provide: {
            [jobsApiKey as symbol]: {
              createJob: vi.fn(),
              subscribe: vi.fn(() => vi.fn())
            }
          }
        }
      })
      await flushPromises()
      const workspace = canonicalWorkspace(wrapper)

      expect(workspace.issueStates.value).toEqual({
        [issues[0].issue_id]: 'accepted',
        [issues[1].issue_id]: 'accepted'
      })
      expect(workspace.hasReplacementConflicts.value).toBe(true)
      expect(workspace.currentRevision.value).toMatchObject({
        kind: 'source',
        revision_id: null,
        text: 'abcdef'
      })
      expect(workspace.modifiedText.value).toBe('abcdef')
      expect(workspace.canUndoLastBatch.value).toBe(false)
      wrapper.unmount()
    }
  )

  it('restores nonconflicting session state into one correct revision', async () => {
    const first = buildWorkspaceIssue({
      start: 0,
      end: 1,
      block_start: 0,
      block_end: 1,
      original: 'a',
      suggestion: 'A',
      context: 'abcd'
    })
    const second = buildWorkspaceIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: 'c',
      suggestion: 'C',
      context: 'abcd'
    })
    const payload = buildWorkspaceResult([first, second], 'abcd')
    sessionStorage.setItem(
      'text-verification-session',
      JSON.stringify({
        result: payload,
        workingText: payload.text,
        issueStates: {
          [first.issue_id]: 'accepted',
          [second.issue_id]: 'accepted'
        },
        selectedSuggestions: {
          [first.issue_id]: '',
          [second.issue_id]: 'SEE'
        }
      })
    )
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: {
            createJob: vi.fn(),
            subscribe: vi.fn(() => vi.fn())
          }
        }
      }
    })
    await flushPromises()
    const workspace = canonicalWorkspace(wrapper)

    expect(workspace.selectedSuggestions.value).toEqual({
      [first.issue_id]: '',
      [second.issue_id]: 'SEE'
    })
    expect(workspace.currentRevision.value).toMatchObject({
      kind: 'review',
      parent_revision_id: null,
      text: 'bSEEd'
    })
    expect(workspace.modifiedText.value).toBe('bSEEd')
    expect(workspace.canUndoLastBatch.value).toBe(false)
    wrapper.unmount()
  })

  it.each(
    (['crossing', 'nested', 'identical'] as const).flatMap((kind) =>
      (['fallback', 'original-file'] as const).map((path) => [kind, path] as const)
    )
  )(
    'blocks %s accepted-range conflicts before the %s export path',
    async (kind, path) => {
      const exportOriginal = vi.fn()
      const createObjectURL = vi.fn(() => 'blob:test')
      Object.defineProperty(URL, 'createObjectURL', {
        configurable: true,
        value: createObjectURL
      })
      Object.defineProperty(URL, 'revokeObjectURL', {
        configurable: true,
        value: vi.fn()
      })
      const anchorClick = vi
        .spyOn(HTMLAnchorElement.prototype, 'click')
        .mockImplementation(() => {})
      vi.spyOn(window, 'confirm').mockReturnValue(true)
      const payload = buildWorkspaceResult(
        buildConflictIssues(kind),
        'abcdef',
        path === 'original-file'
          ? {
              file_id: '55555555-5555-4555-8555-555555555555',
              file_ext: 'docx'
            }
          : {}
      )
      const wrapper = mount(WorkspaceView, {
        global: {
          provide: {
            [jobsApiKey as symbol]: {
              createJob: vi.fn(),
              subscribe: vi.fn(() => vi.fn())
            },
            [verificationApiKey as symbol]: {
              analyzeFile: vi.fn(),
              analyzeText: vi.fn().mockResolvedValue(payload),
              exportReport: vi.fn(),
              exportOriginal
            }
          }
        }
      })
      wrapper
        .getComponent(SourceInputPanel)
        .vm.$emit('submit-text', 'abcdef')
      await flushPromises()
      const workspace = canonicalWorkspace(wrapper)
      const sourceRevision = workspace.currentRevision.value
      await wrapper.get('[data-action="accept-batch"]').trigger('click')

      await wrapper.get('.top-actions .btn.primary').trigger('click')

      expect(wrapper.get('.toast').text()).toBe(
        '存在重叠的已接受修改，请先解决冲突后再导出'
      )
      expect(createObjectURL).not.toHaveBeenCalled()
      expect(anchorClick).not.toHaveBeenCalled()
      expect(exportOriginal).not.toHaveBeenCalled()
      expect(workspace.currentRevision.value).toBe(sourceRevision)
      expect(workspace.modifiedText.value).toBe('abcdef')
      wrapper.unmount()
    }
  )

  it('exports tracked text at canonical code-point offsets', async () => {
    const payload = buildWorkspaceResult(
      [
        buildWorkspaceIssue({
          start: 4,
          end: 5,
          block_start: 4,
          block_end: 5,
          original: '错',
          suggestion: '正',
          alternatives: null,
          context: '😀甲错乙错'
        })
      ],
      '😀甲错乙错'
    )
    const analyzeText = vi.fn().mockResolvedValue(payload)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    let exportedBlob: Blob | null = null
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn((blob: Blob) => {
        exportedBlob = blob
        return 'blob:test'
      })
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn()
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: {
            createJob: vi.fn(),
            subscribe: vi.fn(() => vi.fn())
          },
          [verificationApiKey as symbol]: {
            analyzeFile: vi.fn(),
            analyzeText,
            exportReport: vi.fn(),
            exportOriginal: vi.fn()
          }
        }
      }
    })

    wrapper
      .getComponent(SourceInputPanel)
      .vm.$emit('submit-text', '😀甲错乙错')
    await flushPromises()
    await wrapper.get('.issue-actions .accept').trigger('click')
    await wrapper.get('.top-actions .btn.primary').trigger('click')

    expect(exportedBlob).not.toBeNull()
    const blob = exportedBlob
    if (blob === null) {
      throw new Error('Expected an exported Blob.')
    }
    const exportedText = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.addEventListener('load', () => resolve(String(reader.result)))
      reader.addEventListener('error', () => reject(reader.error))
      reader.readAsText(blob)
    })
    expect(exportedText).toBe(
      '😀甲错乙【删除：错】【替换为：正】'
    )
  })
})
