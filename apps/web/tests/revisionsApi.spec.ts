import { describe, expect, it, vi } from 'vitest'

import { createRevisionsApi } from '../src/api/revisions'
import type {
  DerivedResponse,
  EditDraft,
  OperationBatch,
  ReanalysisResponse,
  VersionListResponse
} from '../src/types/revisions'

function okJson<T>(payload: T) {
  return {
    ok: true,
    json: async () => payload
  }
}

function buildDraft(overrides: Partial<EditDraft> = {}): EditDraft {
  return {
    draft_id: 'draft-1',
    job_id: 'job-1',
    base_version_id: 'version-1',
    revision: 1,
    blocks: [{ block_id: 'p-1', text: '原文' }],
    content_sha256: null,
    created_at: '2026-08-23T12:00:00Z',
    updated_at: '2026-08-23T12:00:00Z',
    consumed_at: null,
    ...overrides
  }
}

function buildBatch(overrides: Partial<OperationBatch> = {}): OperationBatch {
  return {
    batch_id: 'batch-1',
    job_id: 'job-1',
    version_id: 'version-1',
    operation_type: 'decision',
    affected_count: 2,
    undoes_batch_id: null,
    created_at: '2026-08-23T12:00:00Z',
    ...overrides
  }
}

class FakeEventSource {
  public onerror: ((event: Event) => void) | null = null

  private listeners = new Map<string, Set<(event: MessageEvent<string>) => void>>()
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

  emitControl(type: string) {
    const event = { data: JSON.stringify({ event: type }) } as MessageEvent<string>
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event)
    }
  }

  get closeCalls() {
    return this._closeCalls
  }
}

describe('createRevisionsApi', () => {
  it('lists versions for a job', async () => {
    const response: VersionListResponse = {
      job_id: 'job-1',
      active_version_id: 'version-2',
      versions: [
        {
          version_id: 'version-2',
          job_id: 'job-1',
          parent_version_id: 'version-1',
          revision_number: 2,
          status: 'succeeded',
          source_kind: 'reanalysis',
          created_reason: 'draft_reanalysis',
          content_sha256: 'a'.repeat(64),
          created_at: '2026-08-23T12:00:00Z',
          started_at: '2026-08-23T12:00:01Z',
          completed_at: '2026-08-23T12:00:02Z',
          failure_code: null,
          failure_message: null
        }
      ]
    }
    const fetchMock = vi.fn().mockResolvedValue(okJson(response))

    const result = await createRevisionsApi({ fetch: fetchMock }).listVersions('job 1')

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/jobs/job%201/versions', undefined)
    expect(result.active_version_id).toBe('version-2')
  })

  it('creates drafts with an encoded base version payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson(buildDraft()))

    await createRevisionsApi({ fetch: fetchMock }).createDraft('job-1', 'version/1')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/drafts',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base_version_id: 'version/1' })
      })
    )
  })

  it('gets and updates drafts with optimistic revision payloads', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(okJson(buildDraft()))
      .mockResolvedValueOnce(okJson(buildDraft({ revision: 3 })))
    const api = createRevisionsApi({ fetch: fetchMock })

    await api.getDraft('job-1', 'draft/1')
    await api.updateDraft('job-1', 'draft-1', {
      expected_revision: 2,
      blocks: [{ block_id: 'p-1', text: '修改后' }]
    })

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/jobs/job-1/drafts/draft%2F1',
      undefined
    )
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/jobs/job-1/drafts/draft-1',
      expect.objectContaining({
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          expected_revision: 2,
          blocks: [{ block_id: 'p-1', text: '修改后' }]
        })
      })
    )
  })

  it('deletes drafts without parsing a response body', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })

    await createRevisionsApi({ fetch: fetchMock }).deleteDraft('job-1', 'draft-1')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/drafts/draft-1',
      expect.objectContaining({ method: 'DELETE' })
    )
  })

  it('posts reanalysis requests with the idempotency key body', async () => {
    const response: ReanalysisResponse = {
      version: {
        version_id: 'version-2',
        job_id: 'job-1',
        parent_version_id: 'version-1',
        revision_number: 2,
        status: 'queued',
        source_kind: 'reanalysis',
        created_reason: 'draft_reanalysis',
        content_sha256: null,
        created_at: '2026-08-23T12:00:00Z',
        started_at: null,
        completed_at: null,
        failure_code: null,
        failure_message: null
      },
      events_url: '/api/v1/jobs/job-1/versions/version-2/events'
    }
    const fetchMock = vi.fn().mockResolvedValue(okJson(response))

    const result = await createRevisionsApi({ fetch: fetchMock }).reanalyze('job-1', 'draft-1', {
      expected_draft_revision: 4,
      idempotency_key: 'retry-key-1'
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/drafts/draft-1/reanalyze',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          expected_draft_revision: 4,
          idempotency_key: 'retry-key-1'
        })
      })
    )
    expect(result.events_url).toBe('/api/v1/jobs/job-1/versions/version-2/events')
  })

  it.each([
    ['modified' as const, [{ block_id: 'p-1', kind: 'paragraph', text: '改', page: 1, paragraph_index: 0, parent_id: null, style: {}, source_locator: {} }]],
    ['diff' as const, [{ block_id: 'p-1', segments: [{ kind: 'insert' as const, text: '改' }] }]]
  ])('gets %s derived content with a view query', async (mode, blocks) => {
    const response: DerivedResponse = {
      job_id: 'job-1',
      version_id: 'version-1',
      decision_snapshot_sha256: 'b'.repeat(64),
      blocks
    } as DerivedResponse
    const fetchMock = vi.fn().mockResolvedValue(okJson(response))

    await createRevisionsApi({ fetch: fetchMock }).getDerived('job-1', 'version/1', mode)

    expect(fetchMock).toHaveBeenCalledWith(
      `/api/v1/jobs/job-1/versions/version%2F1/derived?view=${mode}`,
      undefined
    )
  })

  it('subscribes to version events and preserves EventSource Last-Event-ID sequence values', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/versions/version-1/events')
    const onEvent = vi.fn()
    const onError = vi.fn()

    createRevisionsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    }).subscribeVersionEvents('job-1', 'version-1', onEvent, onError)

    eventSource.emit(
      'progress',
      {
        status: 'analyzing',
        progress: 50,
        message: '正在重新分析',
        created_at: '2026-08-23T12:00:00Z',
        current_category: 'security',
        completed_categories: ['character'],
        issue_count: 3
      },
      '2'
    )

    expect(eventSource.url).toBe('/api/v1/jobs/job-1/versions/version-1/events')
    expect(onEvent).toHaveBeenCalledWith({
      sequence: 2,
      status: 'analyzing',
      progress: 50,
      message: '正在重新分析',
      created_at: '2026-08-23T12:00:00Z',
      metadata: {
        current_category: 'security',
        completed_categories: ['character'],
        issue_count: 3
      }
    })
    expect(onError).not.toHaveBeenCalled()
  })

  it('closes version event streams on done', () => {
    const eventSource = new FakeEventSource('/api/v1/jobs/job-1/versions/version-1/events')

    const unsubscribe = createRevisionsApi({
      fetch: vi.fn(),
      eventSourceFactory: () => eventSource as unknown as EventSource
    }).subscribeVersionEvents('job-1', 'version-1', vi.fn(), vi.fn())

    eventSource.emitControl('done')
    unsubscribe()

    expect(eventSource.closeCalls).toBe(1)
  })

  it('lists history with encoded version id only', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      okJson({
        job_id: 'job-1',
        version_id: 'version/1',
        total: 1,
        items: [buildBatch({ version_id: 'version/1' })],
        next_cursor: null
      })
    )

    // @ts-expect-error history pagination is intentionally not public until the backend supports it
    await createRevisionsApi({ fetch: fetchMock }).listHistory('job-1', 'version/1', {
      cursor: 'batch/1',
      limit: 25
    })

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/operation-batches?version_id=version%2F1',
      undefined
    )
  })

  it('posts undo requests for operation batches', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson(buildBatch({ operation_type: 'undo' })))

    const result = await createRevisionsApi({ fetch: fetchMock }).undoBatch('job-1', 'batch/1')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/jobs/job-1/operation-batches/batch%2F1/undo',
      expect.objectContaining({ method: 'POST' })
    )
    expect(result.operation_type).toBe('undo')
  })
})
