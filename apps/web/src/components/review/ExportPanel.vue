<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'

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
  open: boolean
}>()

const emit = defineEmits<{
  close: []
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
const dialog = ref<HTMLElement | null>(null)

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

function focusableElements(): HTMLElement[] {
  if (!dialog.value) {
    return []
  }

  return Array.from(
    dialog.value.querySelectorAll<HTMLElement>(
      'button:not(:disabled), select:not(:disabled), input:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])'
    )
  ).filter((element) => !element.hasAttribute('disabled') && element.tabIndex !== -1)
}

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

function onDialogKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }

  if (event.key !== 'Tab') {
    return
  }

  const focusable = focusableElements()
  const first = focusable[0]
  const last = focusable.at(-1)

  if (!first || !last) {
    return
  }

  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
    return
  }

  if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
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

watch(
  () => props.open,
  async (open) => {
    if (!open) {
      return
    }

    await nextTick()
    focusableElements()[0]?.focus()
  }
)

onBeforeUnmount(() => {
  active = false
  stopPolling()
  clearExpiryTimer()
})
</script>

<template>
  <div v-show="open" class="export-panel-overlay">
    <div
      class="export-panel-overlay__backdrop"
      data-testid="export-backdrop"
      @pointerdown.self="emit('close')"
    />

    <section
      ref="dialog"
      class="export-panel"
      role="dialog"
      aria-modal="true"
      aria-label="导出文件"
      tabindex="-1"
      @keydown="onDialogKeydown"
    >
      <div class="export-panel__heading">
        <div>
          <strong>导出文件</strong>
          <p>生成修改版文件或核验报告。</p>
        </div>
        <div class="export-panel__heading-actions">
          <span>{{ fileType.toUpperCase() }}</span>
          <button
            type="button"
            class="export-panel__close"
            aria-label="关闭导出"
            @click="emit('close')"
          >
            ×
          </button>
        </div>
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
  </div>
</template>

<style scoped>
.export-panel-overlay {
  position: absolute;
  inset: 0;
  z-index: 20;
  overflow: visible;
  pointer-events: none;
}

.export-panel-overlay__backdrop {
  position: fixed;
  inset: 0;
  background: rgba(28, 37, 56, 0.2);
  pointer-events: auto;
}

.export-panel {
  position: absolute;
  left: calc(100% + 12px);
  bottom: 0;
  display: grid;
  gap: var(--review-space-3);
  min-width: 0;
  width: min(360px, calc(100vw - 32px));
  max-height: calc(100dvh - 48px);
  padding: calc(var(--review-space-3) + 2px) var(--review-space-4);
  overflow: auto;
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) + var(--review-space-1));
  box-shadow: 0 20px 48px rgba(15, 23, 42, 0.18);
  pointer-events: auto;
}

.export-panel__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--review-space-3);
  flex-wrap: wrap;
}

.export-panel__heading strong {
  display: block;
  color: var(--review-text);
  font-size: 0.95rem;
}

.export-panel__heading p {
  margin: 4px 0 0;
  color: var(--review-text-muted);
  font-size: 0.8rem;
}

.export-panel__heading-actions {
  display: flex;
  align-items: center;
  gap: calc(var(--review-space-2) + 2px);
}

.export-panel__heading span {
  color: var(--review-accent);
  font-size: 0.78rem;
  font-weight: 700;
  white-space: nowrap;
}

.export-panel__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  min-height: 44px;
  padding: 0;
  color: var(--review-text-muted);
  font-size: 1.4rem;
  line-height: 1;
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) - 2px);
  cursor: pointer;
}

.export-panel__controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(152px, 1fr));
  gap: calc(var(--review-space-2) + 2px);
}

.export-panel__controls label {
  display: grid;
  gap: 6px;
  color: var(--review-text-muted);
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
  padding: 0 var(--review-space-3);
  color: var(--review-text);
  background: var(--review-surface);
  border: 1px solid var(--review-border);
}

.export-panel__controls button,
.export-panel__error button,
.export-panel__warnings button,
.export-panel__download {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 calc(var(--review-space-3) + 2px);
  color: var(--review-surface);
  font-weight: 700;
  white-space: nowrap;
  text-decoration: none;
  background: var(--review-accent);
  border: 1px solid var(--review-accent);
  cursor: pointer;
}

.export-panel__controls button:disabled,
.export-panel__error button:disabled,
.export-panel__warnings button:disabled {
  opacity: 0.7;
  cursor: wait;
}

.export-panel__status {
  padding: calc(var(--review-space-2) + 2px) var(--review-space-3);
  color: #1f4d7a;
  font-size: 0.82rem;
  background: #eef6ff;
  border: 1px solid #c7def7;
  border-radius: var(--review-panel-radius);
}

.export-panel__error,
.export-panel__warnings {
  display: grid;
  gap: calc(var(--review-space-2) + 2px);
  padding: var(--review-space-3);
  border-radius: var(--review-panel-radius);
}

.export-panel__error {
  color: #8a2424;
  background: #fff1f1;
  border: 1px solid #f4caca;
}

.export-panel__error button {
  justify-self: start;
  color: var(--review-accent);
  background: var(--review-surface);
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
  gap: var(--review-space-2);
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
</style>
