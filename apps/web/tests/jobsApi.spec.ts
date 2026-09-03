import { describe, expect, it, vi } from 'vitest'

import {
  createJobsApi,
  JobResultExpiredError
} from '../src/api/jobs'
import { AnalyzeOptionsError } from '../src/api/analyzeOptions'
import {
  JOB_FILE_TYPE_VALUES,
  JOB_PROGRESS_STAGE_VALUES,
  JOB_STATUS_VALUES,
  type JobRead
} from '../src/types/jobs'
import type { AnalyzeOptions } from '../src/types/verification'

const ALL_JOB_FILE_TYPES = [
  'docx',
  'doc',
  'pdf',
  'txt',
  'rtf',
  'md',
  'csv'
] as const

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
  it.each(ALL_JOB_FILE_TYPES)(
    'posts %s uploads with the exact immutable options contract',
    async (fileType) => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
        source_name: `sample.${fileType}`,
        file_type: fileType,
        size_bytes: 6,
        status: 'queued',
        stage: 'queued',
        progress: 0,
        error_code: null,
        error_message: null,
        error_stage: null,
        error_retryable: null,
        created_at: '2026-08-14T00:00:00Z',
        expires_at: '2026-08-15T00:00:00Z'
      })
    })
    const api = createJobsApi({
      fetch: fetchMock,
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource
    })
    const file = new File(['body'], `sample.${fileType}`, { type: 'text/plain' })
    const options: AnalyzeOptions = {
      scenario: 'technical',
      enableSecurity: false,
      enableSensitive: true,
      enableAdExtreme: false,
      glossary: [
        { original: '', standard: '保留空字符串' },
        { original: 'AI', standard: '人工智能' }
      ],
      bannedWords: ['', '最好']
    }

    const job = await api.createJob(file, options)
    options.glossary[1].standard = '调用后变更'
    options.bannedWords.push('调用后新增')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/jobs', expect.objectContaining({ method: 'POST' }))
    expect(job.job_id).toBe('6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f')
    expect(job.file_type).toBe(fileType)
    expect(job.stage).toBe('queued')
    const body = fetchMock.mock.calls[0]?.[1]?.body as FormData
    expect((body.get('file') as File).name).toBe(`sample.${fileType}`)
    expect(body.get('scenario')).toBe('technical')
    expect(body.get('enable_security')).toBe('false')
    expect(body.get('enable_sensitive')).toBe('true')
    expect(body.get('enable_ad_extreme')).toBe('false')
    expect(body.get('custom_glossary')).toBe(
      '[{"original":"","standard":"保留空字符串"},{"original":"AI","standard":"人工智能"}]'
    )
    expect(body.get('banned_words')).toBe('["","最好"]')
  })

  it('serializes empty terminology arrays instead of omitting them', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
        source_name: 'sample.txt',
        file_type: 'txt',
        size_bytes: 6,
        status: 'queued',
        stage: 'queued',
        progress: 0,
        error_code: null,
        error_message: null,
        error_stage: null,
        error_retryable: null,
        created_at: '2026-08-14T00:00:00Z',
        expires_at: '2026-08-15T00:00:00Z'
      })
    })
    const api = createJobsApi({
      fetch: fetchMock,
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource
    })

    await api.createJob(new File(['body'], 'sample.txt'), {
      scenario: 'general',
      enableSecurity: true,
      enableSensitive: true,
      enableAdExtreme: false,
      glossary: [],
      bannedWords: []
    })

    const body = fetchMock.mock.calls[0]?.[1]?.body as FormData
    expect(body.get('custom_glossary')).toBe('[]')
    expect(body.get('banned_words')).toBe('[]')
  })

  it('rejects an invalid options snapshot before invoking fetch', async () => {
    const fetchMock = vi.fn()
    const api = createJobsApi({
      fetch: fetchMock,
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource
    })

    await expect(
      // @ts-expect-error Runtime callers can still supply an invalid snapshot.
      api.createJob(new File(['body'], 'sample.txt'), null)
    ).rejects.toBeInstanceOf(AnalyzeOptionsError)
    expect(fetchMock).not.toHaveBeenCalled()
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
      api.createJob(
        new File(['body'], 'large.txt', { type: 'text/plain' }),
        {
          scenario: 'general',
          enableSecurity: true,
          enableSensitive: true,
          enableAdExtreme: false,
          glossary: [],
          bannedWords: []
        }
      )
    ).rejects.toThrow('Upload exceeds the configured maximum size.')
  })

  it('loads the retained canonical result from the job result endpoint', async () => {
    const payload = {
      document_id: '11111111-1111-4111-8111-111111111111'
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload
    })
    const api = createJobsApi({
      fetch: fetchMock,
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource
    })

    const result = await api.getResult('job/with spaces')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job%2Fwith%20spaces/result'
    )
    expect(result).toBe(payload)
  })

  it('throws a typed expired-result error for HTTP 410', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 410,
      json: async () => ({
        detail: {
          code: 'job_result_expired',
          message: 'Job result has expired.'
        }
      })
    })
    const api = createJobsApi({
      fetch: fetchMock,
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource
    })

    const request = api.getResult('job-1')

    await expect(request).rejects.toBeInstanceOf(JobResultExpiredError)
    await expect(request).rejects.toMatchObject({
      status: 410,
      code: 'job_result_expired',
      message: 'Job result has expired.'
    })
  })

  it('keeps ordinary result failures distinct from expiration', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({
        detail: {
          code: 'job_result_pending',
          stage: 'finalizing',
          message: 'Job result is not available yet.',
          retryable: true
        }
      })
    })
    const api = createJobsApi({
      fetch: fetchMock,
      eventSourceFactory: (url) => new FakeEventSource(url) as unknown as EventSource
    })

    await expect(api.getResult('job-1')).rejects.toMatchObject({
      name: 'ApiRequestError',
      status: 409,
      code: 'job_result_pending',
      stage: 'finalizing',
      retryable: true,
      message: 'Job result is not available yet.'
    })
    await expect(api.getResult('job-1')).rejects.not.toBeInstanceOf(
      JobResultExpiredError
    )
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
      stage: 'completed',
      progress: 100,
      message: '处理完成',
      created_at: '2026-08-14T00:02:00Z'
    }, '3')

    expect(onEvent).toHaveBeenCalledTimes(1)
    expect(onEvent).toHaveBeenLastCalledWith(
      expect.objectContaining({
        sequence: 3,
        status: 'completed',
        stage: 'completed',
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
    ['missing created_at', '{"status":"parsing","stage":"parsing","progress":25,"message":"开始解析"}'],
    ['missing stage', '{"status":"parsing","progress":25,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['bad status', '{"status":"unknown","stage":"parsing","progress":25,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['bad stage', '{"status":"parsing","stage":"unknown","progress":25,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['non-finite progress', '{"status":"parsing","stage":"parsing","progress":1e999,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['out-of-range progress', '{"status":"parsing","stage":"parsing","progress":101,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['wrong message type', '{"status":"parsing","stage":"parsing","progress":25,"message":42,"created_at":"2026-08-14T00:02:00Z"}'],
    ['wrong created_at type', '{"status":"parsing","stage":"parsing","progress":25,"message":"开始解析","created_at":42}']
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
      '{"status":"checking_format","stage":"checking_format","progress":50,"message":"正在检查格式","created_at":"2026-08-14T00:02:00+00:00"}',
      '9'
    )

    expect(onEvent).toHaveBeenCalledWith({
      sequence: 9,
      status: 'checking_format',
      stage: 'checking_format',
      progress: 50,
      message: '正在检查格式',
      created_at: '2026-08-14T00:02:00+00:00'
    })
    expect(eventSource.closeCalls).toBe(0)
  })

  it.each([
    ['ocr', 'parsing'],
    ['finalizing', 'checking_english'],
    ['exporting', 'completed']
  ] as const)(
    'parses the derived %s stage without changing coarse status %s',
    (stage, status) => {
      const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
      const api = createJobsApi({
        fetch: vi.fn(),
        eventSourceFactory: () => eventSource as unknown as EventSource
      })
      const onEvent = vi.fn()

      api.subscribe('job-1', onEvent, vi.fn())
      eventSource.emit('progress', {
        status,
        stage,
        progress: 50,
        message: stage,
        created_at: '2026-08-14T00:02:00Z'
      })

      expect(onEvent).toHaveBeenCalledWith(
        expect.objectContaining({ status, stage })
      )
    }
  )

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

  it('exports the exact backend file-format and progress-stage unions', () => {
    const allFormats: readonly JobRead['file_type'][] = JOB_FILE_TYPE_VALUES
    expect(allFormats).toEqual(['docx', 'doc', 'pdf', 'txt', 'rtf', 'md', 'csv'])
    expect(JOB_PROGRESS_STAGE_VALUES).toEqual([
      'queued',
      'upload_validated',
      'parsing',
      'ocr',
      'checking_format',
      'checking_sensitive',
      'checking_chinese',
      'checking_english',
      'exporting',
      'finalizing',
      'completed',
      'partial',
      'failed',
      'expired'
    ])
  })
})
