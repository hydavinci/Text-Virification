<script setup lang="ts">
import { computed, ref } from 'vue'

import CheckOptions from './CheckOptions.vue'
import type { JobCreateOptions } from '../types/jobs'
import { CHECK_CATEGORY_VALUES, type CheckCategory, type CheckScenario } from '../types/review'

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['docx', 'pdf', 'txt']
const CATEGORY_REQUIRED_MESSAGE = '至少选择一类检查'

type UploadOptionsSnapshot = Readonly<Required<JobCreateOptions>>

const props = defineProps<{
  serverError?: string | null
  busy?: boolean
}>()

const emit = defineEmits<{
  upload: [file: File, options: UploadOptionsSnapshot]
}>()

const validationError = ref<string | null>(null)
const isDragging = ref(false)
const selectedScenario = ref<CheckScenario>('general')
const enabledCategories = ref<CheckCategory[]>([...CHECK_CATEGORY_VALUES])

const visibleError = computed(() => validationError.value ?? props.serverError ?? null)

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement

  if (props.busy) {
    input.value = ''
    return
  }

  const file = input.files?.[0]

  validateAndUpload(file)
  input.value = ''
}

function handleDragEnter() {
  if (!props.busy) {
    isDragging.value = true
  }
}

function handleDragLeave() {
  isDragging.value = false
}

function handleScenarioChange(scenario: CheckScenario) {
  selectedScenario.value = scenario
}

function handleEnabledCategoriesChange(categories: CheckCategory[]) {
  enabledCategories.value = [...categories]

  if (categories.length > 0 && validationError.value === CATEGORY_REQUIRED_MESSAGE) {
    validationError.value = null
  }
}

function validateAndUpload(file?: File) {
  if (!file) {
    validationError.value = null
    return
  }
  const extension = file.name.split('.').pop()?.toLowerCase()

  if (!extension || !ACCEPTED_EXTENSIONS.includes(extension)) {
    validationError.value = '请选择 DOCX、PDF 或 TXT 格式的文件。'
    return
  }

  if (file.size > MAX_UPLOAD_BYTES) {
    validationError.value = '文件大小不能超过 25 MiB。'
    return
  }

  if (enabledCategories.value.length < 1) {
    validationError.value = CATEGORY_REQUIRED_MESSAGE
    return
  }

  validationError.value = null
  emit('upload', file, buildUploadOptions())
}

function buildUploadOptions(): UploadOptionsSnapshot {
  const enabledCategoriesSnapshot = Object.freeze([
    ...enabledCategories.value
  ]) as UploadOptionsSnapshot['enabledCategories']

  return Object.freeze({
    scenario: selectedScenario.value,
    enabledCategories: enabledCategoriesSnapshot
  }) as UploadOptionsSnapshot
}

function handleDrop(event: DragEvent) {
  isDragging.value = false
  if (!props.busy) {
    validateAndUpload(event.dataTransfer?.files[0])
  }
}
</script>

<template>
  <section class="upload">
    <div class="upload__heading">
      <span>1</span>
      <div>
        <h2>上传待核验文档</h2>
        <p>选择一份源文件开始智能核验</p>
      </div>
    </div>

    <CheckOptions
      :busy="busy"
      :scenario="selectedScenario"
      :enabled-categories="enabledCategories"
      @update:scenario="handleScenarioChange"
      @update:enabled-categories="handleEnabledCategoriesChange"
    />

    <label
      data-testid="upload-dropzone"
      class="upload__dropzone"
      :class="{ 'upload__dropzone--active': isDragging && !busy, 'upload__dropzone--busy': busy }"
      @dragenter.prevent="handleDragEnter"
      @dragover.prevent="handleDragEnter"
      @dragleave.prevent="handleDragLeave"
      @drop.prevent="handleDrop"
    >
      <span class="upload__icon" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" />
          <path d="M5 14v4a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4" />
        </svg>
      </span>
      <strong>{{ busy ? '正在创建核验任务…' : '点击选择或拖拽文件到此处' }}</strong>
      <span class="upload__hint">支持 DOCX、PDF、TXT 格式，文件大小不超过 25 MiB</span>
      <span class="upload__button">{{ busy ? '请稍候' : '选择文件' }}</span>
      <span class="sr-only">选择待核验文档</span>
      <input
        :disabled="busy"
        type="file"
        accept=".docx,.pdf,.txt"
        @change="handleFileChange"
      />
    </label>
    <p v-if="visibleError" class="upload__error" role="alert">
      <span aria-hidden="true">!</span>
      {{ visibleError }}
    </p>
  </section>
</template>

<style scoped>
.upload {
  padding: 34px;
}

.upload__heading {
  display: flex;
  align-items: center;
  gap: 13px;
  margin-bottom: 24px;
}

.upload__heading > span {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  color: #fff;
  font-size: 0.88rem;
  font-weight: 700;
  background: #5b6ff2;
  border-radius: 10px;
}

h2 {
  margin: 0;
  color: #20283a;
  font-size: 1.1rem;
}

.upload__heading p {
  margin: 4px 0 0;
  color: #667085;
  font-size: 0.82rem;
}

.upload__dropzone {
  display: flex;
  min-height: 286px;
  padding: 34px 24px;
  cursor: pointer;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  text-align: center;
  background: #f8f9ff;
  border: 2px dashed #cfd6ef;
  border-radius: 18px;
  transition:
    border-color 160ms ease,
    background 160ms ease,
    transform 160ms ease;
}

.upload__dropzone:hover,
.upload__dropzone--active {
  background: #f2f4ff;
  border-color: #687af1;
  transform: translateY(-1px);
}

.upload__dropzone--busy {
  cursor: wait;
  opacity: 0.72;
}

.upload__dropzone:focus-within {
  outline: 3px solid rgba(91, 111, 242, 0.25);
  outline-offset: 3px;
}

.upload__icon {
  display: grid;
  width: 64px;
  height: 64px;
  margin-bottom: 18px;
  place-items: center;
  color: #5b6ff2;
  background: #e9ecff;
  border-radius: 18px;
}

.upload__icon svg {
  width: 31px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

.upload__dropzone strong {
  color: #30394d;
  font-size: 1rem;
}

.upload__hint {
  margin-top: 8px;
  color: #667085;
  font-size: 0.82rem;
}

.upload__button {
  margin-top: 22px;
  padding: 10px 25px;
  color: #fff;
  font-size: 0.88rem;
  font-weight: 650;
  background: linear-gradient(135deg, #6278f7, #725ee4);
  border-radius: 10px;
  box-shadow: 0 8px 18px rgba(93, 104, 225, 0.24);
}

.upload__dropzone input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}

.upload__error {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 16px 0 0;
  padding: 12px 14px;
  color: #a53535;
  font-size: 0.86rem;
  background: #fff2f2;
  border-radius: 10px;
}

.upload__error > span {
  display: grid;
  width: 19px;
  height: 19px;
  flex: 0 0 auto;
  place-items: center;
  color: #fff;
  font-size: 0.72rem;
  font-weight: 800;
  background: #d85353;
  border-radius: 50%;
}

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

@media (max-width: 560px) {
  .upload {
    padding: 24px 20px;
  }

  .upload__dropzone {
    min-height: 250px;
  }
}
</style>
