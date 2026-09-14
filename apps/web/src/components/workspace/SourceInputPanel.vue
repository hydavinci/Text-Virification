<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
  unicodeCodePointLength,
  validateDirectText
} from '../../validation/verificationLimits'

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['docx', 'doc', 'pdf', 'txt', 'rtf', 'md', 'csv', 'png', 'jpg', 'jpeg']

const props = withDefaults(defineProps<{
  busy?: boolean
  serverError?: string | null
  text?: string
}>(), {
  busy: false,
  serverError: null,
  text: ''
})

const emit = defineEmits<{
  'submit-text': [text: string]
  'submit-file': [file: File]
  'update:text': [text: string]
}>()

const mode = ref<'file' | 'text'>('file')
const draft = ref(props.text)
const validationError = ref<string | null>(null)
const isDragging = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)

const visibleError = computed(
  () => validationError.value ?? props.serverError ?? null
)
const draftCodePoints = computed(() => unicodeCodePointLength(draft.value))

watch(
  () => props.text,
  (value) => {
    if (value !== draft.value) {
      draft.value = value
    }
  }
)

function updateDraft(event: Event): void {
  const value = (event.target as HTMLTextAreaElement).value
  draft.value = value
  emit('update:text', value)
  validationError.value = null
}

function submitText(): void {
  if (props.busy) {
    return
  }
  const validation = validateDirectText(draft.value)
  if (validation !== null) {
    validationError.value =
      validation === 'empty'
        ? '请先输入需要检查的文本。'
        : validation === 'too_many_code_points'
          ? '文本不能超过 5,000,000 个 Unicode 字符。'
          : '文本的 UTF-8 大小不能超过 25 MiB。'
    return
  }
  validationError.value = null
  emit('submit-text', draft.value)
}

function handleTextKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    submitText()
  }
}

function handleFileChange(event: Event): void {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) {
    selectFile(file)
  }
  input.value = ''
}

function handleDrop(event: DragEvent): void {
  isDragging.value = false
  if (props.busy) {
    return
  }
  const file = event.dataTransfer?.files[0]
  if (file) {
    selectFile(file)
  }
}

function selectFile(file: File): void {
  if (props.busy) {
    return
  }
  selectedFile.value = null
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (!extension || !ACCEPTED_EXTENSIONS.includes(extension)) {
    validationError.value =
      '请选择 DOCX、DOC、PDF、TXT、RTF、MD、CSV、PNG 或 JPEG 文件。'
    return
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    validationError.value = '文件大小不能超过 25 MiB。'
    return
  }
  validationError.value = null
  selectedFile.value = file
}

function submitSource(): void {
  if (props.busy) return
  if (mode.value === 'text') {
    submitText()
  } else if (selectedFile.value) {
    emit('submit-file', selectedFile.value)
  } else {
    validationError.value = '请先选择需要检查的文件。'
  }
}

function removeFile(): void {
  if (props.busy) return
  selectedFile.value = null
  validationError.value = null
}

function openFilePicker(): void {
  if (!props.busy) {
    fileInput.value?.click()
  }
}

function handleDropzoneKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    openFilePicker()
  }
}
</script>

<template>
  <section class="source-input-panel">
    <div class="mode-tabs ui-tabs" aria-label="输入方式">
      <button
        data-mode="file"
        :class="{ active: mode === 'file' }"
        :aria-pressed="mode === 'file'"
        type="button"
        :disabled="busy"
        @click="mode = 'file'"
      >
        上传文件
      </button>
      <button
        data-mode="text"
        :class="{ active: mode === 'text' }"
        :aria-pressed="mode === 'text'"
        type="button"
        :disabled="busy"
        @click="mode = 'text'"
      >
        粘贴文本
      </button>
    </div>

    <div
      v-if="mode === 'file'"
      class="dropzone"
      :class="{ busy, dragging: isDragging }"
      data-dropzone
      role="button"
      tabindex="0"
      :aria-disabled="busy"
      aria-label="选择或拖放待检查文件"
      @click="openFilePicker"
      @keydown="handleDropzoneKeydown"
      @dragenter.prevent="isDragging = true"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="handleDrop"
    >
      <svg class="upload-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
        <path d="M12 16V4m-4 4 4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
      </svg>
      <strong>{{ selectedFile ? '文件已就绪，可点击更换' : '拖放文档到这里' }}</strong>
      <span class="choose-file">{{ selectedFile ? '更换文件' : '或点击选择文件' }}</span>
      <small>DOCX、DOC、PDF、TXT、RTF、MD、CSV、PNG、JPEG · 最大 25 MiB</small>
    </div>
    <input
      v-if="mode === 'file'"
      ref="fileInput"
      :disabled="busy"
      type="file"
      accept=".docx,.doc,.pdf,.txt,.rtf,.md,.csv,.png,.jpg,.jpeg"
      hidden
      tabindex="-1"
      aria-hidden="true"
      @change="handleFileChange"
    />

    <div v-if="mode === 'file' && selectedFile" class="selected-file" data-selected-file>
      <div>
        <strong>{{ selectedFile.name }}</strong>
        <small>{{ (selectedFile.size / 1024).toFixed(1) }} KB · 等待开始检查</small>
      </div>
      <button type="button" data-remove-file :disabled="busy" @click="removeFile">
        移除
      </button>
    </div>

    <div v-if="mode === 'text'" class="text-mode">
      <label for="source-text">待检查文本</label>
      <textarea
        id="source-text"
        :value="draft"
        :disabled="busy"
        placeholder="在此粘贴需要检查的文本内容…"
        @input="updateDraft"
        @keydown="handleTextKeydown"
      />
      <div class="text-footer">
        <span>{{ draftCodePoints.toLocaleString() }} 字符</span>
        <span>Ctrl/⌘ + Enter 快速提交</span>
      </div>
    </div>

    <p v-if="visibleError" role="alert">{{ visibleError }}</p>
    <slot name="settings" />
    <div class="submit-row">
      <button
        class="btn primary ui-button ui-button--primary"
        data-submit-source
        :disabled="busy"
        type="button"
        @click="submitSource"
      >
        {{ busy ? '正在检查…' : '开始检查' }}
        <span v-if="!busy" aria-hidden="true">→</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.mode-tabs {
  width: fit-content;
  margin-bottom: 20px;
}
.btn:disabled, button:disabled {
  opacity: .55;
  cursor: not-allowed;
}
.dropzone {
  min-height: 220px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-panel);
  color: var(--muted);
  background: color-mix(in srgb, var(--primary-soft) 35%, var(--surface));
  text-align: center;
  cursor: pointer;
  transition: border-color .15s;
}
.dropzone:hover,
.dropzone:focus-visible {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-soft);
}
.dropzone.dragging {
  border-style: solid;
  border-color: var(--primary);
  color: var(--primary);
}
.dropzone.busy {
  opacity: .6;
  cursor: wait;
}
.upload-icon {
  width: 52px;
  height: 52px;
  padding: 12px;
  border-radius: 14px;
  background: var(--primary-soft);
  margin-bottom: 4px;
  color: var(--primary);
}
.dropzone strong { color: var(--text); font-size: 16px; font-weight: 500; }
.dropzone small { margin-top: 8px; font-size: 12px; line-height: 1.7; }
.choose-file { color: var(--primary); font-size: 13px; }
.selected-file { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 12px; padding: 12px; border: 1px solid var(--border); border-radius: 8px; }
.selected-file > div { min-width: 0; }
.selected-file strong { display: block; overflow-wrap: anywhere; font-size: 13px; font-weight: 500; }
.selected-file small { display: block; color: var(--muted); margin-top: 4px; font-size: 12px; }
.selected-file button { flex: 0 0 auto; border: 0; padding: 8px; color: var(--muted); background: transparent; cursor: pointer; }
.submit-row { display: flex; justify-content: flex-end; margin-top: 20px; }
.submit-row .btn { min-height: 42px; min-width: 148px; gap: 20px; }
.text-mode > label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 700;
}
.text-mode textarea {
  width: 100%;
  min-height: 220px;
  padding: 18px;
  resize: vertical;
  border: 1px solid var(--border);
  border-radius: 10px;
  color: var(--text);
  background: var(--surface-2);
  outline: none;
  line-height: 1.8;
}
.text-mode textarea:focus {
  border-color: var(--primary);
  outline: 3px solid rgba(37, 99, 235, .1);
}
.text-footer {
  margin-top: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: var(--muted);
  font-size: 12px;
}
[role='alert'] {
  color: var(--danger);
  font-weight: 500;
}
@media (max-width: 680px) {
  .text-footer {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
