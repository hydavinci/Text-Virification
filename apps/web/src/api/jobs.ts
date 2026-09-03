import type { InjectionKey } from 'vue'

import {
  JOB_FILE_TYPE_VALUES,
  JOB_PROGRESS_STAGE_VALUES,
  JOB_STATUS_VALUES,
  isTerminalJobStatus,
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
import {
  ApiRequestError,
  ApiResponseValidationError,
  readApiRequestError
} from './errors'
import { createVerificationResultSnapshot } from '../composables/useVerificationWorkspace'

export interface JobsApi {
  createJob(file: File, options: AnalyzeOptions): Promise<JobRead>
  getResult(jobId: string): Promise<VerificationResult>
  subscribe(
    jobId: string,
    onEvent: (event: JobProgressEvent) => void,
    onError: (error: JobSubscriptionError) => void
  ): () => void
}

export interface JobSubscriptionError {
  kind: 'transient' | 'fatal'
  message: string
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

      const job = parseJobRead(await response.json())
      if (job === null) {
        throw new ApiResponseValidationError('Invalid job response.')
      }
      return job
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
      const result = createVerificationResultSnapshot(await response.json())
      if (result === null) {
        throw new ApiResponseValidationError(
          'Invalid verification result response.'
        )
      }
      return result
    },
    subscribe(jobId, onEvent, onError) {
      const eventSource = dependencies.eventSourceFactory(
        `${API_BASE}/jobs/${encodeURIComponent(jobId)}/events`
      )
      let closed = false
      let lastSequence = 0
      let lastProgress = 0
      let terminalProgressObserved = false

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

      const reportFatalProtocolError = () => {
        close()
        onError({
          kind: 'fatal',
          message: PROGRESS_CONNECTION_ERROR
        })
      }

      const handleProgress = (event: MessageEvent<string>) => {
        if (closed) {
          return
        }

        const sequence = parseEventSequence(event.lastEventId)
        if (sequence === null) {
          reportFatalProtocolError()
          return
        }
        if (sequence <= lastSequence) {
          return
        }
        try {
          const payload = parseProgressPayload(event.data)
          lastSequence = sequence
          lastProgress = payload.progress
          terminalProgressObserved = isTerminalJobStatus(payload.status)
          onEvent({
            sequence: lastSequence,
            status: payload.status,
            stage: payload.stage,
            progress: payload.progress,
            message: payload.message,
            created_at: payload.created_at
          })
        } catch {
          reportFatalProtocolError()
        }
      }

      const handleDone = () => {
        if (!terminalProgressObserved) {
          reportFatalProtocolError()
          return
        }
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
        if (eventSource.readyState === 2) {
          reportFatalProtocolError()
          return
        }
        onError({
          kind: 'transient',
          message: TEMPORARY_CONNECTION_NOTICE
        })
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

function parseEventSequence(value: string): number | null {
  if (!/^(0|[1-9]\d*)$/.test(value)) {
    return null
  }
  const sequence = Number(value)
  return Number.isSafeInteger(sequence) ? sequence : null
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
    isProgress(value.progress) &&
    isProgressStageForStatus(value.status, value.stage, value.progress) &&
    typeof value.message === 'string' &&
    typeof value.created_at === 'string' &&
    value.created_at.trim().length > 0 &&
    Number.isFinite(Date.parse(value.created_at))
  )
}

function isProgressStageForStatus(
  status: JobStatus,
  stage: JobProgressStage,
  progress: number
): boolean {
  if (
    (status === 'completed' || status === 'partial') &&
    (stage === 'exporting' || stage === 'finalizing')
  ) {
    return true
  }
  return stage === expectedJobStage(status, progress)
}

function isJobStatus(value: unknown): value is JobStatus {
  return (
    typeof value === 'string' &&
    JOB_STATUS_VALUES.some((status) => status === value)
  )
}

function isJobFileType(value: unknown): value is JobRead['file_type'] {
  return (
    typeof value === 'string' &&
    JOB_FILE_TYPE_VALUES.some((fileType) => fileType === value)
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

function parseJobRead(value: unknown): JobRead | null {
  if (
    !isRecord(value) ||
    typeof value.job_id !== 'string' ||
    !isUuid(value.job_id) ||
    typeof value.source_name !== 'string' ||
    value.source_name.length === 0 ||
    !isJobFileType(value.file_type) ||
    !isNonnegativeInteger(value.size_bytes) ||
    !isJobStatus(value.status) ||
    !isJobProgressStage(value.stage) ||
    !isProgress(value.progress) ||
    value.stage !== expectedJobStage(value.status, value.progress) ||
    !isNullableString(value.error_code) ||
    !isNullableString(value.error_message) ||
    !isNullableString(value.error_stage) ||
    !isNullableBoolean(value.error_retryable) ||
    !isDateTime(value.created_at) ||
    !isDateTime(value.expires_at) ||
    Date.parse(value.expires_at) < Date.parse(value.created_at)
  ) {
    return null
  }
  return Object.freeze({
    job_id: value.job_id,
    source_name: value.source_name,
    file_type: value.file_type,
    size_bytes: value.size_bytes,
    status: value.status,
    stage: value.stage,
    progress: value.progress,
    error_code: value.error_code,
    error_message: value.error_message,
    error_stage: value.error_stage,
    error_retryable: value.error_retryable,
    created_at: value.created_at,
    expires_at: value.expires_at
  })
}

function expectedJobStage(
  status: JobStatus,
  progress: number
): JobProgressStage {
  if (status === 'parsing' && progress >= 40) {
    return 'ocr'
  }
  if (status === 'checking_english' && progress >= 95) {
    return 'finalizing'
  }
  return status
}

function isProgress(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= 0 &&
    value <= 100
  )
}

function isNonnegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isNullableBoolean(value: unknown): value is boolean | null {
  return value === null || typeof value === 'boolean'
}

function isDateTime(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.trim().length > 0 &&
    Number.isFinite(Date.parse(value))
  )
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value
  )
}
