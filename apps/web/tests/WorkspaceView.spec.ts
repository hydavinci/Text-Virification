import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { jobsApiKey, type JobsApi } from '../src/api/jobs'
import { verificationApiKey } from '../src/api/verification'
import SourceInputPanel from '../src/components/workspace/SourceInputPanel.vue'
import TerminologyEditor from '../src/components/workspace/TerminologyEditor.vue'
import VerificationSettings from '../src/components/workspace/VerificationSettings.vue'
import type { AnalyzeOptions, VerificationResult } from '../src/types/verification'
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

describe('WorkspaceView', () => {
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

  it('treats a nullable suggestion as a safe deletion in the current workspace', async () => {
    const payload = {
      success: true,
      filename: 'direct.txt',
      text: '禁用词',
      stats: {
        char_count: 3,
        char_count_no_space: 3,
        line_count: 1,
        paragraph_count: 1,
        language: 'zh',
        primary_count: 3,
        primary_label: '总字数'
      },
      issues: [
        {
          issue_id: '33333333-3333-3333-3333-333333333333',
          document_id: '11111111-1111-1111-1111-111111111111',
          verification_run_id: '22222222-2222-2222-2222-222222222222',
          block_id: 'p-0',
          page: null,
          start: 0,
          end: 3,
          block_start: 0,
          block_end: 3,
          type: 'banned_word',
          severity: 'error',
          original: '禁用词',
          suggestion: null,
          alternatives: null,
          layer: 'discourse',
          message: '禁用词',
          description: '请人工处理',
          rule_id: 'banned_word',
          rule_version: '1',
          source: 'compatibility.analyzer',
          source_version: '1',
          confidence: 1,
          auto_fixable: false,
          context: '禁用词',
          position: 0,
          end_position: 3,
          review: '',
          review_reason: ''
        }
      ],
      summary: {
        total: 1,
        by_type: { banned_word: 1 },
        by_severity: { error: 1 },
        by_rule: { banned_word: 1 },
        by_layer: { discourse: 1 }
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
      scenario: 'general'
    } as unknown as VerificationResult
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
    await wrapper.get('.review-toolbar button:nth-child(3)').trigger('click')

    expect(wrapper.get('.document-content.preview').text()).toBe('')
    expect(wrapper.text()).toContain('（删除）')
    expect(wrapper.text()).not.toContain('null')
    confirm.mockRestore()
  })
})
