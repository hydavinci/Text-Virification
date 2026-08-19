<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'

import { exportsApiKey } from '../../api/exports'
import { ApiError } from '../../types/api'
import type {
  ExportDispatchStatus,
  ExportResponse,
  ExportType,
  ExportWarning
} from '../../types/exports'
import type { FileType } from '../../types/review'

const POLL_INTERVAL_MS = 2000

const props = defineProps<{
  jobId: string
  fileType: FileType
}>()

const injectedExportsApi = inject(exportsApiKey)

if (!injectedExportsApi) {
  throw new Error('ExportsApi is not provided.')
}

const exportsApi = injectedExportsApi

const exportOptionsByFileType: Record<
  FileType,
  ReadonlyArray<{ value: ExportType; label: string }>
> = {
  docx: [
    { value: 'modified_document', label: '修改版文件' },
    { value: 'html_report', label: 'HTML 报告' },
    { value: 'pdf_report', label: 'PDF 报告' }
  ],
  txt: [
    { value: 'modified_document', label: '修改版文件' },
    { value: 'html_report', label: 'HTML 报告' },
    { value: 'pdf_report', label: 'PDF 报告' }
  ],
  pdf: [
    { value: 'html_report', label: 'HTML 报告' },
    { value: 'pdf_report', label: 'PDF 报告' }
  ]
}

const exportOptions = computed(() => exportOptionsByFileType[props.fileType])
const selectedType = ref<ExportType>(exportOptions.value[0]?.value ?? 'html_report')
const currentExport = ref<ExportResponse | null>(null)
const dispatchStatus = ref<ExportDispatchStatus | null>(null)
const submitting = ref(false)
const polling = ref(false)
const requestError = ref<string | null>(null)
const confirmationMessage = ref<string | null>(null)
const confirmationWarnings = ref<ExportWarning[]>([])
const expirySignal = ref(0)

let active = true
let pollTimerId: ReturnType<typeof setTimeout> | null = null
let expiryTimerId: ReturnType<typeof setTimeout> | null = null
let pollGeneration = 0

const busy = computed(() => submitting.value || polling.value)

watch(
  exportOptions,
  (options) => {
    if (!options.some((option) => option.value === selectedType.value)) {
      selectedType.value = options[0]?.value ?? 'html_report'
    }
  },
  { immediate: true }
)

watch(selectedType, () => {
  stopPolling()
  clearExpiryTimer()
  currentExport.value = null
  dispatchStatus.value = null
  requestError.value = null
  confirmationMessage.value = null
  confirmationWarnings.value = []
})

const panelWarnings = computed(() =>
  confirmationWarnings.value.length
    ? confirmationWarnings.value
    : currentExport.value?.warnings ?? []
)

const warningHeading = computed(() =>
  confirmationWarnings.value.length ? '请确认以下导出警告' : '导出警告'
)

const warningMessage = computed(() => {
  if (confirmationMessage.value) {
    return confirmationMessage.value
  }

  if (currentExport.value?.warnings.length) {
    return '导出结果包含以下警告，请先查看后再下载。'
  }

  return ''
})

function getExpiryTime(exportState: ExportResponse | null): number | null {
  if (!exportState) {
    return null
  }

  const expiresAt = Date.parse(exportState.expires_at)
  return Number.isNaN(expiresAt) ? null : expiresAt
}

const isExpired = computed(() => {
  expirySignal.value

  const expiresAt = getExpiryTime(currentExport.value)
  if (expiresAt === null) {
    return false
  }

  return expiresAt <= Date.now()
})

const terminalError = computed(() => {
  if (isExpired.value) {
    return '导出文件已过期，请重新创建。'
  }

  if (currentExport.value?.status === 'failed') {
    return currentExport.value.error_message ?? '导出失败，请稍后重试。'
  }

  return null
})

const statusMessage = computed(() => {
  if (terminalError.value || !currentExport.value) {
    return null
  }

  switch (currentExport.value.status) {
    case 'queued':
      return dispatchStatus.value === 'deferred'
        ? '导出任务已排队，后台派发延迟，可稍后重试状态查询。'
        : '导出任务已排队，正在等待处理。'
    case 'processing':
      return '导出任务处理中，请稍候。'
    case 'completed':
      return '导出文件已生成，可直接下载。'
    case 'failed':
      return null
  }
})

const canDownload = computed(
  () => currentExport.value?.status === 'completed' && !isExpired.value
)

const downloadUrl = computed(() => {
  if (!canDownload.value || !currentExport.value) {
    return null
  }

  return exportsApi.downloadUrl(props.jobId, currentExport.value.export_id)
})

const canRetry = computed(() => {
  if (!terminalError.value && !requestError.value) {
    return false
  }

  if (confirmationWarnings.value.length) {
    return false
  }

  return true
})

const retryLabel = computed(() => {
  if (currentExport.value && !terminalError.value) {
    return '重试查询状态'
  }

  return '重新导出'
})

function clearTimer() {
  if (pollTimerId !== null) {
    clearTimeout(pollTimerId)
    pollTimerId = null
  }
}

function clearExpiryTimer() {
  if (expiryTimerId !== null) {
    clearTimeout(expiryTimerId)
    expiryTimerId = null
  }
}

function stopPolling() {
  pollGeneration += 1
  polling.value = false
  clearTimer()
}

function applyExportState(
  exportState: ExportResponse,
  nextDispatchStatus: ExportDispatchStatus | null = dispatchStatus.value
) {
  currentExport.value = exportState
  dispatchStatus.value = nextDispatchStatus
  requestError.value = null

  if (
    (exportState.status === 'queued' || exportState.status === 'processing') &&
    !isExpired.value
  ) {
    schedulePoll(exportState.export_id, pollGeneration + 1)
    return
  }

  stopPolling()
}

function schedulePoll(exportId: string, generation: number) {
  stopPolling()
  pollGeneration = generation
  polling.value = true
  pollTimerId = setTimeout(() => {
    void pollExport(exportId, generation)
  }, POLL_INTERVAL_MS)
}

async function pollExport(exportId: string, generation: number) {
  if (!active || generation !== pollGeneration) {
    return
  }

  try {
    const exportState = await exportsApi.get(props.jobId, exportId)
    if (!active || generation !== pollGeneration) {
      return
    }

    applyExportState(exportState)
  } catch (error) {
    if (!active || generation !== pollGeneration) {
      return
    }

    stopPolling()
    requestError.value = errorMessage(error, '无法获取导出状态，请重试。')
  }
}

async function createExport(confirmWarnings: boolean) {
  stopPolling()
  submitting.value = true
  requestError.value = null
  confirmationMessage.value = null
  confirmationWarnings.value = []

  try {
    const exportState = await exportsApi.create(props.jobId, {
      type: selectedType.value,
      confirm_warnings: confirmWarnings
    })
    if (!active) {
      return
    }

    applyExportState(exportState, exportState.dispatch_status)
  } catch (error) {
    if (!active) {
      return
    }

    currentExport.value = null
    dispatchStatus.value = null
    stopPolling()

    if (
      error instanceof ApiError &&
      error.detail.code === 'export_confirmation_required' &&
      error.detail.warnings?.length
    ) {
      confirmationMessage.value = error.detail.message
      confirmationWarnings.value = error.detail.warnings
      requestError.value = null
      return
    }

    requestError.value = errorMessage(error, '创建导出任务失败，请稍后重试。')
  } finally {
    if (active) {
      submitting.value = false
    }
  }
}

function retry() {
  if (currentExport.value && !terminalError.value) {
    const generation = pollGeneration + 1
    stopPolling()
    pollGeneration = generation
    polling.value = true
    void pollExport(currentExport.value.export_id, generation)
    return
  }

  void createExport(false)
}

function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.detail.message
  }

  if (error instanceof Error && error.message) {
    return error.message
  }

  return fallback
}

watch(
  currentExport,
  (exportState) => {
    clearExpiryTimer()
    expirySignal.value += 1

    const expiresAt = getExpiryTime(exportState)
    if (expiresAt === null) {
      return
    }

    const delay = expiresAt - Date.now()
    if (delay <= 0) {
      stopPolling()
      return
    }

    expiryTimerId = setTimeout(() => {
      expiryTimerId = null
      expirySignal.value += 1
      stopPolling()
    }, delay)
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  active = false
  stopPolling()
  clearExpiryTimer()
})
</script>

<template>
  <section class="export-panel" aria-label="导出文件">
    <div class="export-panel__heading">
      <div>
        <strong>导出文件</strong>
        <p>生成修改版文件或核验报告。</p>
      </div>
      <span>{{ fileType.toUpperCase() }}</span>
    </div>

    <div class="export-panel__controls">
      <label>
        <span>导出格式</span>
        <select v-model="selectedType" name="export-type" :disabled="busy">
          <option
            v-for="option in exportOptions"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
      </label>
      <button type="button" name="create-export" :disabled="busy" @click="createExport(false)">
        {{ busy ? '处理中…' : '创建导出' }}
      </button>
    </div>

    <div
      v-if="statusMessage"
      class="export-panel__status"
      data-testid="export-status"
      role="status"
    >
      {{ statusMessage }}
    </div>

    <div
      v-if="terminalError || requestError"
      class="export-panel__error"
      data-testid="export-error"
      role="alert"
    >
      <span>{{ terminalError ?? requestError }}</span>
      <button
        v-if="canRetry"
        type="button"
        name="retry-export"
        :disabled="busy"
        @click="retry"
      >
        {{ retryLabel }}
      </button>
    </div>

    <div
      v-if="panelWarnings.length"
      class="export-panel__warnings"
      data-testid="export-warnings"
      role="alert"
    >
      <strong>{{ warningHeading }}</strong>
      <p>{{ warningMessage }}</p>
      <ul>
        <li v-for="warning in panelWarnings" :key="`${warning.code}-${warning.issue_id}`">
          <span class="export-panel__warning-code">{{ warning.code }}</span>
          <span>{{ warning.message }}</span>
        </li>
      </ul>
      <button
        v-if="confirmationWarnings.length"
        type="button"
        name="confirm-export-warnings"
        :disabled="busy"
        @click="createExport(true)"
      >
        确认警告并继续导出
      </button>
    </div>

    <a
      v-if="downloadUrl"
      class="export-panel__download"
      data-testid="export-download-link"
      :href="downloadUrl"
      :download="currentExport?.file_name"
    >
      下载 {{ currentExport?.file_name }}
    </a>
  </section>
</template>

<style scoped>
.export-panel {
  display: grid;
  gap: 12px;
  min-width: 0;
  padding: 14px 16px;
  background: #fff;
  border: 1px solid #e2e7f0;
  border-radius: 16px;
}

.export-panel__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.export-panel__heading strong {
  display: block;
  color: #1c2538;
  font-size: 0.95rem;
}

.export-panel__heading p {
  margin: 4px 0 0;
  color: #667085;
  font-size: 0.8rem;
}

.export-panel__heading span {
  color: #5a6fe7;
  font-size: 0.78rem;
  font-weight: 700;
}

.export-panel__controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}

.export-panel__controls label {
  display: grid;
  gap: 6px;
  color: #475467;
  font-size: 0.8rem;
  font-weight: 600;
}

.export-panel__controls select,
.export-panel__controls button,
.export-panel__download,
.export-panel__error button,
.export-panel__warnings button {
  min-height: 44px;
  border-radius: 10px;
}

.export-panel__controls select {
  padding: 0 12px;
  color: #1c2538;
  background: #fff;
  border: 1px solid #c9d3e3;
}

.export-panel__controls button,
.export-panel__error button,
.export-panel__warnings button,
.export-panel__download {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 14px;
  color: #fff;
  font-weight: 700;
  text-decoration: none;
  background: #4256c9;
  border: 1px solid #4256c9;
  cursor: pointer;
}

.export-panel__controls button:disabled,
.export-panel__error button:disabled,
.export-panel__warnings button:disabled {
  opacity: 0.7;
  cursor: wait;
}

.export-panel__status {
  padding: 10px 12px;
  color: #1f4d7a;
  font-size: 0.82rem;
  background: #eef6ff;
  border: 1px solid #c7def7;
  border-radius: 12px;
}

.export-panel__error,
.export-panel__warnings {
  display: grid;
  gap: 10px;
  padding: 12px;
  border-radius: 12px;
}

@media (min-width: 981px) {
  .export-panel {
    gap: 6px;
    padding: 8px 10px;
  }

  .export-panel__heading {
    align-items: center;
  }

  .export-panel__heading strong {
    font-size: 0.84rem;
  }

  .export-panel__heading p {
    display: none;
  }

  .export-panel__controls {
    gap: 8px;
  }

  .export-panel__controls label {
    gap: 3px;
    font-size: 0.72rem;
  }
}

.export-panel__error {
  color: #8a2424;
  background: #fff1f1;
  border: 1px solid #f4caca;
}

.export-panel__error button {
  justify-self: start;
  color: #4256c9;
  background: #fff;
}

.export-panel__warnings {
  color: #7c3f16;
  background: #fff6e8;
  border: 1px solid #f3d6ad;
}

.export-panel__warnings strong {
  color: #6a3512;
}

.export-panel__warnings p,
.export-panel__warnings ul {
  margin: 0;
}

.export-panel__warnings ul {
  display: grid;
  gap: 8px;
  padding-left: 18px;
}

.export-panel__warning-code {
  display: inline-block;
  margin-right: 8px;
  font-weight: 700;
}

.export-panel__download {
  justify-self: start;
}

select:focus-visible,
button:focus-visible,
a:focus-visible {
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
}

@media (max-width: 980px) {
  .export-panel__controls {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
