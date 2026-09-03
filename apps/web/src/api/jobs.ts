import type { InjectionKey } from 'vue'

import {
  JOB_PROGRESS_STAGE_VALUES,
  JOB_STATUS_VALUES,
  type JobProgressEvent,
  type JobProgressStage,
  type JobRead,
  type JobStatus
} from '../types/jobs'
import type { AnalyzeOptions, VerificationResult } from '../types/verification'
import {
  appendAnalyzeOptions,
  createAnalyzeOptionsSnapshot
} from './analyzeOptions'
import { ApiRequestError, readApiRequestError } from './errors'

export interface JobsApi {
  createJob(file: File, options: AnalyzeOptions): Promise<JobRead>
  getResult(jobId: string): Promise<VerificationResult>
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

const API_BASE = '/api/v1'
const TEMPORARY_CONNECTION_NOTICE = 'Connection interrupted. Waiting to reconnect…'
const PROGRESS_CONNECTION_ERROR = 'Unable to receive job progress updates.'
const EXPIRED_MESSAGE = '任务已过期'

export const jobsApiKey: InjectionKey<JobsApi> = Symbol('jobsApi')

export class JobResultExpiredError extends ApiRequestError {
  constructor(
    status: number,
    code: string | null,
    message: string,
    stage: string | null = null,
    retryable: boolean | null = null
  ) {
    super(status, code, message, stage, retryable)
    this.name = 'JobResultExpiredError'
  }
}

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
      const snapshot = createAnalyzeOptionsSnapshot(options)
      body.append('file', file, file.name)
      appendAnalyzeOptions(body, snapshot)

      const response = await dependencies.fetch(`${API_BASE}/jobs`, {
        method: 'POST',
        body
      })

      if (!response.ok) {
        throw await readApiRequestError(
          response,
          `Request failed with status ${response.status}.`
        )
      }

      return (await response.json()) as JobRead
    },
    async getResult(jobId) {
      const response = await dependencies.fetch(
        `${API_BASE}/jobs/${encodeURIComponent(jobId)}/result`
      )
      if (!response.ok) {
        const error = await readApiRequestError(
          response,
          `Request failed with status ${response.status}.`
        )
        if (response.status === 410) {
          throw new JobResultExpiredError(
            error.status,
            error.code,
            error.message,
            error.stage,
            error.retryable
          )
        }
        throw error
      }
      return (await response.json()) as VerificationResult
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
          stage: 'expired',
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
            stage: payload.stage,
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
  const parsed: unknown = JSON.parse(data)

  if (!isProgressPayload(parsed)) {
    throw new Error('Invalid progress payload.')
  }

  return {
    sequence: 0,
    status: parsed.status,
    stage: parsed.stage,
    progress: parsed.progress,
    message: parsed.message,
    created_at: parsed.created_at
  }
}

function isProgressPayload(value: unknown): value is {
  status: JobStatus
  stage: JobProgressStage
  progress: number
  message: string
  created_at: string
} {
  if (!isRecord(value)) {
    return false
  }

  return (
    isJobStatus(value.status) &&
    isJobProgressStage(value.stage) &&
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
  return (
    typeof value === 'string' &&
    JOB_STATUS_VALUES.some((status) => status === value)
  )
}

function isJobProgressStage(value: unknown): value is JobProgressStage {
  return (
    typeof value === 'string' &&
    JOB_PROGRESS_STAGE_VALUES.some((stage) => stage === value)
  )
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}
