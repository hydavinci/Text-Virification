import type { InjectionKey } from 'vue'

import type { JobProgressEvent, JobRead, JobStatus } from '../types/jobs'

export interface JobsApi {
  createJob(file: File): Promise<JobRead>
  subscribe(
    jobId: string,
    onEvent: (event: JobProgressEvent) => void,
    onError: (message: string) => void
  ): () => void
}

interface JobsApiDependencies {
  fetch: typeof fetch
  eventSourceFactory: (url: string) => EventSource
}

interface ProgressPayload {
  status: JobStatus
  progress: number
  message: string
  created_at: string
}

const API_BASE = '/api/v1'
const PROGRESS_CONNECTION_ERROR = 'Unable to receive job progress updates.'
const EXPIRED_MESSAGE = '任务已过期'

export const jobsApiKey: InjectionKey<JobsApi> = Symbol('jobsApi')

export function createJobsApi(
  overrides: Partial<JobsApiDependencies> = {}
): JobsApi {
  const dependencies: JobsApiDependencies = {
    fetch: overrides.fetch ?? fetch,
    eventSourceFactory: overrides.eventSourceFactory ?? ((url) => new EventSource(url))
  }

  return {
    async createJob(file) {
      const body = new FormData()
      body.append('file', file, file.name)

      const response = await dependencies.fetch(`${API_BASE}/jobs`, {
        method: 'POST',
        body
      })

      if (!response.ok) {
        throw new Error(await extractErrorMessage(response))
      }

      return (await response.json()) as JobRead
    },
    subscribe(jobId, onEvent, onError) {
      const eventSource = dependencies.eventSourceFactory(
        `${API_BASE}/jobs/${encodeURIComponent(jobId)}/events`
      )
      let closed = false
      let lastSequence = 0
      let lastProgress = 0

      const close = () => {
        if (closed) {
          return
        }
        closed = true
        eventSource.removeEventListener('progress', handleProgress)
        eventSource.removeEventListener('done', handleDone)
        eventSource.removeEventListener('expired', handleExpired)
        eventSource.onerror = null
        eventSource.close()
      }

      const emitExpired = () => {
        onEvent({
          sequence: lastSequence,
          status: 'expired',
          progress: lastProgress,
          message: EXPIRED_MESSAGE,
          created_at: new Date().toISOString()
        })
      }

      const handleProgress = (event: MessageEvent<string>) => {
        if (closed) {
          return
        }

        try {
          const payload = JSON.parse(event.data) as ProgressPayload
          const sequence = Number.parseInt(event.lastEventId, 10)
          lastSequence = Number.isFinite(sequence) ? sequence : lastSequence
          lastProgress = payload.progress
          onEvent({
            sequence: lastSequence,
            status: payload.status,
            progress: payload.progress,
            message: payload.message,
            created_at: payload.created_at
          })
        } catch {
          close()
          onError(PROGRESS_CONNECTION_ERROR)
        }
      }

      const handleDone = () => {
        close()
      }

      const handleExpired = () => {
        if (closed) {
          return
        }
        emitExpired()
        close()
      }

      eventSource.addEventListener('progress', handleProgress as EventListener)
      eventSource.addEventListener('done', handleDone as EventListener)
      eventSource.addEventListener('expired', handleExpired as EventListener)
      eventSource.onerror = () => {
        if (closed) {
          return
        }
        close()
        onError(PROGRESS_CONNECTION_ERROR)
      }

      return close
    }
  }
}

async function extractErrorMessage(response: Response): Promise<string> {
  const fallback = `Request failed with status ${response.status}.`

  try {
    const payload = (await response.json()) as { detail?: { message?: string } }
    const detailMessage = payload.detail?.message
    if (typeof detailMessage === 'string' && detailMessage.trim()) {
      return detailMessage
    }
  } catch {
    return fallback
  }

  return fallback
}
