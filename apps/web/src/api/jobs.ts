import type { InjectionKey } from 'vue'

import { buildApiPath, requestJson, type RequestJsonDependencies } from './client'
import {
  JOB_STATUS_VALUES,
  type JobCreateOptions,
  type JobProgressEvent,
  type JobRead,
  type JobStatus
} from '../types/jobs'

export interface JobsApi {
  createJob(file: File, options?: JobCreateOptions): Promise<JobRead>
  subscribe(
    jobId: string,
    onEvent: (event: JobProgressEvent) => void,
    onError: (message: string) => void
  ): () => void
}

interface JobsApiDependencies extends RequestJsonDependencies {
  eventSourceFactory: (url: string) => EventSource
}

const TEMPORARY_CONNECTION_NOTICE = 'Connection interrupted. Waiting to reconnect…'
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
    async createJob(file, options) {
      const body = new FormData()
      body.append('file', file, file.name)
      appendScenario(body, options?.scenario)
      appendEnabledCategories(body, options?.enabledCategories)

      return requestJson<JobRead>(dependencies, '/jobs', {
        method: 'POST',
        body
      })
    },
    subscribe(jobId, onEvent, onError) {
      const eventSource = dependencies.eventSourceFactory(
        buildApiPath(`/jobs/${encodeURIComponent(jobId)}/events`)
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
          const payload = parseProgressPayload(event.data)
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
        onError(TEMPORARY_CONNECTION_NOTICE)
      }

      return close
    }
  }
}

function parseProgressPayload(data: string): JobProgressEvent {
  const parsed = JSON.parse(data) as unknown

  if (!isProgressPayload(parsed)) {
    throw new Error('Invalid progress payload.')
  }

  return {
    sequence: 0,
    status: parsed.status,
    progress: parsed.progress,
    message: parsed.message,
    created_at: parsed.created_at
  }
}

function isProgressPayload(value: unknown): value is {
  status: JobStatus
  progress: number
  message: string
  created_at: string
} {
  if (!isRecord(value)) {
    return false
  }

  return (
    isJobStatus(value.status) &&
    typeof value.progress === 'number' &&
    Number.isFinite(value.progress) &&
    value.progress >= 0 &&
    value.progress <= 100 &&
    typeof value.message === 'string' &&
    typeof value.created_at === 'string' &&
    value.created_at.trim().length > 0 &&
    Number.isFinite(Date.parse(value.created_at))
  )
}

function isJobStatus(value: unknown): value is JobStatus {
  return typeof value === 'string' && JOB_STATUS_VALUES.includes(value as JobStatus)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function appendScenario(body: FormData, scenario: JobCreateOptions['scenario']): void {
  if (scenario) {
    body.append('scenario', scenario)
  }
}

function appendEnabledCategories(
  body: FormData,
  enabledCategories: JobCreateOptions['enabledCategories']
): void {
  if (enabledCategories === undefined) {
    return
  }

  if (enabledCategories.length < 1) {
    throw new RangeError('At least one check category must be enabled.')
  }

  for (const category of enabledCategories) {
    body.append('enabled_categories', category)
  }
}
