import type { InjectionKey } from 'vue'

import { buildApiPath, requestJson, requestVoid, type RequestJsonDependencies } from './client'
import type {
  DerivedResponse,
  EditDraft,
  OperationBatch,
  OperationBatchPage,
  ReanalysisResponse,
  ReanalyzeRequest,
  UpdateDraftRequest,
  VersionEvent,
  VersionListResponse
} from '../types/revisions'
import type { CheckCategory } from '../types/review'

interface BaseVersionEventPayload {
  status: VersionEvent['status']
  progress: number
  message: string
  created_at: string
}

type VersionEventPayload =
  | (BaseVersionEventPayload & {
      current_category?: undefined
      completed_categories?: undefined
      issue_count?: undefined
    })
  | (BaseVersionEventPayload & {
      current_category: CheckCategory
      completed_categories: CheckCategory[]
      issue_count: number
    })

export interface RevisionsApi {
  listVersions(jobId: string): Promise<VersionListResponse>
  createDraft(jobId: string, baseVersionId: string): Promise<EditDraft>
  getDraft(jobId: string, draftId: string): Promise<EditDraft>
  updateDraft(jobId: string, draftId: string, request: UpdateDraftRequest): Promise<EditDraft>
  deleteDraft(jobId: string, draftId: string): Promise<void>
  reanalyze(jobId: string, draftId: string, request: ReanalyzeRequest): Promise<ReanalysisResponse>
  getDerived(jobId: string, versionId: string, mode: 'modified' | 'diff'): Promise<DerivedResponse>
  subscribeVersionEvents(
    jobId: string,
    versionId: string,
    onEvent: (event: VersionEvent) => void,
    onError: (message: string) => void
  ): () => void
  listHistory(
    jobId: string,
    versionId: string
  ): Promise<OperationBatchPage>
  undoBatch(jobId: string, batchId: string): Promise<OperationBatch>
}

function parseVersionEvent(event: MessageEvent<string>): VersionEvent {
  const payload = JSON.parse(event.data) as unknown
  if (!isVersionEventPayload(payload)) {
    throw new Error('Invalid version event payload.')
  }
  const sequence = Number.parseInt(event.lastEventId, 10)
  const metadata =
    payload.current_category === undefined
      ? null
      : {
          current_category: payload.current_category,
          completed_categories: payload.completed_categories,
          issue_count: payload.issue_count
        }
  return {
    sequence: Number.isFinite(sequence) ? sequence : 0,
    status: payload.status,
    progress: payload.progress,
    message: payload.message,
    created_at: payload.created_at,
    metadata
  }
}

function isVersionEventPayload(value: unknown): value is VersionEventPayload {
  return (
    isRecord(value) &&
    isVersionStatus(value.status) &&
    typeof value.progress === 'number' &&
    Number.isFinite(value.progress) &&
    value.progress >= 0 &&
    value.progress <= 100 &&
    typeof value.message === 'string' &&
    typeof value.created_at === 'string' &&
    hasValidVersionEventMetadata(value)
  )
}

function hasValidVersionEventMetadata(value: Record<string, unknown>): boolean {
  const hasAnyMetadata =
    value.current_category !== undefined ||
    value.completed_categories !== undefined ||
    value.issue_count !== undefined
  if (!hasAnyMetadata) {
    return true
  }
  return (
    isCheckCategory(value.current_category) &&
    Array.isArray(value.completed_categories) &&
    value.completed_categories.every(isCheckCategory) &&
    typeof value.issue_count === 'number' &&
    Number.isInteger(value.issue_count) &&
    value.issue_count >= 0
  )
}

function isVersionStatus(value: unknown): value is VersionEvent['status'] {
  return (
    value === 'queued' || value === 'analyzing' || value === 'succeeded' || value === 'failed'
  )
}

function isCheckCategory(value: unknown): value is CheckCategory {
  return (
    value === 'character' ||
    value === 'vocabulary' ||
    value === 'sentence' ||
    value === 'format' ||
    value === 'discourse' ||
    value === 'security'
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

interface RevisionsApiDependencies extends RequestJsonDependencies {
  eventSourceFactory: (url: string) => EventSource
}

export const revisionsApiKey: InjectionKey<RevisionsApi> = Symbol('revisionsApi')

export function createRevisionsApi(
  overrides: Partial<RevisionsApiDependencies> = {}
): RevisionsApi {
  const dependencies: RevisionsApiDependencies = {
    fetch: overrides.fetch ?? fetch,
    eventSourceFactory: overrides.eventSourceFactory ?? ((url) => new EventSource(url))
  }

  return {
    listVersions(jobId) {
      return requestJson<VersionListResponse>(
        dependencies,
        `/jobs/${encodeURIComponent(jobId)}/versions`
      )
    },
    createDraft(jobId, baseVersionId) {
      return requestJson<EditDraft>(dependencies, `/jobs/${encodeURIComponent(jobId)}/drafts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base_version_id: baseVersionId })
      })
    },
    getDraft(jobId, draftId) {
      return requestJson<EditDraft>(
        dependencies,
        `/jobs/${encodeURIComponent(jobId)}/drafts/${encodeURIComponent(draftId)}`
      )
    },
    updateDraft(jobId, draftId, request) {
      return requestJson<EditDraft>(
        dependencies,
        `/jobs/${encodeURIComponent(jobId)}/drafts/${encodeURIComponent(draftId)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(request)
        }
      )
    },
    deleteDraft(jobId, draftId) {
      return requestVoid(
        dependencies,
        `/jobs/${encodeURIComponent(jobId)}/drafts/${encodeURIComponent(draftId)}`,
        { method: 'DELETE' }
      )
    },
    reanalyze(jobId, draftId, request) {
      return requestJson<ReanalysisResponse>(
        dependencies,
        `/jobs/${encodeURIComponent(jobId)}/drafts/${encodeURIComponent(draftId)}/reanalyze`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(request)
        }
      )
    },
    getDerived(jobId, versionId, mode) {
      return requestJson<DerivedResponse>(
        dependencies,
        withSearch(
          `/jobs/${encodeURIComponent(jobId)}/versions/${encodeURIComponent(versionId)}/derived`,
          [['view', mode]]
        )
      )
    },
    subscribeVersionEvents(jobId, versionId, onEvent, onError) {
      const eventSource = dependencies.eventSourceFactory(
        buildApiPath(
          `/jobs/${encodeURIComponent(jobId)}/versions/${encodeURIComponent(versionId)}/events`
        )
      )
      let closed = false

      const close = () => {
        if (closed) {
          return
        }
        closed = true
        eventSource.removeEventListener('progress', handleProgress)
        eventSource.removeEventListener('done', handleDone)
        eventSource.removeEventListener('expired', handleDone)
        eventSource.onerror = null
        eventSource.close()
      }

      const handleProgress = (event: MessageEvent<string>) => {
        if (closed) {
          return
        }

        try {
          onEvent(parseVersionEvent(event))
        } catch {
          close()
          onError('Unable to receive version progress updates.')
        }
      }

      const handleDone = () => {
        close()
      }

      eventSource.addEventListener('progress', handleProgress as EventListener)
      eventSource.addEventListener('done', handleDone as EventListener)
      eventSource.addEventListener('expired', handleDone as EventListener)
      eventSource.onerror = () => {
        if (!closed) {
          onError('Connection interrupted. Waiting to reconnect…')
        }
      }

      return close
    },
    listHistory(jobId, versionId) {
      return requestJson<OperationBatchPage>(
        dependencies,
        withSearch(`/jobs/${encodeURIComponent(jobId)}/operation-batches`, [
          ['version_id', versionId]
        ])
      )
    },
    undoBatch(jobId, batchId) {
      return requestJson<OperationBatch>(
        dependencies,
        `/jobs/${encodeURIComponent(jobId)}/operation-batches/${encodeURIComponent(batchId)}/undo`,
        { method: 'POST' }
      )
    }
  }
}

function withSearch(
  path: string,
  entries: Array<[string, string | number | null | undefined]>
): string {
  const params = new URLSearchParams()
  for (const [key, value] of entries) {
    if (value !== undefined && value !== null) {
      params.set(key, String(value))
    }
  }
  const query = params.toString()
  return query ? `${path}?${query}` : path
}
