<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import {
  unicodeCodePointLength,
  validateDirectText
} from '../../validation/verificationLimits'

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['docx', 'doc', 'pdf', 'txt', 'rtf', 'md', 'csv']

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
    validateAndSubmitFile(file)
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
    validateAndSubmitFile(file)
  }
}

function validateAndSubmitFile(file: File): void {
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (!extension || !ACCEPTED_EXTENSIONS.includes(extension)) {
    validationError.value =
      'Please upload a DOCX、PDF 或 TXT file，或 DOC、RTF、MD、CSV 文件.'
    return
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    validationError.value = '文件大小不能超过 25 MiB。'
    return
  }
  validationError.value = null
  emit('submit-file', file)
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
    <div class="mode-tabs" aria-label="输入方式">
      <button
        data-mode="file"
        :class="{ active: mode === 'file' }"
        :aria-pressed="mode === 'file'"
        type="button"
        @click="mode = 'file'"
      >
        上传文件
      </button>
      <button
        data-mode="text"
        :class="{ active: mode === 'text' }"
        :aria-pressed="mode === 'text'"
        type="button"
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
      <span class="upload-icon" aria-hidden="true">↑</span>
      <strong>{{ busy ? '正在检查文档…' : '将文件拖到此处，或点击选择文件' }}</strong>
      <span>支持 DOCX、DOC、PDF、TXT、RTF、MD、CSV · 最大 25 MiB</span>
    </div>
    <input
      v-if="mode === 'file'"
      ref="fileInput"
      :disabled="busy"
      type="file"
      accept=".docx,.doc,.pdf,.txt,.rtf,.md,.csv"
      hidden
      tabindex="-1"
      aria-hidden="true"
      @change="handleFileChange"
    />

    <div v-else class="text-mode">
      <label for="source-text">待检查文本</label>
      <textarea
        id="source-text"
        :value="draft"
        placeholder="在此粘贴需要检查的文本内容…"
        @input="updateDraft"
        @keydown="handleTextKeydown"
      />
      <div class="text-footer">
        <span>{{ draftCodePoints.toLocaleString() }} 字符</span>
        <span>Ctrl/⌘ + Enter 快速提交</span>
        <button
          class="btn primary"
          :disabled="busy"
          type="button"
          @click="submitText"
        >
          开始检查
        </button>
      </div>
    </div>

    <p v-if="visibleError" role="alert">{{ visibleError }}</p>
  </section>
</template>

<style scoped>
.mode-tabs {
  width: fit-content;
  margin-bottom: 20px;
  padding: 4px;
  display: flex;
  gap: 5px;
  border-radius: 12px;
  background: var(--surface-2);
}
.mode-tabs button {
  padding: 9px 17px;
  border: 0;
  border-radius: 9px;
  color: var(--muted);
  background: transparent;
  cursor: pointer;
  font-weight: 700;
}
.mode-tabs button.active {
  color: var(--primary);
  background: var(--surface);
  box-shadow: 0 3px 10px rgba(15, 23, 42, .08);
}
.btn {
  padding: 9px 15px;
  border: 1px solid transparent;
  border-radius: 11px;
  font-weight: 700;
  cursor: pointer;
}
.btn:disabled {
  opacity: .55;
  cursor: wait;
}
.btn.primary {
  color: white;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
  box-shadow: 0 7px 18px rgba(37, 99, 235, .2);
}
.dropzone {
  min-height: 280px;
  padding: 34px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 1.5px dashed #94a3b8;
  border-radius: 16px;
  color: #64748b;
  background: color-mix(in srgb, #eff6ff 70%, transparent);
  cursor: pointer;
  transition: .2s;
}
.dropzone:hover,
.dropzone:focus-visible {
  border-color: #2563eb;
  color: #2563eb;
  outline: 3px solid rgba(37, 99, 235, .14);
}
.dropzone.dragging {
  border-style: solid;
  border-color: #06b6d4;
  color: #0369a1;
  transform: translateY(-2px);
}
.dropzone.busy {
  opacity: .6;
  cursor: wait;
}
.upload-icon {
  width: 56px;
  height: 56px;
  display: grid;
  place-items: center;
  border-radius: 18px;
  color: white;
  background: linear-gradient(135deg, #2563eb, #06b6d4);
  font-size: 30px;
  box-shadow: 0 10px 22px rgba(37, 99, 235, .22);
}
.text-mode > label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 700;
}
.text-mode textarea {
  width: 100%;
  min-height: 280px;
  padding: 18px;
  resize: vertical;
  border: 1px solid var(--border);
  border-radius: 15px;
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
  color: #be123c;
  font-weight: 700;
}
@media (max-width: 680px) {
  .text-footer {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
