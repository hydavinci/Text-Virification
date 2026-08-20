<script setup lang="ts">
import ExportPanel from './ExportPanel.vue'
import FindReplace from './FindReplace.vue'
import type { FileType } from '../../types/review'

const props = defineProps<{
  jobId: string
  fileType: FileType
  bulkActionPending: boolean
  findQuery: string
  replaceText: string
  findStatus: string
  canNavigateMatches: boolean
  canReplaceAllMatches: boolean
  findReplaceError: string | null
}>()

const emit = defineEmits<{
  updateFindQuery: [value: string]
  updateReplaceText: [value: string]
  previousMatch: []
  nextMatch: []
  replaceAll: []
}>()
</script>

<template>
  <section class="review-toolbar__actions" aria-label="导出与查找工具">
    <ExportPanel :job-id="jobId" :file-type="fileType" />
    <FindReplace
      :query="findQuery"
      :replacement="replaceText"
      :status="findStatus"
      :can-navigate="canNavigateMatches"
      :can-replace-all="canReplaceAllMatches"
      :busy="bulkActionPending"
      :error="findReplaceError"
      @update-query="emit('updateFindQuery', $event)"
      @update-replacement="emit('updateReplaceText', $event)"
      @previous-match="emit('previousMatch')"
      @next-match="emit('nextMatch')"
      @replace-all="emit('replaceAll')"
    />
  </section>
</template>

<style scoped>
.review-toolbar__actions {
  display: grid;
  grid-template-columns: minmax(260px, 0.9fr) minmax(320px, 1.1fr);
  gap: 12px;
  margin-top: 12px;
}

@media (min-width: 981px) {
  .review-toolbar {
    min-height: 64px;
  }

  .review-toolbar__actions {
    grid-template-columns: minmax(240px, 0.8fr) minmax(420px, 1.4fr);
    gap: 8px;
    margin-top: 8px;
  }
}

@media (max-width: 980px) {
  .review-toolbar__actions {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
