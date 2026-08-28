<script setup lang="ts">
import { computed, ref } from 'vue'

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['docx', 'doc', 'pdf', 'txt', 'rtf', 'md', 'csv']

const props = defineProps<{
  serverError?: string | null
  busy?: boolean
}>()

const emit = defineEmits<{
  upload: [file: File]
}>()

const validationError = ref<string | null>(null)
const isDragging = ref(false)

const visibleError = computed(() => validationError.value ?? props.serverError ?? null)

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]

  if (!file) {
    validationError.value = null
    return
  }

  validateAndEmit(file)
  input.value = ''
}

function handleDrop(event: DragEvent) {
  isDragging.value = false
  const file = event.dataTransfer?.files[0]
  if (file) {
    validateAndEmit(file)
  }
}

function validateAndEmit(file: File) {
  const extension = file.name.split('.').pop()?.toLowerCase()

  if (!extension || !ACCEPTED_EXTENSIONS.includes(extension)) {
    validationError.value = 'Please upload a DOCX、PDF 或 TXT file，或 DOC、RTF、MD、CSV 文件.'
    return
  }

  if (file.size > MAX_UPLOAD_BYTES) {
    validationError.value = 'Please upload a file that is 25 MiB or smaller.'
    return
  }

  validationError.value = null
  emit('upload', file)
}
</script>

<template>
  <section class="upload-workspace">
    <label
      class="dropzone"
      :class="{ busy, dragging: isDragging }"
      @dragenter.prevent="isDragging = true"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="handleDrop"
    >
      <span class="upload-icon">↑</span>
      <strong>{{ busy ? '正在检查文档…' : '将文件拖到此处，或点击选择文件' }}</strong>
      <span>支持 DOCX、DOC、PDF、TXT、RTF、MD、CSV · 最大 25 MiB</span>
      <span class="sr-only">Select a source document</span>
      <input
        :disabled="busy"
        type="file"
        accept=".docx,.doc,.pdf,.txt,.rtf,.md,.csv"
        @change="handleFileChange"
      />
    </label>
    <p v-if="visibleError" role="alert">{{ visibleError }}</p>
  </section>
</template>

<style scoped>
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
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
.dropzone:hover {
  border-color: #2563eb;
  color: #2563eb;
  background: color-mix(in srgb, #dbeafe 74%, transparent);
}
.dropzone.dragging {
  border-style: solid;
  border-color: #06b6d4;
  color: #0369a1;
  transform: translateY(-2px);
}
.dropzone.busy { opacity: .6; cursor: wait; }
.dropzone input { position: absolute; width: 1px; height: 1px; opacity: 0; }
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
.dropzone strong { color: inherit; }
.dropzone span:last-of-type { font-size: 12px; }
[role='alert'] { color: #be123c; font-weight: 700; }
</style>
