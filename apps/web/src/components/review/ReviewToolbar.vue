<script setup lang="ts">
import ExportPanel from './ExportPanel.vue'
import type { FileType } from '../../types/review'

defineProps<{
  jobId: string
  fileType: FileType
}>()
</script>

<template>
  <section class="review-toolbar__actions" aria-label="导出工具">
    <ExportPanel :job-id="jobId" :file-type="fileType" />
  </section>
</template>

<style scoped>
.review-toolbar__actions {
  display: flex;
  flex-direction: column;
  margin-top: 12px;
}

@media (min-width: 981px) {
  .review-toolbar__actions {
    min-height: 64px;
    margin-top: 8px;
  }
}
</style>
