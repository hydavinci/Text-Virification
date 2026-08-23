import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { analysisApiKey, type AnalysisApi } from '../src/api/analysis'
import { exportsApiKey, type ExportsApi } from '../src/api/exports'
import { jobsApiKey, type JobsApi } from '../src/api/jobs'
import { revisionsApiKey, type RevisionsApi } from '../src/api/revisions'
import UploadWorkspace from '../src/components/UploadWorkspace.vue'
import { type JobCreateOptions } from '../src/types/jobs'
import { CHECK_CATEGORY_VALUES } from '../src/types/review'
import type { DocumentVersion, EditDraft } from '../src/types/revisions'
import WorkspaceView from '../src/views/WorkspaceView.vue'

type UploadOptionsSnapshot = Readonly<Required<JobCreateOptions>>

function buildJobRead(
  overrides: Partial<Awaited<ReturnType<JobsApi['createJob']>>> = {}
): Awaited<ReturnType<JobsApi['createJob']>> {
  return {
    job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
    source_name: 'sample.txt',
    file_type: 'txt' as const,
    size_bytes: 6,
    status: 'queued' as const,
    progress: 0,
    error_code: null,
    error_message: null,
    scenario: 'general' as const,
    enabled_categories: [
      'character',
      'vocabulary',
      'sentence',
      'format',
      'discourse',
      'security'
    ],
    created_at: '2026-08-14T00:00:00Z',
    expires_at: '2026-08-15T00:00:00Z',
    ...overrides
  }
}

function buildUploadOptions(overrides: JobCreateOptions = {}): UploadOptionsSnapshot {
  const enabledCategories = Object.freeze(
    overrides.enabledCategories ? [...overrides.enabledCategories] : [...CHECK_CATEGORY_VALUES]
  ) as UploadOptionsSnapshot['enabledCategories']

  return Object.freeze({
    scenario: overrides.scenario ?? 'general',
    enabledCategories
  })
}

async function selectFile(wrapper: ReturnType<typeof mount>, file: File) {
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', {
    configurable: true,
    value: [file]
  })
  await input.trigger('change')
}

async function emitUpload(
  wrapper: ReturnType<typeof mount>,
  file: File,
  options: UploadOptionsSnapshot = buildUploadOptions()
) {
  wrapper.getComponent(UploadWorkspace).vm.$emit('upload', file, options)
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

function createAnalysisApiMock(
  overrides: Partial<AnalysisApi> = {}
): AnalysisApi {
  return {
    getSummary: vi.fn().mockResolvedValue({
      job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
      status: 'completed',
      total_issues: 0,
      by_category: {
        character: 0,
        vocabulary: 0,
        sentence: 0,
        format: 0,
        discourse: 0,
        security: 0
      },
      by_severity: { error: 0, warning: 0, info: 0 },
      by_decision: { accepted: 0, ignored: 0, custom: 0, unreviewed: 0 },
      checker_failures: {}
    }),
    getDocumentPage: vi.fn().mockResolvedValue({
      job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
      status: 'completed',
      document_id: 'document-1',
      file_type: 'txt',
      source_name: 'sample.txt',
      version: 1,
      metadata: {},
      blocks: [],
      total_blocks: 0,
      next_cursor: null,
      checker_failures: {}
    }),
    getIssues: vi.fn().mockResolvedValue({
      job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
      status: 'completed',
      total: 0,
      items: [],
      next_cursor: null,
      checker_failures: {}
    }),
    putDecisions: vi.fn(),
    ...overrides
  }
}

function createExportsApiMock(overrides: Partial<ExportsApi> = {}): ExportsApi {
  return {
    create: vi.fn(),
    get: vi.fn(),
    downloadUrl: vi
      .fn()
      .mockReturnValue('/api/v1/jobs/6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f/exports/export-1/download'),
    ...overrides
  }
}

function buildVersion(overrides: Partial<DocumentVersion> = {}): DocumentVersion {
  return {
    version_id: 'version-1',
    job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
    parent_version_id: null,
    revision_number: 1,
    status: 'succeeded',
    source_kind: 'original',
    created_reason: 'upload',
    content_sha256: 'a'.repeat(64),
    created_at: '2026-08-23T12:00:00Z',
    started_at: '2026-08-23T12:00:01Z',
    completed_at: '2026-08-23T12:00:02Z',
    failure_code: null,
    failure_message: null,
    ...overrides
  }
}

function buildDraft(overrides: Partial<EditDraft> = {}): EditDraft {
  return {
    draft_id: 'draft-1',
    job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
    base_version_id: 'version-1',
    revision: 1,
    blocks: [{ block_id: 'block-1', text: '服务器草稿' }],
    content_sha256: null,
    created_at: '2026-08-23T12:00:00Z',
    updated_at: '2026-08-23T12:00:00Z',
    consumed_at: null,
    ...overrides
  }
}

function createRevisionsApiMock(overrides: Partial<RevisionsApi> = {}): RevisionsApi {
  return {
    listVersions: vi.fn().mockResolvedValue({
      job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
      active_version_id: 'version-1',
      versions: [buildVersion()]
    }),
    createDraft: vi.fn().mockResolvedValue(buildDraft()),
    getDraft: vi.fn().mockResolvedValue(buildDraft()),
    updateDraft: vi.fn().mockResolvedValue(buildDraft({ revision: 2 })),
    deleteDraft: vi.fn().mockResolvedValue(undefined),
    reanalyze: vi.fn(),
    getDerived: vi.fn(),
    subscribeVersionEvents: vi.fn().mockReturnValue(vi.fn()),
    listHistory: vi.fn().mockResolvedValue({
      job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
      version_id: 'version-1',
      total: 0,
      items: [],
      next_cursor: null
    }),
    undoBatch: vi.fn(),
    ...overrides
  }
}

describe('WorkspaceView', () => {
  it('presents the upload workspace in Simplified Chinese', () => {
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

    expect(wrapper.get('h1').text()).toBe('文档智能核验')
    expect(wrapper.get('[data-testid="upload-dropzone"]').text()).toContain('点击选择或拖拽文件到此处')
    expect(wrapper.text()).toContain('支持 DOCX、PDF、TXT 格式，文件大小不超过 25 MiB')
    expect(
      wrapper.findAll('select[name="scenario"] option').map((option) => option.text())
    ).toEqual(['通用', '学术', '商务', '法律', '新闻', '技术'])
    expect(
      wrapper
        .findAll('select[name="scenario"] option')
        .map((option) => option.attributes('value'))
    ).toEqual(['general', 'academic', 'business', 'legal', 'news', 'technical'])
  })

  it('uploads the selected scenario and categories with the file', async () => {
    const createJob = vi.fn().mockResolvedValue(buildJobRead())
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe: vi.fn(() => vi.fn()) }
        }
      }
    })
    const file = new File(['检查'], 'sample.txt', { type: 'text/plain' })

    await wrapper.get('select[name="scenario"]').setValue('legal')
    await wrapper.get('input[name="category-character"]').setValue(false)
    await wrapper.get('input[name="category-format"]').setValue(false)
    await selectFile(wrapper, file)
    await flushPromises()

    expect(createJob).toHaveBeenCalledWith(
      file,
      buildUploadOptions({
        scenario: 'legal',
        enabledCategories: ['vocabulary', 'sentence', 'discourse', 'security']
      })
    )
  })

  it('forwards the same frozen upload options snapshot to createJob', async () => {
    const createJob = vi.fn().mockResolvedValue(buildJobRead())
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe: vi.fn(() => vi.fn()) }
        }
      }
    })
    const file = new File(['检查'], 'sample.txt', { type: 'text/plain' })
    const options = buildUploadOptions({
      scenario: 'legal',
      enabledCategories: ['character', 'security']
    })

    await emitUpload(wrapper, file, options)

    expect(createJob).toHaveBeenCalledTimes(1)

    const [, forwardedOptions] = createJob.mock.calls[0] as [File, UploadOptionsSnapshot]

    expect(Object.isFrozen(forwardedOptions)).toBe(true)
    expect(Object.isFrozen(forwardedOptions.enabledCategories)).toBe(true)
    expect(forwardedOptions).toBe(options)
  })

  it('rejects uploads when no check categories are selected', async () => {
    const createJob = vi.fn()
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe: vi.fn(() => vi.fn()) }
        }
      }
    })

    for (const category of CHECK_CATEGORY_VALUES) {
      await wrapper.get(`input[name="category-${category}"]`).setValue(false)
    }

    await selectFile(wrapper, new File(['检查'], 'sample.txt', { type: 'text/plain' }))

    expect(createJob).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('至少选择一类检查')
  })

  it('uploads an allowed file dropped onto the upload area', async () => {
    const createJob = vi.fn().mockResolvedValue(buildJobRead())
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe: vi.fn(() => vi.fn()) }
        }
      }
    })
    const file = new File(['检查'], 'sample.txt', { type: 'text/plain' })

    await wrapper.get('[data-testid="upload-dropzone"]').trigger('drop', {
      dataTransfer: { files: [file] }
    })
    await flushPromises()

    expect(createJob).toHaveBeenCalledWith(file, buildUploadOptions())
  })

  it('opens the review workspace after analysis completes', async () => {
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
    const analysisApi = createAnalysisApiMock()
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe },
          [analysisApiKey as symbol]: analysisApi,
          [exportsApiKey as symbol]: createExportsApiMock()
        }
      }
    })
    const file = new File(['检查'], 'sample.txt', { type: 'text/plain' })

    await selectFile(wrapper, file)
    await flushPromises()

    expect(createJob).toHaveBeenCalledWith(file, buildUploadOptions())
    expect(wrapper.find('[aria-label="文档审阅工作台"]').exists()).toBe(true)
    expect(wrapper.get('main').classes()).toContain('workspace--review')
    expect(wrapper.get('[data-testid="document-header"]').text()).toContain('sample.txt')
    expect(analysisApi.getDocumentPage).toHaveBeenCalledWith(
      '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
      { cursor: null, limit: 100 }
    )
    expect(analysisApi.getIssues).toHaveBeenCalledWith(
      '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
      { cursor: null, limit: 50 }
    )
  })

  it('returns to the upload workspace to process another file', async () => {
    const closeSubscription = vi.fn()
    const createJob = vi.fn().mockResolvedValue(buildJobRead())
    const subscribe = vi.fn((_jobId, onEvent) => {
      onEvent({
        sequence: 2,
        status: 'completed',
        progress: 100,
        message: '处理完成',
        created_at: '2026-08-14T00:02:00Z'
      })
      return closeSubscription
    })
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe },
          [analysisApiKey as symbol]: createAnalysisApiMock(),
          [exportsApiKey as symbol]: createExportsApiMock()
        }
      }
    })

    await selectFile(wrapper, new File(['检查'], 'sample.txt', { type: 'text/plain' }))
    await flushPromises()
    await wrapper.get('button[name="process-another-file"]').trigger('click')
    await flushPromises()

    expect(closeSubscription).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[aria-label="文档审阅工作台"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="upload-dropzone"]').isVisible()).toBe(true)
    expect(wrapper.get('main').classes()).not.toContain('workspace--review')
  })

  it('keeps the current review when processing another file is cancelled with a dirty draft', async () => {
    const originalConfirm = globalThis.confirm
    const confirm = vi.fn().mockReturnValue(false)
    globalThis.confirm = confirm
    const closeSubscription = vi.fn()
    const createJob = vi.fn().mockResolvedValue(buildJobRead())
    const subscribe = vi.fn((_jobId, onEvent) => {
      onEvent({
        sequence: 2,
        status: 'completed',
        progress: 100,
        message: '处理完成',
        created_at: '2026-08-14T00:02:00Z'
      })
      return closeSubscription
    })

    try {
      const wrapper = mount(WorkspaceView, {
        global: {
          provide: {
            [jobsApiKey as symbol]: { createJob, subscribe },
            [analysisApiKey as symbol]: createAnalysisApiMock(),
            [exportsApiKey as symbol]: createExportsApiMock(),
            [revisionsApiKey as symbol]: createRevisionsApiMock()
          }
        }
      })

      await selectFile(wrapper, new File(['检查'], 'sample.txt', { type: 'text/plain' }))
      await flushPromises()
      await wrapper.get('button[name="edit-version"]').trigger('click')
      await flushPromises()
      await wrapper.get('textarea[aria-label="第 1 段"]').setValue('未保存文本')
      await wrapper.get('button[name="process-another-file"]').trigger('click')
      await flushPromises()

      expect(confirm).toHaveBeenCalledTimes(1)
      expect(closeSubscription).not.toHaveBeenCalled()
      expect(wrapper.find('[aria-label="文档审阅工作台"]').exists()).toBe(true)
      expect((wrapper.get('textarea[aria-label="第 1 段"]').element as HTMLTextAreaElement).value).toBe(
        '未保存文本'
      )
    } finally {
      globalThis.confirm = originalConfirm
    }
  })

  it('opens the review workspace when analysis partially completes', async () => {
    const createJob = vi.fn().mockResolvedValue(buildJobRead())
    const subscribe = vi.fn((_jobId, onEvent) => {
      onEvent({
        sequence: 2,
        status: 'partial',
        progress: 100,
        message: '部分检查器失败',
        created_at: '2026-08-14T00:02:00Z'
      })
      return vi.fn()
    })
    const analysisApi = createAnalysisApiMock({
      getSummary: vi.fn().mockResolvedValue({
        job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
        status: 'partial',
        total_issues: 0,
        by_category: {
          character: 0,
          vocabulary: 0,
          sentence: 0,
          format: 0,
          discourse: 0,
          security: 0
        },
        by_severity: { error: 0, warning: 0, info: 0 },
        by_decision: { accepted: 0, ignored: 0, custom: 0, unreviewed: 0 },
        checker_failures: {
          security: {
            code: 'checker_failed',
            message: '安全检查器启动失败'
          }
        }
      })
    })
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe },
          [analysisApiKey as symbol]: analysisApi,
          [exportsApiKey as symbol]: createExportsApiMock()
        }
      }
    })

    await selectFile(wrapper, new File(['检查'], 'partial.txt', { type: 'text/plain' }))
    await flushPromises()

    expect(wrapper.find('[aria-label="文档审阅工作台"]').exists()).toBe(true)
    expect(wrapper.get('[data-testid="document-header"]').text()).toContain('sample.txt')
    expect(analysisApi.getSummary).toHaveBeenCalledWith(
      '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f'
    )
    expect(wrapper.get('.checker-failures__category').text()).toBe('安全')
    expect(wrapper.text()).toContain('安全检查器启动失败')
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

    expect(createJob).toHaveBeenCalledWith(exactLimit, buildUploadOptions())
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  }, 15_000)

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
    const analysisApi = createAnalysisApiMock()
    const wrapper = mount(WorkspaceView, {
      global: {
        provide: {
          [jobsApiKey as symbol]: { createJob, subscribe },
          [analysisApiKey as symbol]: analysisApi,
          [exportsApiKey as symbol]: createExportsApiMock()
        }
      }
    })

    await selectFile(wrapper, new File(['done'], 'done.txt', { type: 'text/plain' }))
    await flushPromises()

    expect(wrapper.find('[aria-label="文档审阅工作台"]').exists()).toBe(true)
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

  it('keeps the newer upload when create-job responses resolve out of order', async () => {
    const first = createDeferred<Awaited<ReturnType<JobsApi['createJob']>>>()
    const second = createDeferred<Awaited<ReturnType<JobsApi['createJob']>>>()
    const createJob = vi.fn()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise)
    const closeSecond = vi.fn()
    const subscribe = vi.fn().mockImplementation(() => closeSecond)
    const wrapper = mount(WorkspaceView, {
      global: { provide: { [jobsApiKey as symbol]: { createJob, subscribe } } }
    })

    await emitUpload(wrapper, new File(['first'], 'first.txt', { type: 'text/plain' }))
    await emitUpload(wrapper, new File(['second'], 'second.txt', { type: 'text/plain' }))

    second.resolve(
      buildJobRead({
        job_id: 'job-2',
        source_name: 'second.txt'
      })
    )
    await flushPromises()

    first.resolve(
      buildJobRead({
        job_id: 'job-1',
        source_name: 'first.txt'
      })
    )
    await flushPromises()

    expect(subscribe).toHaveBeenCalledTimes(1)
    expect(subscribe).toHaveBeenCalledWith('job-2', expect.any(Function), expect.any(Function))
    expect(wrapper.text()).toContain('second.txt')
    expect(wrapper.text()).not.toContain('first.txt')
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
})
