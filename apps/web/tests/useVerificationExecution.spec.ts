import { flushPromises } from '@vue/test-utils'
import { effectScope } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import {
  createJobsApi,
  JobResultExpiredError,
  type JobsApi,
  type JobSubscriptionError
} from '../src/api/jobs'
import type { VerificationApi } from '../src/api/verification'
import { useVerificationExecution } from '../src/composables/useVerificationExecution'
import { useVerificationWorkspace } from '../src/composables/useVerificationWorkspace'
import type { JobProgressEvent, JobRead } from '../src/types/jobs'
import type {
  AnalyzeOptions,
  VerificationResult
} from '../src/types/verification'

const options: AnalyzeOptions = {
  scenario: 'technical',
  enableSecurity: true,
  enableSensitive: false,
  enableAdExtreme: true,
  glossary: [{ original: 'AI', standard: '人工智能' }],
  bannedWords: ['最好']
}
const EVENT_SOURCE_CLOSED = 2

class IntegratedEventSource {
  public onerror: ((event: Event) => void) | null = null
  public readyState = 0

  private listeners = new Map<
    string,
    Set<(event: MessageEvent<string>) => void>
  >()

  addEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject
  ): void {
    const callback =
      typeof listener === 'function'
        ? (listener as (event: MessageEvent<string>) => void)
        : ((event: MessageEvent<string>) => listener.handleEvent(event))
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set())
    }
    this.listeners.get(type)?.add(callback)
  }

  removeEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject
  ): void {
    const callback =
      typeof listener === 'function'
        ? (listener as (event: MessageEvent<string>) => void)
        : ((event: MessageEvent<string>) => listener.handleEvent(event))
    this.listeners.get(type)?.delete(callback)
  }

  close(): void {
    this.readyState = EVENT_SOURCE_CLOSED
  }

  emitControl(type: string): void {
    const event = {
      data: JSON.stringify({ event: type })
    } as MessageEvent<string>
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event)
    }
  }

  emitProgress(event: JobProgressEvent): void {
    const messageEvent = {
      data: JSON.stringify(event),
      lastEventId: String(event.sequence)
    } as MessageEvent<string>
    for (const listener of this.listeners.get('progress') ?? []) {
      listener(messageEvent)
    }
  }

  emitClosedError(): void {
    this.readyState = EVENT_SOURCE_CLOSED
    this.onerror?.(new Event('error'))
  }
}

function buildResult(
  overrides: Partial<VerificationResult> = {}
): VerificationResult {
  return {
    success: true,
    filename: 'sample.txt',
    source_name: 'sample.txt',
    file_type: 'txt',
    text: '检查文本',
    blocks: [
      {
        block_id: 'p-0',
        kind: 'paragraph',
        text: '检查文本',
        global_start: 0,
        global_end: 4,
        block_start: 0,
        block_end: 4,
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
      char_count: 4,
      char_count_no_space: 4,
      line_count: 1,
      paragraph_count: 1,
      language: 'zh',
      primary_count: 4,
      primary_label: '总字数'
    },
    issues: [],
    summary: {
      total: 0,
      by_type: {},
      by_severity: {},
      by_rule: {},
      by_layer: {}
    },
    file_id: null,
    file_ext: null,
    document_id: '11111111-1111-4111-8111-111111111111',
    verification_run_id: '22222222-2222-4222-8222-222222222222',
    source_version:
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    execution_mode: 'synchronous',
    analysis_mode: 'local_only',
    dictionary_versions: {},
    degradation: { is_degraded: false, reasons: [] },
    scenario: 'technical',
    ...overrides
  }
}

function buildIssue(
  confidence: number
): VerificationResult['issues'][number] {
  return {
    issue_id: '44444444-4444-4444-8444-444444444444',
    document_id: '11111111-1111-4111-8111-111111111111',
    verification_run_id: '22222222-2222-4222-8222-222222222222',
    block_id: 'p-0',
    page: null,
    start: 0,
    end: 1,
    block_start: 0,
    block_end: 1,
    type: 'typo',
    severity: 'warning',
    original: '检',
    suggestion: '校',
    alternatives: [],
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
    position: 0,
    end_position: 1,
    review: null,
    review_reason: null
  }
}

function buildJob(overrides: Partial<JobRead> = {}): JobRead {
  return {
    job_id: '33333333-3333-4333-8333-333333333333',
    source_name: 'sample.pdf',
    file_type: 'pdf',
    size_bytes: 12,
    status: 'queued',
    stage: 'queued',
    progress: 0,
    error_code: null,
    error_message: null,
    error_stage: null,
    error_retryable: null,
    created_at: '2026-09-03T00:00:00Z',
    expires_at: '2026-09-04T00:00:00Z',
    ...overrides
  }
}

function buildEvent(
  status: JobProgressEvent['status'],
  overrides: Partial<JobProgressEvent> = {}
): JobProgressEvent {
  return {
    sequence: 2,
    status,
    stage: status,
    progress: status === 'completed' || status === 'partial' ? 100 : 40,
    message: status,
    created_at: '2026-09-03T00:01:00Z',
    ...overrides
  }
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

function createHarness(overrides: {
  job?: JobRead
  result?: VerificationResult
  getResult?: JobsApi['getResult']
  verificationApi?: VerificationApi | null
  fileExecutionMode?: 'direct' | 'jobs'
} = {}) {
  let onEvent: ((event: JobProgressEvent) => void) | null = null
  let onError: ((error: JobSubscriptionError) => void) | null = null
  const close = vi.fn()
  const jobsApi: JobsApi = {
    createJob: vi.fn().mockResolvedValue(overrides.job ?? buildJob()),
    getResult:
      overrides.getResult ??
      vi.fn().mockResolvedValue(
        overrides.result ??
          buildResult({
            execution_mode: 'asynchronous',
            file_id: '33333333-3333-4333-8333-333333333333',
            file_ext: 'pdf'
          })
      ),
    subscribe: vi.fn((_jobId, nextEvent, nextError) => {
      onEvent = nextEvent
      onError = nextError
      return close
    })
  }

  const verificationApi =
    overrides.verificationApi === undefined
      ? null
      : overrides.verificationApi
  const execution = useVerificationExecution({
    jobsApi,
    verificationApi,
    fileExecutionMode: overrides.fileExecutionMode
  })
  return {
    execution,
    jobsApi,
    close,
    emit: (event: JobProgressEvent) => onEvent?.(event),
    emitError: (error: JobSubscriptionError) => onError?.(error)
  }
}

function createIntegratedHarness(result?: VerificationResult) {
  const eventSource = new IntegratedEventSource()
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => buildJob()
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () =>
        result ?? buildResult({ execution_mode: 'asynchronous' })
    })
  const jobsApi = createJobsApi({
    fetch: fetchMock,
    eventSourceFactory: () => eventSource as unknown as EventSource
  })
  return {
    eventSource,
    execution: useVerificationExecution({
      jobsApi,
      verificationApi: null
    })
  }
}

describe('useVerificationExecution', () => {
  it('loads the canonical result exactly once after a completed event', async () => {
    const harness = createHarness()

    await harness.execution.analyzeFile(new File(['pdf'], 'sample.pdf'), options)
    harness.emit(
      buildEvent('completed', {
        stage: 'completed',
        message: '处理完成'
      })
    )
    await flushPromises()

    expect(harness.jobsApi.getResult).toHaveBeenCalledTimes(1)
    expect(harness.jobsApi.getResult).toHaveBeenCalledWith(
      '33333333-3333-4333-8333-333333333333'
    )
    expect(harness.execution.state.value).toBe('completed')
    expect(harness.execution.result.value?.document_id).toBe(
      '11111111-1111-4111-8111-111111111111'
    )
  })

  it('loads a retained partial result and preserves warning metadata', async () => {
    const harness = createHarness()

    await harness.execution.analyzeFile(new File(['pdf'], 'sample.pdf'), options)
    harness.emit(
      buildEvent('partial', {
        stage: 'partial',
        progress: 95,
        message: '语义复核不可用，已保留本地检查结果'
      })
    )
    await flushPromises()

    expect(harness.jobsApi.getResult).toHaveBeenCalledTimes(1)
    expect(harness.execution.state.value).toBe('completed')
    expect(harness.execution.jobStatus.value).toBe('partial')
    expect(harness.execution.progress.value).toBe(95)
    expect(harness.execution.message.value).toBe(
      '语义复核不可用，已保留本地检查结果'
    )
  })

  it('does not publish completed before the canonical result is loaded', async () => {
    const pending = createDeferred<VerificationResult>()
    const harness = createHarness({
      getResult: vi.fn().mockReturnValue(pending.promise)
    })

    await harness.execution.analyzeFile(new File(['pdf'], 'sample.pdf'), options)
    harness.emit(buildEvent('completed'))
    await flushPromises()

    expect(harness.execution.state.value).toBe('processing')
    expect(harness.execution.result.value).toBeNull()

    pending.resolve(buildResult({ execution_mode: 'asynchronous' }))
    await flushPromises()
    expect(harness.execution.state.value).toBe('completed')
  })

  it('maps an expired result fetch to expired without publishing a result', async () => {
    const harness = createHarness({
      getResult: vi.fn().mockRejectedValue(
        new JobResultExpiredError(
          410,
          'job_result_expired',
          'Job result has expired.'
        )
      )
    })

    await harness.execution.analyzeFile(new File(['pdf'], 'sample.pdf'), options)
    harness.emit(buildEvent('completed'))
    await flushPromises()

    expect(harness.execution.state.value).toBe('expired')
    expect(harness.execution.result.value).toBeNull()
    expect(harness.execution.error.value?.message).toBe(
      'Job result has expired.'
    )
  })

  it.each([
    ['completed', 100],
    ['partial', 95]
  ] as const)(
    'replaces %s SSE presentation with coherent expired metadata when the deferred result fetch returns 410',
    async (terminalStatus, terminalProgress) => {
      const pending = createDeferred<VerificationResult>()
      const harness = createHarness({
        getResult: vi.fn().mockReturnValue(pending.promise)
      })

      await harness.execution.analyzeFile(
        new File(['pdf'], 'sample.pdf'),
        options
      )
      harness.emit(
        buildEvent(terminalStatus, {
          stage: terminalStatus,
          progress: terminalProgress,
          message:
            terminalStatus === 'partial'
              ? '语义复核不可用，已保留本地检查结果'
              : '处理完成'
        })
      )
      expect(harness.execution.jobStatus.value).toBe(terminalStatus)

      pending.reject(
        new JobResultExpiredError(
          410,
          'job_result_expired',
          'Job result has expired.',
          'expired',
          false
        )
      )
      await flushPromises()

      expect(harness.execution.state.value).toBe('expired')
      expect(harness.execution.jobStatus.value).toBe('expired')
      expect(harness.execution.stage.value).toBe('expired')
      expect(harness.execution.progress.value).toBe(terminalProgress)
      expect(harness.execution.message.value).toBe('Job result has expired.')
      expect(harness.execution.job.value).toMatchObject({
        status: 'expired',
        stage: 'expired',
        progress: terminalProgress,
        error_code: 'job_result_expired',
        error_message: 'Job result has expired.',
        error_stage: 'expired',
        error_retryable: false
      })
      expect(harness.execution.result.value).toBeNull()
    }
  )

  it('maps an expired event to expired without fetching a result', async () => {
    const harness = createHarness()

    await harness.execution.analyzeFile(new File(['pdf'], 'sample.pdf'), options)
    harness.emit(
      buildEvent('expired', {
        stage: 'expired',
        progress: 0,
        message: '任务已过期'
      })
    )
    await flushPromises()

    expect(harness.execution.state.value).toBe('expired')
    expect(harness.jobsApi.getResult).not.toHaveBeenCalled()
  })

  it('maps failed events to failed without fetching a result', async () => {
    const harness = createHarness()

    await harness.execution.analyzeFile(new File(['pdf'], 'sample.pdf'), options)
    harness.emit(
      buildEvent('failed', {
        stage: 'failed',
        message: 'OCR 处理失败'
      })
    )
    await flushPromises()

    expect(harness.execution.state.value).toBe('failed')
    expect(harness.execution.error.value?.message).toBe('OCR 处理失败')
    expect(harness.jobsApi.getResult).not.toHaveBeenCalled()
  })

  it('handles duplicate result-bearing terminal events idempotently', async () => {
    const pending = createDeferred<VerificationResult>()
    const getResult = vi.fn().mockReturnValue(pending.promise)
    const harness = createHarness({ getResult })

    await harness.execution.analyzeFile(new File(['pdf'], 'sample.pdf'), options)
    harness.emit(buildEvent('completed'))
    harness.emit(buildEvent('completed', { sequence: 3 }))
    harness.emit(buildEvent('partial', { sequence: 4 }))
    await flushPromises()

    expect(getResult).toHaveBeenCalledTimes(1)
    pending.resolve(buildResult({ execution_mode: 'asynchronous' }))
    await flushPromises()
    expect(harness.execution.state.value).toBe('completed')
  })

  it('ignores late connection errors after a result-bearing terminal event', async () => {
    const pending = createDeferred<VerificationResult>()
    const harness = createHarness({
      getResult: vi.fn().mockReturnValue(pending.promise)
    })

    await harness.execution.analyzeFile(new File(['pdf'], 'sample.pdf'), options)
    harness.emit(
      buildEvent('completed', {
        message: '处理完成'
      })
    )
    harness.emitError({
      kind: 'transient',
      message: 'Connection interrupted. Waiting to reconnect…'
    })
    await flushPromises()

    expect(harness.execution.message.value).toBe('处理完成')
    expect(harness.execution.error.value).toBeNull()

    pending.resolve(buildResult({ execution_mode: 'asynchronous' }))
    await flushPromises()
    harness.emitError({ kind: 'transient', message: 'late' })
    expect(harness.execution.state.value).toBe('completed')
    expect(harness.execution.error.value).toBeNull()
  })

  it('fails and releases active execution on a fatal SSE protocol error', async () => {
    const harness = createHarness()

    await harness.execution.analyzeFile(new File(['pdf'], 'sample.pdf'), options)
    harness.emitError({
      kind: 'fatal',
      message: 'Unable to receive job progress updates.'
    })

    expect(harness.execution.state.value).toBe('failed')
    expect(harness.execution.isActive.value).toBe(false)
    expect(harness.execution.error.value?.message).toBe(
      'Unable to receive job progress updates.'
    )
    expect(harness.execution.connectionMessage.value).toBeNull()
    expect(harness.close).toHaveBeenCalledTimes(1)
  })

  it.each([
    ['premature done', (source: IntegratedEventSource) => source.emitControl('done')],
    ['a permanently closed connection', (source: IntegratedEventSource) => source.emitClosedError()]
  ])('integrates JobsApi fatal handling for %s', async (_label, trigger) => {
    const harness = createIntegratedHarness()

    await harness.execution.analyzeFile(
      new File(['pdf'], 'sample.pdf'),
      options
    )
    trigger(harness.eventSource)

    expect(harness.execution.state.value).toBe('failed')
    expect(harness.execution.isActive.value).toBe(false)
    expect(harness.execution.error.value?.message).toBe(
      'Unable to receive job progress updates.'
    )
  })

  it('ignores stale JobsApi done and closed-error callbacks after reset', async () => {
    const harness = createIntegratedHarness()

    await harness.execution.analyzeFile(
      new File(['pdf'], 'sample.pdf'),
      options
    )
    harness.execution.reset()
    harness.eventSource.emitControl('done')
    harness.eventSource.emitClosedError()

    expect(harness.execution.state.value).toBe('idle')
    expect(harness.execution.error.value).toBeNull()
    expect(harness.execution.connectionMessage.value).toBeNull()
  })

  it('reuses one JobsApi-validated snapshot through execution and workspace loading', async () => {
    const harness = createIntegratedHarness()
    const workspace = useVerificationWorkspace()

    await harness.execution.analyzeFile(
      new File(['pdf'], 'sample.pdf'),
      options
    )
    harness.eventSource.emitProgress(buildEvent('completed'))
    await flushPromises()
    const published = harness.execution.result.value
    if (published === null) {
      throw new Error('Expected a published result.')
    }

    workspace.loadResult(published)

    expect(workspace.result.value).toBe(published)
  })

  it('invalidates an unresolved create request on reset', async () => {
    const pending = createDeferred<JobRead>()
    const harness = createHarness()
    vi.mocked(harness.jobsApi.createJob).mockReturnValue(pending.promise)

    const request = harness.execution.analyzeFile(
      new File(['pdf'], 'sample.pdf'),
      options
    )
    harness.execution.reset()
    pending.resolve(buildJob())
    await request
    await flushPromises()

    expect(harness.jobsApi.subscribe).not.toHaveBeenCalled()
    expect(harness.execution.state.value).toBe('idle')
    expect(harness.execution.result.value).toBeNull()
  })

  it('invalidates an unresolved result fetch on reset and closes the subscription', async () => {
    const pending = createDeferred<VerificationResult>()
    const harness = createHarness({
      getResult: vi.fn().mockReturnValue(pending.promise)
    })

    await harness.execution.analyzeFile(new File(['pdf'], 'sample.pdf'), options)
    harness.emit(buildEvent('completed'))
    harness.execution.reset()
    pending.resolve(buildResult({ execution_mode: 'asynchronous' }))
    await flushPromises()

    expect(harness.close).toHaveBeenCalledTimes(1)
    expect(harness.execution.state.value).toBe('idle')
    expect(harness.execution.result.value).toBeNull()
  })

  it('ignores a stale direct result before applying its result transform', async () => {
    const pending = createDeferred<VerificationResult>()
    const transformResult = vi.fn((result: VerificationResult) => result)
    const verificationApi: VerificationApi = {
      analyzeText: vi.fn().mockReturnValue(pending.promise),
      analyzeFile: vi.fn(),
      exportReport: vi.fn(),
      exportOriginal: vi.fn(),
      persistRevision: vi.fn(),
      exportJob: vi.fn()
    }
    const harness = createHarness({ verificationApi })

    const request = harness.execution.analyzeText(
      '检查文本',
      options,
      transformResult
    )
    harness.execution.reset()
    pending.resolve(buildResult())
    await request
    await flushPromises()

    expect(transformResult).not.toHaveBeenCalled()
    expect(harness.execution.state.value).toBe('idle')
    expect(harness.execution.result.value).toBeNull()
  })

  it('uses jobs for files when the workspace requests asynchronous execution', async () => {
    const verificationApi: VerificationApi = {
      analyzeText: vi.fn(),
      analyzeFile: vi.fn(),
      exportReport: vi.fn(),
      exportOriginal: vi.fn(),
      persistRevision: vi.fn(),
      exportJob: vi.fn()
    }
    const harness = createHarness({
      verificationApi,
      fileExecutionMode: 'jobs'
    })
    const file = new File(['pdf'], 'sample.pdf')

    await harness.execution.analyzeFile(file, options)

    expect(harness.jobsApi.createJob).toHaveBeenCalledWith(file, options)
    expect(verificationApi.analyzeFile).not.toHaveBeenCalled()
    expect(harness.execution.state.value).toBe('processing')
  })

  it('disposes subscriptions with the owning Vue scope and ignores late results', async () => {
    const pending = createDeferred<VerificationResult>()
    const close = vi.fn()
    let emit = (_event: JobProgressEvent): void => {
      throw new Error('Subscription was not established.')
    }
    const jobsApi: JobsApi = {
      createJob: vi.fn().mockResolvedValue(buildJob()),
      getResult: vi.fn().mockReturnValue(pending.promise),
      subscribe: vi.fn((_jobId, onEvent) => {
        emit = onEvent
        return close
      })
    }
    const scope = effectScope()
    const execution = scope.run(() =>
      useVerificationExecution({ jobsApi, verificationApi: null })
    )
    if (!execution) {
      throw new Error('Expected execution composable.')
    }

    await execution.analyzeFile(new File(['pdf'], 'sample.pdf'), options)
    emit(buildEvent('completed'))
    scope.stop()
    pending.resolve(buildResult({ execution_mode: 'asynchronous' }))
    await flushPromises()

    expect(close).toHaveBeenCalledTimes(1)
    expect(execution.result.value).toBeNull()
    expect(execution.state.value).not.toBe('completed')
  })

  it('prevents rapid duplicate direct-text submissions before invoking an API twice', async () => {
    const pending = createDeferred<VerificationResult>()
    const verificationApi: VerificationApi = {
      analyzeText: vi.fn().mockReturnValue(pending.promise),
      analyzeFile: vi.fn(),
      exportReport: vi.fn(),
      exportOriginal: vi.fn(),
      persistRevision: vi.fn(),
      exportJob: vi.fn()
    }
    const harness = createHarness({ verificationApi })

    const first = harness.execution.analyzeText('第一次', options)
    const second = harness.execution.analyzeText('第二次', options)
    await flushPromises()

    expect(verificationApi.analyzeText).toHaveBeenCalledTimes(1)
    pending.resolve(buildResult())
    await Promise.all([first, second])
  })

  it('prevents rapid duplicate asynchronous file submissions while processing', async () => {
    const harness = createHarness()
    const first = new File(['first'], 'first.pdf')
    const second = new File(['second'], 'second.pdf')

    await harness.execution.analyzeFile(first, options)
    await harness.execution.analyzeFile(second, options)

    expect(harness.jobsApi.createJob).toHaveBeenCalledTimes(1)
    expect(harness.jobsApi.createJob).toHaveBeenCalledWith(
      first,
      expect.any(Object)
    )
  })

  it('publishes direct text and synchronous files through the same completed state without SSE', async () => {
    const textResult = buildResult({ filename: 'direct.txt' })
    const fileResult = buildResult({ filename: 'direct.docx', file_type: 'docx' })
    const verificationApi: VerificationApi = {
      analyzeText: vi.fn().mockResolvedValue(textResult),
      analyzeFile: vi.fn().mockResolvedValue(fileResult),
      exportReport: vi.fn(),
      exportOriginal: vi.fn(),
      persistRevision: vi.fn(),
      exportJob: vi.fn()
    }
    const harness = createHarness({ verificationApi })

    await harness.execution.analyzeText('检查文本', options)
    expect(harness.execution.state.value).toBe('completed')
    expect(harness.execution.result.value).toEqual(textResult)
    expect(harness.jobsApi.subscribe).not.toHaveBeenCalled()

    await harness.execution.analyzeFile(
      new File(['docx'], 'direct.docx'),
      options
    )
    expect(harness.execution.state.value).toBe('completed')
    expect(harness.execution.result.value).toEqual(fileResult)
    expect(harness.jobsApi.subscribe).not.toHaveBeenCalled()
  })

  it('validates and freezes raw direct and asynchronous dependency results before publication', async () => {
    const directPayload = buildResult()
    const verificationApi: VerificationApi = {
      analyzeText: vi.fn().mockResolvedValue(directPayload),
      analyzeFile: vi.fn(),
      exportReport: vi.fn(),
      exportOriginal: vi.fn(),
      persistRevision: vi.fn(),
      exportJob: vi.fn()
    }
    const direct = createHarness({ verificationApi })

    await direct.execution.analyzeText('检查文本', options)

    expect(direct.execution.result.value).not.toBe(directPayload)
    expect(Object.isFrozen(direct.execution.result.value)).toBe(true)
    directPayload.text = '调用方篡改'
    expect(direct.execution.result.value?.text).toBe('检查文本')

    const asyncPayload = buildResult({ execution_mode: 'asynchronous' })
    const asynchronous = createHarness({ result: asyncPayload })
    await asynchronous.execution.analyzeFile(
      new File(['pdf'], 'sample.pdf'),
      options
    )
    asynchronous.emit(buildEvent('completed'))
    await flushPromises()

    expect(asynchronous.execution.result.value).not.toBe(asyncPayload)
    expect(Object.isFrozen(asynchronous.execution.result.value)).toBe(true)
    asyncPayload.text = '调用方篡改'
    expect(asynchronous.execution.result.value?.text).toBe('检查文本')
  })

  it.each([
    ['direct dependency', 'direct'],
    ['asynchronous result dependency', 'asynchronous']
  ] as const)(
    'rejects out-of-range issue confidence from a %s before publication',
    async (_label, source) => {
      const issue = buildIssue(1.01)
      const invalidResult = buildResult({
        execution_mode:
          source === 'asynchronous' ? 'asynchronous' : 'synchronous',
        issues: [issue],
        summary: {
          total: 1,
          by_type: { typo: 1 },
          by_severity: { warning: 1 },
          by_rule: { cn_typo: 1 },
          by_layer: { character: 1 }
        }
      })
      if (source === 'direct') {
        const verificationApi: VerificationApi = {
          analyzeText: vi.fn().mockResolvedValue(invalidResult),
          analyzeFile: vi.fn(),
          exportReport: vi.fn(),
          exportOriginal: vi.fn(),
          persistRevision: vi.fn(),
          exportJob: vi.fn()
        }
        const harness = createHarness({ verificationApi })

        await harness.execution.analyzeText('检查文本', options)

        expect(harness.execution.state.value).toBe('failed')
        expect(harness.execution.result.value).toBeNull()
        expect(harness.execution.error.value?.message).toBe(
          'Invalid verification result response.'
        )
        return
      }

      const harness = createHarness({ result: invalidResult })
      await harness.execution.analyzeFile(
        new File(['pdf'], 'sample.pdf'),
        options
      )
      harness.emit(buildEvent('completed'))
      await flushPromises()

      expect(harness.execution.state.value).toBe('failed')
      expect(harness.execution.result.value).toBeNull()
      expect(harness.execution.error.value?.message).toBe(
        'Invalid verification result response.'
      )
    }
  )

  it('passes one immutable cloned options snapshot to direct and asynchronous APIs', async () => {
    const verificationApi: VerificationApi = {
      analyzeText: vi.fn().mockResolvedValue(buildResult()),
      analyzeFile: vi.fn().mockResolvedValue(buildResult()),
      exportReport: vi.fn(),
      exportOriginal: vi.fn(),
      persistRevision: vi.fn(),
      exportJob: vi.fn()
    }
    const direct = createHarness({ verificationApi })
    const directOptions: AnalyzeOptions = structuredClone(options)

    await direct.execution.analyzeText('检查文本', directOptions)
    const directSnapshot = vi.mocked(verificationApi.analyzeText).mock.calls[0]?.[1]
    expect(directSnapshot).toEqual(options)
    expect(directSnapshot).not.toBe(directOptions)
    expect(Object.isFrozen(directSnapshot)).toBe(true)
    expect(Object.isFrozen(directSnapshot?.glossary)).toBe(true)
    expect(Object.isFrozen(directSnapshot?.glossary[0])).toBe(true)

    const asynchronous = createHarness()
    const asyncOptions: AnalyzeOptions = structuredClone(options)
    await asynchronous.execution.analyzeFile(
      new File(['pdf'], 'sample.pdf'),
      asyncOptions
    )
    const asyncSnapshot = vi.mocked(asynchronous.jobsApi.createJob).mock
      .calls[0]?.[1]
    expect(asyncSnapshot).toEqual(directSnapshot)
    expect(asyncSnapshot).not.toBe(asyncOptions)
    expect(Object.isFrozen(asyncSnapshot)).toBe(true)
  })

  it('restores validated async job context without inventing a completed job', () => {
    const harness = createHarness()
    const result = buildResult({ execution_mode: 'asynchronous' })

    expect(
      harness.execution.restoreJobContext(result.document_id, result)
    ).toBe(true)
    expect(harness.execution.jobId.value).toBe(result.document_id)
    expect(harness.execution.job.value).toBeNull()
    expect(harness.execution.state.value).toBe('idle')
    expect(
      harness.execution.restoreJobContext(
        '44444444-4444-4444-8444-444444444444',
        result
      )
    ).toBe(false)
    expect(harness.execution.jobId.value).toBe(result.document_id)

    harness.execution.reset()

    expect(harness.execution.jobId.value).toBeNull()
  })
})
