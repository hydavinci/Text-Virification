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
const EVENT_SOURCE_CONNECTING = 0
const EVENT_SOURCE_CLOSED = 2

function buildCanonicalBackendResult(
  overrides: Record<string, unknown> = {}
) {
  return {
    verification_run_id: '22222222-2222-4222-8222-222222222222',
    document_id: '11111111-1111-4111-8111-111111111111',
    source_version:
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    source_name: 'sample.txt',
    file_type: 'txt',
    scenario: 'technical',
    text: '检查',
    blocks: [
      {
        block_id: 'p-0',
        kind: 'paragraph',
        text: '检查',
        global_start: 0,
        global_end: 2,
        block_start: 0,
        block_end: 2,
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
    metadata: { pdf: null },
    ocr_requirement: null,
    stats: {
      char_count: 2,
      char_count_no_space: 2,
      line_count: 1,
      paragraph_count: 1,
      language: 'zh',
      primary_count: 2,
      primary_label: '总字数'
    },
    issues: [],
    summary: {
      total: 0,
      by_type: {},
      by_severity: {},
      by_rule: {},
      by_layer: {},
      llm_review: null
    },
    execution_mode: 'asynchronous',
    analysis_mode: 'local_only',
    dictionary_versions: {},
    degradation: { is_degraded: false, reasons: [] },
    ...overrides
  }
}

class FakeEventSource {
  public onerror: ((event: Event) => void) | null = null
  public readyState = EVENT_SOURCE_CONNECTING

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
    this.readyState = EVENT_SOURCE_CLOSED
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

  emitError(readyState = EVENT_SOURCE_CONNECTING) {
    this.readyState = readyState
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
  it('binds the default browser fetch receiver for job submission', async () => {
    const originalFetch = globalThis.fetch
    const strictFetch = vi.fn(async function (this: unknown) {
      if (this !== globalThis) {
        throw new TypeError('Illegal invocation')
      }
      return {
        ok: true,
        json: async () => ({
          job_id: '6d96fe0f-f4fc-4b43-90fd-68e5bd09f21f',
          source_name: 'sample.pdf',
          file_type: 'pdf',
          size_bytes: 3,
          status: 'queued',
          stage: 'queued',
          progress: 0,
          error_code: null,
          error_message: null,
          error_stage: null,
          error_retryable: null,
          created_at: '2026-09-03T04:00:00Z',
          expires_at: '2026-09-04T04:00:00Z'
        })
      } as Response
    })
    Object.defineProperty(globalThis, 'fetch', {
      configurable: true,
      value: strictFetch
    })
    try {
      const api = createJobsApi()

      await api.createJob(new File(['pdf'], 'sample.pdf'), {
        scenario: 'general',
        enableSecurity: true,
        enableSensitive: true,
        enableAdExtreme: false,
        glossary: [],
        bannedWords: []
      })

      expect(strictFetch).toHaveBeenCalledTimes(1)
    } finally {
      Object.defineProperty(globalThis, 'fetch', {
        configurable: true,
        value: originalFetch
      })
    }
  })

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
        { original: '保留空字符串', standard: '' },
        { original: 'AI', standard: '人工智能' }
      ],
      bannedWords: ['最好']
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
      '[{"original":"保留空字符串","standard":""},{"original":"AI","standard":"人工智能"}]'
    )
    expect(body.get('banned_words')).toBe('["最好"]')
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

  it('rejects a malformed successful create-job response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        job_id: 'not-a-uuid',
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
      eventSourceFactory: (url) =>
        new FakeEventSource(url) as unknown as EventSource
    })

    await expect(
      api.createJob(new File(['body'], 'sample.txt'), {
        scenario: 'general',
        enableSecurity: true,
        enableSensitive: true,
        enableAdExtreme: false,
        glossary: [],
        bannedWords: []
      })
    ).rejects.toThrow('Invalid job response.')
  })

  it('validates and adapts the authoritative retained-result response', async () => {
    const payload = buildCanonicalBackendResult()
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
    expect(result).toMatchObject({
      success: true,
      filename: 'sample.txt',
      source_name: 'sample.txt',
      file_type: 'txt',
      file_id: '11111111-1111-4111-8111-111111111111',
      file_ext: '.txt',
      document_id: '11111111-1111-4111-8111-111111111111',
      execution_mode: 'asynchronous'
    })
    expect(result).not.toHaveProperty('metadata')
    expect(result).not.toHaveProperty('ocr_requirement')
  })

  it('adapts canonical backend issue offsets to the workspace aliases', async () => {
    const issue = {
      issue_id: '33333333-3333-4333-8333-333333333333',
      document_id: '11111111-1111-4111-8111-111111111111',
      verification_run_id: '22222222-2222-4222-8222-222222222222',
      block_id: 'p-0',
      page: null,
      start: 0,
      end: 1,
      block_start: 0,
      block_end: 1,
      original: '检',
      suggestion: '校',
      alternatives: [],
      type: 'typo',
      severity: 'warning',
      layer: 'character',
      message: '疑似错别字',
      description: '疑似错别字',
      rule_id: 'cn_typo',
      rule_version: '1',
      source: 'test',
      source_version: '1',
      confidence: 0.8,
      auto_fixable: true,
      context: '检查',
      review: null,
      review_reason: null
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () =>
        buildCanonicalBackendResult({
          issues: [issue],
          summary: {
            total: 1,
            by_type: { typo: 1 },
            by_severity: { warning: 1 },
            by_rule: { cn_typo: 1 },
            by_layer: { character: 1 },
            llm_review: null
          }
        })
    })
    const api = createJobsApi({
      fetch: fetchMock,
      eventSourceFactory: (url) =>
        new FakeEventSource(url) as unknown as EventSource
    })

    const result = await api.getResult('job-1')

    expect(result.issues[0]).toMatchObject({
      start: 0,
      end: 1,
      position: 0,
      end_position: 1
    })
  })

  it.each([-0.01, 1.01])(
    'rejects retained-result issue confidence %s outside the backend range',
    async (confidence) => {
      const issue = {
        issue_id: '33333333-3333-4333-8333-333333333333',
        document_id: '11111111-1111-4111-8111-111111111111',
        verification_run_id: '22222222-2222-4222-8222-222222222222',
        block_id: 'p-0',
        page: null,
        start: 0,
        end: 1,
        block_start: 0,
        block_end: 1,
        original: '检',
        suggestion: '校',
        alternatives: [],
        type: 'typo',
        severity: 'warning',
        layer: 'character',
        message: '疑似错别字',
        description: '疑似错别字',
        rule_id: 'cn_typo',
        rule_version: '1',
        source: 'test',
        source_version: '1',
        confidence,
        auto_fixable: true,
        context: '检查',
        review: null,
        review_reason: null
      }
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () =>
          buildCanonicalBackendResult({
            issues: [issue],
            summary: {
              total: 1,
              by_type: { typo: 1 },
              by_severity: { warning: 1 },
              by_rule: { cn_typo: 1 },
              by_layer: { character: 1 },
              llm_review: null
            }
          })
      })
      const api = createJobsApi({
        fetch: fetchMock,
        eventSourceFactory: (url) =>
          new FakeEventSource(url) as unknown as EventSource
      })

      await expect(api.getResult('job-1')).rejects.toThrow(
        'Invalid verification result response.'
      )
    }
  )

  it('rejects a malformed successful retained-result response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () =>
        buildCanonicalBackendResult({
          summary: {
            total: 1,
            by_type: {},
            by_severity: {},
            by_rule: {},
            by_layer: {},
            llm_review: null
          }
        })
    })
    const api = createJobsApi({
      fetch: fetchMock,
      eventSourceFactory: (url) =>
        new FakeEventSource(url) as unknown as EventSource
    })

    await expect(api.getResult('job-1')).rejects.toThrow(
      'Invalid verification result response.'
    )
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
    expect(onError).toHaveBeenCalledWith({
      kind: 'transient',
      message: 'Connection interrupted. Waiting to reconnect…'
    })
    expect(eventSource.closed).toBe(false)
    expect(eventSource.closeCalls).toBe(0)
  })

  it('treats a permanently closed EventSource connection as fatal', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
    const api = createJobsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    })
    const onError = vi.fn()

    api.subscribe('job-1', vi.fn(), onError)
    eventSource.emitError(EVENT_SOURCE_CLOSED)

    expect(onError).toHaveBeenCalledWith({
      kind: 'fatal',
      message: 'Unable to receive job progress updates.'
    })
    expect(eventSource.closed).toBe(true)
    expect(eventSource.closeCalls).toBe(1)
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
    eventSource.emitRaw('progress', '{"status":"parsing",', '1')

    expect(onEvent).not.toHaveBeenCalled()
    expect(onError).toHaveBeenCalledWith({
      kind: 'fatal',
      message: 'Unable to receive job progress updates.'
    })
    expect(eventSource.closeCalls).toBe(1)
  })

  it.each([
    ['missing created_at', '{"status":"parsing","stage":"parsing","progress":25,"message":"开始解析"}'],
    ['missing stage', '{"status":"parsing","progress":25,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['bad status', '{"status":"unknown","stage":"parsing","progress":25,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['bad stage', '{"status":"parsing","stage":"unknown","progress":25,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['non-finite progress', '{"status":"parsing","stage":"parsing","progress":1e999,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['fractional progress', '{"status":"parsing","stage":"parsing","progress":25.5,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['out-of-range progress', '{"status":"parsing","stage":"parsing","progress":101,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['queued with parsing stage', '{"status":"queued","stage":"parsing","progress":0,"message":"作业已创建","created_at":"2026-08-14T00:02:00Z"}'],
    ['pre-OCR parsing with OCR stage', '{"status":"parsing","stage":"ocr","progress":39,"message":"开始解析","created_at":"2026-08-14T00:02:00Z"}'],
    ['OCR parsing with parsing stage', '{"status":"parsing","stage":"parsing","progress":40,"message":"正在进行 OCR","created_at":"2026-08-14T00:02:00Z"}'],
    ['pre-finalizing English check with finalizing stage', '{"status":"checking_english","stage":"finalizing","progress":94,"message":"正在检查英文","created_at":"2026-08-14T00:02:00Z"}'],
    ['finalizing English check with checking stage', '{"status":"checking_english","stage":"checking_english","progress":95,"message":"正在保存结果","created_at":"2026-08-14T00:02:00Z"}'],
    ['failed status with finalizing stage', '{"status":"failed","stage":"finalizing","progress":95,"message":"处理失败","created_at":"2026-08-14T00:02:00Z"}'],
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
    expect(onError).toHaveBeenCalledWith({
      kind: 'fatal',
      message: 'Unable to receive job progress updates.'
    })
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
    ['queued', 'queued', 0],
    ['upload_validated', 'upload_validated', 10],
    ['parsing', 'parsing', 25],
    ['parsing', 'ocr', 40],
    ['checking_format', 'checking_format', 50],
    ['checking_sensitive', 'checking_sensitive', 65],
    ['checking_chinese', 'checking_chinese', 80],
    ['checking_english', 'checking_english', 90],
    ['checking_english', 'finalizing', 95],
    ['completed', 'completed', 100],
    ['partial', 'partial', 95],
    ['failed', 'failed', 65],
    ['expired', 'expired', 65],
    ['completed', 'exporting', 100],
    ['completed', 'finalizing', 100],
    ['partial', 'exporting', 95],
    ['partial', 'finalizing', 95]
  ] as const)(
    'accepts backend-published progress relationship %s/%s at %i',
    (status, stage, progress) => {
      const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
      const api = createJobsApi({
        fetch: vi.fn(),
        eventSourceFactory: () => eventSource as unknown as EventSource
      })
      const onEvent = vi.fn()

      api.subscribe('job-1', onEvent, vi.fn())
      eventSource.emit(
        'progress',
        {
          status,
          stage,
          progress,
          message: stage,
          created_at: '2026-08-14T00:02:00Z'
        },
        '1'
      )

      expect(onEvent).toHaveBeenCalledWith(
        expect.objectContaining({ status, stage, progress })
      )
      expect(eventSource.closeCalls).toBe(0)
    }
  )

  it.each(['', '-1', '1.5', '3junk', '9007199254740992'])(
    'treats an invalid SSE replay id as a fatal protocol error: %s',
    (lastEventId) => {
      const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
      const api = createJobsApi({
        fetch: vi.fn(),
        eventSourceFactory: () => eventSource as unknown as EventSource
      })
      const onEvent = vi.fn()
      const onError = vi.fn()

      api.subscribe('job-1', onEvent, onError)
      eventSource.emit(
        'progress',
        {
          status: 'parsing',
          stage: 'parsing',
          progress: 25,
          message: '开始解析',
          created_at: '2026-08-14T00:02:00Z'
        },
        lastEventId
      )

      expect(onEvent).not.toHaveBeenCalled()
      expect(onError).toHaveBeenCalledWith({
        kind: 'fatal',
        message: 'Unable to receive job progress updates.'
      })
      expect(eventSource.closeCalls).toBe(1)
    }
  )

  it('ignores duplicate and decreasing SSE sequences without regressing progress', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
    const api = createJobsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    })
    const onEvent = vi.fn()

    api.subscribe('job-1', onEvent, vi.fn())
    eventSource.emit(
      'progress',
      {
        status: 'checking_format',
        stage: 'checking_format',
        progress: 50,
        message: '正在检查格式',
        created_at: '2026-08-14T00:02:00Z'
      },
      '5'
    )
    eventSource.emit(
      'progress',
      {
        status: 'parsing',
        stage: 'parsing',
        progress: 25,
        message: '重复事件',
        created_at: '2026-08-14T00:01:00Z'
      },
      '5'
    )
    eventSource.emit(
      'progress',
      {
        status: 'parsing',
        stage: 'parsing',
        progress: 10,
        message: '倒序事件',
        created_at: '2026-08-14T00:00:00Z'
      },
      '4'
    )
    eventSource.emit(
      'progress',
      {
        status: 'checking_sensitive',
        stage: 'checking_sensitive',
        progress: 60,
        message: '继续处理',
        created_at: '2026-08-14T00:03:00Z'
      },
      '6'
    )

    expect(onEvent).toHaveBeenCalledTimes(2)
    expect(onEvent.mock.calls.map(([event]) => event.sequence)).toEqual([5, 6])
    expect(onEvent).toHaveBeenLastCalledWith(
      expect.objectContaining({
        status: 'checking_sensitive',
        progress: 60,
        message: '继续处理'
      })
    )
    expect(eventSource.closeCalls).toBe(0)
  })

  it.each([
    ['ocr', 'parsing', 40],
    ['finalizing', 'checking_english', 95],
    ['exporting', 'completed', 100]
  ] as const)(
    'parses the derived %s stage without changing coarse status %s',
    (stage, status, progress) => {
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
        progress,
        message: stage,
        created_at: '2026-08-14T00:02:00Z'
      }, '1')

      expect(onEvent).toHaveBeenCalledWith(
        expect.objectContaining({ status, stage })
      )
    }
  )

  it('reports premature done without terminal progress as a fatal protocol error', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
    const api = createJobsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    })
    const onError = vi.fn()

    api.subscribe('job-1', vi.fn(), onError)
    eventSource.emitControl('done')

    expect(onError).toHaveBeenCalledWith({
      kind: 'fatal',
      message: 'Unable to receive job progress updates.'
    })
    expect(eventSource.closeCalls).toBe(1)
  })

  it('closes the stream once on done after terminal progress even if unsubscribe is called later', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/events')
    const api = createJobsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    })
    const onError = vi.fn()

    const unsubscribe = api.subscribe('job-1', vi.fn(), onError)
    eventSource.emit(
      'progress',
      {
        status: 'completed',
        stage: 'completed',
        progress: 100,
        message: '处理完成',
        created_at: '2026-08-14T00:02:00Z'
      },
      '1'
    )
    eventSource.emitControl('done')
    unsubscribe()

    expect(onError).not.toHaveBeenCalled()
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
