import { describe, expect, it, vi } from 'vitest'

import { createJobsApi } from '../src/api/jobs'
import { JOB_STATUS_VALUES } from '../src/types/jobs'

class FakeEventSource {
  public onerror: ((event: Event) => void) | null = null

  private listeners = new Map<string, Set<(event: MessageEvent<string>) => void>>()
  private _closed = false
  private _closeCalls = 0

  constructor(public readonly url: string) {}

  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    const callback =
      typeof listener === 'function'
        ? (listener as (event: MessageEvent<string>) => void)
        : ((event: MessageEvent<string>) => listener.handleEvent(event))
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set())
    }
    this.listeners.get(type)?.add(callback)
  }

  removeEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    const callback =
      typeof listener === 'function'
        ? (listener as (event: MessageEvent<string>) => void)
        : ((event: MessageEvent<string>) => listener.handleEvent(event))
    this.listeners.get(type)?.delete(callback)
  }

  close() {
    this._closeCalls += 1
    this._closed = true
  }

  emit(type: string, data: Record<string, unknown>, lastEventId = '0') {
    const event = {
      data: JSON.stringify(data),
      lastEventId
    } as MessageEvent<string>
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event)
    }
  }

  emitRaw(type: string, data: string, lastEventId = '0') {
    const event = {
      data,
      lastEventId
    } as MessageEvent<string>
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event)
    }
  }

  emitControl(type: string) {
    const event = { data: JSON.stringify({ event: type }) } as MessageEvent<string>
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event)
    }
  }

  emitError() {
    this.onerror?.(new Event('error'))
  }

  get closed() {
    return this._closed
  }

  get closeCalls() {
    return this._closeCalls
  }
}

describe('createJobsApi', () => {
  it('posts uploads to the relative API base and returns the job payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
        source_name: 'sample.txt',
        file_type: 'txt',
        size_bytes: 6,
        status: 'queued',
        progress: 0,
        error_code: null,
        error_message: null,
        created_at: '2026-08-14T00:00:00Z',
        expires_at: '2026-08-15T00:00:00Z'
      })
    })
    const api = createJobsApi({
      fetch: fetchMock,
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource
    })
    const file = new File(['body'], 'sample.txt', { type: 'text/plain' })

    const job = await api.createJob(file)

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/jobs', expect.objectContaining({ method: 'POST' }))
    expect(job.job_id).toBe('6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f')
  })

  it('parses shaped backend errors from create-job responses', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 413,
      json: async () => ({
        detail: {
          code: 'upload_too_large',
          message: 'Upload exceeds the configured maximum size.'
        }
      })
    })
    const api = createJobsApi({
      fetch: fetchMock,
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource
    })

    await expect(
      api.createJob(new File(['body'], 'large.txt', { type: 'text/plain' }))
    ).rejects.toThrow('Upload exceeds the configured maximum size.')
  })

  it('keeps the stream open across transient errors and accepts later progress', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
    const api = createJobsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    })
    const onEvent = vi.fn()
    const onError = vi.fn()

    api.subscribe('job-1', onEvent, onError)
    eventSource.emitError()
    eventSource.emit('progress', {
      status: 'completed',
      progress: 100,
      message: '处理完成',
      created_at: '2026-08-14T00:02:00Z'
    }, '3')

    expect(onEvent).toHaveBeenCalledTimes(1)
    expect(onEvent).toHaveBeenLastCalledWith(
      expect.objectContaining({
        sequence: 3,
        status: 'completed',
        progress: 100,
        message: '处理完成'
      })
    )
    expect(onError).toHaveBeenCalledWith('Connection interrupted. Waiting to reconnect…')
    expect(eventSource.closed).toBe(false)
    expect(eventSource.closeCalls).toBe(0)
  })

  it('closes once and reports an error for malformed JSON progress payloads', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
    const api = createJobsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    })
    const onEvent = vi.fn()
    const onError = vi.fn()

    api.subscribe('job-1', onEvent, onError)
    eventSource.emitRaw('progress', '{"status":"parsing",')

    expect(onEvent).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledWith('Unable to receive job progress updates.')
    expect(eventSource.closeCalls).toBe(1)
  })

  it.each([
    ['missing created_at', '{"status":"parsing","progress":25,"message":"开始解析"}'],
    ['bad status', '{"status":"unknown","progress":25,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['non-finite progress', '{"status":"parsing","progress":1e999,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['out-of-range progress', '{"status":"parsing","progress":101,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['wrong message type', '{"status":"parsing","progress":25,"message":42,"created_at":"2026-08-14T00:02:00Z"}'],
    ['wrong created_at type', '{"status":"parsing","progress":25,"message":"开始解析","created_at":42}']
  ])('closes once and reports an error for invalid progress payload shape: %s', (_label, payload) => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
    const api = createJobsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    })
    const onEvent = vi.fn()
    const onError = vi.fn()

    api.subscribe('job-1', onEvent, onError)
    eventSource.emitRaw('progress', payload, '4')

    expect(onEvent).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledWith('Unable to receive job progress updates.')
    expect(eventSource.closeCalls).toBe(1)
  })

  it('continues delivering valid progress payloads with validated fields', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
    const api = createJobsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    })
    const onEvent = vi.fn()

    api.subscribe('job-1', onEvent, vi.fn())
    eventSource.emitRaw(
      'progress',
      '{"status":"checking_format","progress":50,"message":"正在检查格式","created_at":"2026-08-14T00:02:00+00:00"}',
      '9'
    )

    expect(onEvent).toHaveBeenCalledWith({
      sequence: 9,
      status: 'checking_format',
      progress: 50,
      message: '正在检查格式',
      created_at: '2026-08-14T00:02:00+00:00'
    })
    expect(eventSource.closeCalls).toBe(0)
  })

  it('closes the stream once on done even if unsubscribe is called later', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
    const api = createJobsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    })

    const unsubscribe = api.subscribe('job-1', vi.fn(), vi.fn())
    eventSource.emitControl('done')
    unsubscribe()

    expect(eventSource.closed).toBe(true)
    expect(eventSource.closeCalls).toBe(1)
  })

  it('closes the stream when explicitly unsubscribed', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
    const api = createJobsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    })

    const unsubscribe = api.subscribe('job-1', vi.fn(), vi.fn())
    unsubscribe()

    expect(eventSource.closed).toBe(true)
    expect(eventSource.closeCalls).toBe(1)
  })

  it('emits an expired terminal state and closes the event source', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
    const api = createJobsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    })
    const onEvent = vi.fn()

    api.subscribe('job-1', onEvent, vi.fn())
    eventSource.emitControl('expired')

    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'expired',
        progress: 0,
        message: '任务已过期'
      })
    )
    expect(eventSource.closed).toBe(true)
  })

  it('exports the exact backend status union', () => {
    expect(JOB_STATUS_VALUES).toEqual([
      'queued',
      'upload_validated',
      'parsing',
      'checking_format',
      'checking_sensitive',
      'checking_chinese',
      'checking_english',
      'completed',
      'partial',
      'failed',
      'expired'
    ])
  })
})
