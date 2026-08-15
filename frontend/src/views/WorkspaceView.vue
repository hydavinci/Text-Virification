<script setup lang="ts">
import { inject, onBeforeUnmount, ref } from 'vue'

import { jobsApiKey } from '../api/jobs'
import JobProgress from '../components/JobProgress.vue'
import UploadWorkspace from '../components/UploadWorkspace.vue'
import { isTerminalJobStatus, type JobProgressEvent, type JobRead, type JobStatus } from '../types/jobs'

interface JobProgressState {
  sourceName: string
  status: JobStatus
  progress: number
  message: string
  failureMessage: string | null
  connectionMessage: string | null
}

const injectedJobsApi = inject(jobsApiKey)

if (!injectedJobsApi) {
  throw new Error('JobsApi is not provided.')
}

const jobsApi = injectedJobsApi

const uploadError = ref<string | null>(null)
const isCreating = ref(false)
const jobState = ref<JobProgressState | null>(null)

let unsubscribe: (() => void) | null = null

function closeSubscription() {
  unsubscribe?.()
  unsubscribe = null
}

function buildInitialState(job: JobRead): JobProgressState {
  return {
    sourceName: job.source_name,
    status: job.status,
    progress: job.progress,
    message: job.error_message ?? defaultStatusMessage(job.status),
    failureMessage: job.error_message,
    connectionMessage: null
  }
}

function handleProgress(event: JobProgressEvent) {
  const currentSourceName = jobState.value?.sourceName ?? 'Uploaded document'
  const isFailureState =
    event.status === 'failed' || event.status === 'partial' || event.status === 'expired'

  jobState.value = {
    sourceName: currentSourceName,
    status: event.status,
    progress: event.progress,
    message: event.message,
    failureMessage: isFailureState ? event.message : null,
    connectionMessage: null
  }
}

function handleProgressError(message: string) {
  if (!jobState.value || isTerminalJobStatus(jobState.value.status)) {
    return
  }

  jobState.value = {
    ...jobState.value,
    connectionMessage: message
  }
}

async function handleUpload(file: File) {
  uploadError.value = null
  closeSubscription()
  isCreating.value = true

  try {
    const job = await jobsApi.createJob(file)
    jobState.value = buildInitialState(job)
    unsubscribe = jobsApi.subscribe(job.job_id, handleProgress, handleProgressError)
  } catch (error) {
    uploadError.value =
      error instanceof Error ? error.message : 'Unable to create the job.'
  } finally {
    isCreating.value = false
  }
}

function defaultStatusMessage(status: JobStatus): string {
  switch (status) {
    case 'queued':
      return '作业已创建'
    case 'upload_validated':
      return '上传校验完成'
    case 'parsing':
      return '开始解析'
    case 'checking_format':
      return '正在检查格式'
    case 'checking_sensitive':
      return '正在检查敏感词'
    case 'checking_chinese':
      return '正在检查中文'
    case 'checking_english':
      return '正在检查英文'
    case 'completed':
      return '处理完成'
    case 'partial':
      return '部分完成'
    case 'failed':
      return '处理失败'
    case 'expired':
      return '任务已过期'
  }
}

onBeforeUnmount(() => {
  closeSubscription()
})
</script>

<template>
  <section>
    <h1>Upload and progress workspace</h1>
    <UploadWorkspace :busy="isCreating" :server-error="uploadError" @upload="handleUpload" />
    <JobProgress v-if="jobState" :state="jobState" />
  </section>
</template>
