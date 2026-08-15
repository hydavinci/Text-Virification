<script setup lang="ts">
import { computed, ref } from 'vue'

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['docx', 'pdf', 'txt']

const props = defineProps<{
  serverError?: string | null
  busy?: boolean
}>()

const emit = defineEmits<{
  upload: [file: File]
}>()

const validationError = ref<string | null>(null)

const visibleError = computed(() => validationError.value ?? props.serverError ?? null)

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]

  if (!file) {
    validationError.value = null
    return
  }

  const extension = file.name.split('.').pop()?.toLowerCase()

  if (!extension || !ACCEPTED_EXTENSIONS.includes(extension)) {
    validationError.value = 'Please upload a DOCX、PDF 或 TXT file.'
    input.value = ''
    return
  }

  if (file.size > MAX_UPLOAD_BYTES) {
    validationError.value = 'Please upload a file that is 25 MiB or smaller.'
    input.value = ''
    return
  }

  validationError.value = null
  emit('upload', file)
  input.value = ''
}
</script>

<template>
  <section>
    <h2>Upload source document</h2>
    <p>Accepted formats: DOCX, PDF, TXT. Maximum size: 25 MiB.</p>
    <label>
      <span class="sr-only">Select a source document</span>
      <input
        :disabled="busy"
        type="file"
        accept=".docx,.pdf,.txt"
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
</style>
