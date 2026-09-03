import {
  computed,
  getCurrentScope,
  onScopeDispose,
  ref
} from 'vue'

import {
  JobResultExpiredError,
  type JobsApi
} from '../api/jobs'
import { createAnalyzeOptionsSnapshot } from '../api/analyzeOptions'
import type { VerificationApi } from '../api/verification'
import {
  isTerminalJobStatus,
  type JobProgressEvent,
  type JobProgressStage,
  type JobRead,
  type JobStatus
} from '../types/jobs'
import type {
  AnalyzeOptions,
  VerificationResult
} from '../types/verification'

export type VerificationExecutionState =
  | 'idle'
  | 'submitting'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'expired'

export interface UseVerificationExecutionDependencies {
  jobsApi: JobsApi
  verificationApi?: VerificationApi | null
}

export type VerificationResultTransform = (
  result: VerificationResult
) => VerificationResult

export function useVerificationExecution({
  jobsApi,
  verificationApi = null
}: UseVerificationExecutionDependencies) {
  const state = ref<VerificationExecutionState>('idle')
  const result = ref<VerificationResult | null>(null)
  const job = ref<JobRead | null>(null)
  const jobStatus = ref<JobStatus | null>(null)
  const progress = ref(0)
  const stage = ref<JobProgressStage | null>(null)
  const message = ref('')
  const error = ref<Error | null>(null)
  const connectionMessage = ref<string | null>(null)

  let requestGeneration = 0
  let requestActive = false
  let disposed = false
  let terminalObserved = false
  let resultFetchStarted = false
  let unsubscribe: (() => void) | null = null

  function closeSubscription(): void {
    const close = unsubscribe
    unsubscribe = null
    close?.()
  }

  function beginRequest(): number | null {
    if (disposed || requestActive) {
      return null
    }
    closeSubscription()
    requestGeneration += 1
    requestActive = true
    terminalObserved = false
    resultFetchStarted = false
    state.value = 'submitting'
    result.value = null
    job.value = null
    jobStatus.value = null
    progress.value = 0
    stage.value = null
    message.value = ''
    error.value = null
    connectionMessage.value = null
    return requestGeneration
  }

  function isCurrent(generation: number): boolean {
    return !disposed && generation === requestGeneration
  }

  function finishWithError(
    generation: number,
    nextState: 'failed' | 'expired',
    nextError: Error
  ): void {
    if (!isCurrent(generation)) {
      return
    }
    closeSubscription()
    requestActive = false
    terminalObserved = true
    state.value = nextState
    error.value = nextError
    message.value ||= nextError.message
    connectionMessage.value = null
  }

  function finishDirect(
    generation: number,
    payload: VerificationResult
  ): void {
    if (!isCurrent(generation)) {
      return
    }
    requestActive = false
    terminalObserved = true
    result.value = payload
    state.value = 'completed'
  }

  async function runDirect(
    generation: number,
    action: () => Promise<VerificationResult>,
    transformResult: VerificationResultTransform
  ): Promise<void> {
    try {
      const payload = await action()
      if (!isCurrent(generation)) {
        return
      }
      finishDirect(generation, transformResult(payload))
    } catch (caught) {
      finishWithError(generation, 'failed', toError(caught))
    }
  }

  async function analyzeText(
    text: string,
    options: AnalyzeOptions,
    transformResult: VerificationResultTransform = identityResult
  ): Promise<void> {
    const generation = beginRequest()
    if (generation === null) {
      return
    }
    if (!verificationApi) {
      finishWithError(
        generation,
        'failed',
        new Error('Direct verification is unavailable.')
      )
      return
    }
    try {
      const snapshot = createAnalyzeOptionsSnapshot(options)
      await runDirect(
        generation,
        () => verificationApi.analyzeText(text, snapshot),
        transformResult
      )
    } catch (caught) {
      finishWithError(generation, 'failed', toError(caught))
    }
  }

  async function analyzeFile(
    file: File,
    options: AnalyzeOptions
  ): Promise<void> {
    const generation = beginRequest()
    if (generation === null) {
      return
    }
    try {
      const snapshot = createAnalyzeOptionsSnapshot(options)
      if (verificationApi) {
        await runDirect(
          generation,
          () => verificationApi.analyzeFile(file, snapshot),
          identityResult
        )
        return
      }
      await createAndSubscribe(generation, file, snapshot)
    } catch (caught) {
      finishWithError(generation, 'failed', toError(caught))
    }
  }

  async function createAndSubscribe(
    generation: number,
    file: File,
    options: AnalyzeOptions
  ): Promise<void> {
    const createdJob = await jobsApi.createJob(file, options)
    if (!isCurrent(generation)) {
      return
    }
    applyJob(createdJob)
    if (isTerminalJobStatus(createdJob.status)) {
      handleProgress(
        {
          sequence: 0,
          status: createdJob.status,
          stage: createdJob.stage,
          progress: createdJob.progress,
          message:
            createdJob.error_message ??
            defaultStatusMessage(createdJob.status),
          created_at: createdJob.created_at
        },
        generation
      )
      return
    }

    state.value = 'processing'
    const close = jobsApi.subscribe(
      createdJob.job_id,
      (event) => handleProgress(event, generation),
      (connectionError) => handleConnectionError(connectionError, generation)
    )
    if (!isCurrent(generation) || terminalObserved) {
      close()
      return
    }
    unsubscribe = close
  }

  function applyJob(createdJob: JobRead): void {
    job.value = createdJob
    jobStatus.value = createdJob.status
    progress.value = createdJob.progress
    stage.value = createdJob.stage
    message.value =
      createdJob.error_message ?? defaultStatusMessage(createdJob.status)
  }

  function handleProgress(
    event: JobProgressEvent,
    generation: number
  ): void {
    if (!isCurrent(generation) || terminalObserved) {
      return
    }
    jobStatus.value = event.status
    progress.value = event.progress
    stage.value = event.stage
    message.value = event.message
    connectionMessage.value = null

    if (!isTerminalJobStatus(event.status)) {
      state.value = 'processing'
      return
    }

    terminalObserved = true
    closeSubscription()
    if (event.status === 'failed') {
      requestActive = false
      state.value = 'failed'
      error.value = new Error(event.message)
      return
    }
    if (event.status === 'expired') {
      requestActive = false
      state.value = 'expired'
      error.value = new JobResultExpiredError(
        410,
        'job_result_expired',
        event.message,
        event.stage,
        false
      )
      return
    }
    void loadCanonicalResult(generation)
  }

  async function loadCanonicalResult(generation: number): Promise<void> {
    const jobId = job.value?.job_id
    if (!jobId || resultFetchStarted || !isCurrent(generation)) {
      return
    }
    resultFetchStarted = true
    try {
      const payload = await jobsApi.getResult(jobId)
      if (!isCurrent(generation)) {
        return
      }
      result.value = payload
      state.value = 'completed'
      requestActive = false
    } catch (caught) {
      const nextError = toError(caught)
      finishWithError(
        generation,
        caught instanceof JobResultExpiredError ? 'expired' : 'failed',
        nextError
      )
    }
  }

  function handleConnectionError(
    connectionError: string,
    generation: number
  ): void {
    if (
      !isCurrent(generation) ||
      terminalObserved ||
      state.value === 'completed' ||
      state.value === 'failed' ||
      state.value === 'expired'
    ) {
      return
    }
    connectionMessage.value = connectionError
  }

  function reset(): void {
    requestGeneration += 1
    closeSubscription()
    requestActive = false
    terminalObserved = false
    resultFetchStarted = false
    state.value = 'idle'
    result.value = null
    job.value = null
    jobStatus.value = null
    progress.value = 0
    stage.value = null
    message.value = ''
    error.value = null
    connectionMessage.value = null
  }

  function dispose(): void {
    if (disposed) {
      return
    }
    reset()
    disposed = true
  }

  if (getCurrentScope()) {
    onScopeDispose(dispose)
  }

  return {
    state: computed(() => state.value),
    result: computed(() => result.value),
    job: computed(() => job.value),
    jobStatus: computed(() => jobStatus.value),
    progress: computed(() => progress.value),
    stage: computed(() => stage.value),
    message: computed(() => message.value),
    error: computed(() => error.value),
    connectionMessage: computed(() => connectionMessage.value),
    isActive: computed(
      () => state.value === 'submitting' || state.value === 'processing'
    ),
    analyzeText,
    analyzeFile,
    reset,
    dispose
  }
}

function defaultStatusMessage(status: JobStatus): string {
  const messages: Record<JobStatus, string> = {
    queued: '作业已创建',
    upload_validated: '上传校验完成',
    parsing: '开始解析',
    checking_format: '正在检查格式',
    checking_sensitive: '正在检查敏感词',
    checking_chinese: '正在检查中文',
    checking_english: '正在检查英文',
    completed: '处理完成',
    partial: '部分完成',
    failed: '处理失败',
    expired: '任务已过期'
  }
  return messages[status]
}

function toError(value: unknown): Error {
  return value instanceof Error
    ? value
    : new Error('检查失败，请稍后重试')
}

function identityResult(result: VerificationResult): VerificationResult {
  return result
}
