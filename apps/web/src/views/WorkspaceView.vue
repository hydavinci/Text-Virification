<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref } from 'vue'

import { jobsApiKey } from '../api/jobs'
import JobProgress from '../components/JobProgress.vue'
import UploadWorkspace from '../components/UploadWorkspace.vue'
import {
  isTerminalJobStatus,
  type JobCreateOptions,
  type JobProgressEvent,
  type JobRead,
  type JobStatus
} from '../types/jobs'
import type { FileType } from '../types/review'
import ReviewWorkspaceView from './ReviewWorkspaceView.vue'

interface JobProgressState {
  sourceName: string
  status: JobStatus
  progress: number
  message: string
  failureMessage: string | null
  connectionMessage: string | null
}

interface ActiveJob {
  jobId: string
  sourceName: string
  fileType: FileType
}

const injectedJobsApi = inject(jobsApiKey)

if (!injectedJobsApi) {
  throw new Error('JobsApi is not provided.')
}

const jobsApi = injectedJobsApi

const uploadError = ref<string | null>(null)
const isCreating = ref(false)
const jobState = ref<JobProgressState | null>(null)
const activeJob = ref<ActiveJob | null>(null)
const reviewDirty = ref(false)
const showsReviewWorkspace = computed(
  () =>
    activeJob.value !== null &&
    (jobState.value?.status === 'completed' || jobState.value?.status === 'partial')
)

let unsubscribe: (() => void) | null = null
let requestGeneration = 0
let isMounted = true

type UploadOptionsSnapshot = Readonly<Required<JobCreateOptions>>

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

async function handleUpload(file: File, options: UploadOptionsSnapshot) {
  const generation = ++requestGeneration
  uploadError.value = null
  closeSubscription()
  isCreating.value = true

  try {
    const job = await jobsApi.createJob(file, options)
    if (!isRequestCurrent(generation)) {
      return
    }
    activeJob.value = {
      jobId: job.job_id,
      sourceName: job.source_name,
      fileType: job.file_type
    }
    jobState.value = buildInitialState(job)
    unsubscribe = jobsApi.subscribe(
      job.job_id,
      (event) => {
        if (!isRequestCurrent(generation)) {
          return
        }
        handleProgress(event)
      },
      (message) => {
        if (!isRequestCurrent(generation)) {
          return
        }
        handleProgressError(message)
      }
    )
  } catch (error) {
    if (!isRequestCurrent(generation)) {
      return
    }
    uploadError.value =
      error instanceof Error ? error.message : 'Unable to create the job.'
  } finally {
    if (isRequestCurrent(generation)) {
      isCreating.value = false
    }
  }
}

function isRequestCurrent(generation: number): boolean {
  return isMounted && generation === requestGeneration
}

function processAnotherFile(): void {
  if (
    reviewDirty.value &&
    typeof globalThis.confirm === 'function' &&
    !globalThis.confirm('当前草稿尚未保存，确定要处理其他文件吗？')
  ) {
    return
  }
  requestGeneration += 1
  closeSubscription()
  activeJob.value = null
  jobState.value = null
  uploadError.value = null
  isCreating.value = false
  reviewDirty.value = false
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
  isMounted = false
  requestGeneration += 1
  closeSubscription()
})
</script>

<template>
  <main :class="['workspace', { 'workspace--review': showsReviewWorkspace }]">
    <ReviewWorkspaceView
      v-if="showsReviewWorkspace && activeJob"
      :job-id="activeJob.jobId"
      :source-name="activeJob.sourceName"
      :file-type="activeJob.fileType"
      @process-another-file="processAnotherFile"
      @dirty-change="reviewDirty = $event"
    />

    <template v-else>
      <header class="workspace__header">
        <div class="workspace__brand" aria-hidden="true">
          <svg viewBox="0 0 24 24" role="img">
            <path d="M8 3h6l4 4v14H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
            <path d="M14 3v5h5M9.5 13l1.7 1.7 3.8-4" />
          </svg>
        </div>
        <div>
          <h1>文档智能核验</h1>
          <p>上传文档，自动完成格式、内容与语言规范检查</p>
        </div>
      </header>

      <section class="workspace__card" aria-label="文档核验工作台">
        <UploadWorkspace :busy="isCreating" :server-error="uploadError" @upload="handleUpload" />
        <JobProgress v-if="jobState" :state="jobState" />
      </section>

      <p class="workspace__privacy">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 3 5 6v5c0 4.6 2.9 8.2 7 10 4.1-1.8 7-5.4 7-10V6l-7-3Z" />
          <path d="m9 12 2 2 4-4" />
        </svg>
        文件仅用于本次核验，任务到期后将自动清理
      </p>
    </template>
  </main>
</template>

<style scoped>
.workspace {
  width: min(100% - 32px, 760px);
  margin: 0 auto;
  padding: 64px 0 40px;
}

.workspace--review {
  width: 100%;
  height: 100dvh;
  padding: 0;
  overflow: hidden;
}

.workspace__header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin-bottom: 30px;
}

.workspace__brand {
  display: grid;
  width: 56px;
  height: 56px;
  flex: 0 0 auto;
  place-items: center;
  color: #fff;
  background: linear-gradient(135deg, #5c75f7, #7958d9);
  border-radius: 16px;
  box-shadow: 0 10px 24px rgba(88, 86, 220, 0.24);
}

.workspace__brand svg {
  width: 30px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

h1 {
  margin: 0;
  color: #172033;
  font-size: clamp(1.75rem, 4vw, 2.25rem);
  line-height: 1.2;
  letter-spacing: -0.03em;
}

.workspace__header p {
  margin: 8px 0 0;
  color: #5f687a;
  font-size: 0.96rem;
}

.workspace__card {
  overflow: hidden;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(221, 227, 239, 0.9);
  border-radius: 24px;
  box-shadow: 0 20px 60px rgba(40, 53, 85, 0.1);
}

.workspace__privacy {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  margin: 20px 0 0;
  color: #667085;
  font-size: 0.8rem;
}

.workspace__privacy svg {
  width: 16px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

@media (max-width: 560px) {
  .workspace {
    padding-top: 32px;
  }

  .workspace__header {
    align-items: flex-start;
    justify-content: flex-start;
  }

  .workspace__brand {
    width: 48px;
    height: 48px;
    border-radius: 14px;
  }
}

@media (max-width: 1279px) {
  .workspace--review {
    height: auto;
    overflow: visible;
  }
}
</style>
