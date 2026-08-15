import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { jobsApiKey, type JobsApi } from '../src/api/jobs'
import UploadWorkspace from '../src/components/UploadWorkspace.vue'
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
  wrapper.getComponent(UploadWorkspace).vm.$emit('upload', file)
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
