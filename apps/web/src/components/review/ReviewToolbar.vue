<script setup lang="ts">
import { computed } from 'vue'

import BatchActions from './BatchActions.vue'
import ExportPanel from './ExportPanel.vue'
import FindReplace from './FindReplace.vue'
import type { CheckerFailureMap } from '../../types/analysis'
import type { FileType } from '../../types/review'
import { categoryLabel } from './presentation'

const props = defineProps<{
  jobId: string
  fileType: FileType
  checkerFailures: CheckerFailureMap
  batchLimit: number
  visibleIssueCount: number
  highRiskVisibleIssueCount: number
  batchDecisionError: string | null
  bulkActionPending: boolean
  findQuery: string
  replaceText: string
  findStatus: string
  canNavigateMatches: boolean
  canReplaceAllMatches: boolean
  findReplaceError: string | null
}>()

const emit = defineEmits<{
  acceptVisible: []
  ignoreVisible: []
  updateFindQuery: [value: string]
  updateReplaceText: [value: string]
  previousMatch: []
  nextMatch: []
  replaceAll: []
}>()

const failures = computed(() =>
  Object.entries(props.checkerFailures).flatMap(([category, failure]) =>
    failure ? [{ category, failure }] : []
  )
)
</script>

<template>
  <section class="review-toolbar__actions" aria-label="导出、批量与查找工具">
    <ExportPanel :job-id="jobId" :file-type="fileType" />
    <BatchActions
      :issue-count="visibleIssueCount"
      :batch-limit="batchLimit"
      :high-risk-security-count="highRiskVisibleIssueCount"
      :busy="bulkActionPending"
      :error="batchDecisionError"
      @accept-visible="emit('acceptVisible')"
      @ignore-visible="emit('ignoreVisible')"
    />
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

  <section
    v-if="failures.length"
    class="checker-failures"
    aria-label="未完成的检查类别"
  >
    <strong>部分检查未完成</strong>
    <ul>
      <li v-for="{ category, failure } in failures" :key="category">
        <span class="checker-failures__category">{{ categoryLabel(category) }}</span>
        <span>{{ failure.message }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.review-toolbar__actions {
  display: grid;
  grid-template-columns: minmax(260px, 0.9fr) minmax(280px, 0.9fr) minmax(320px, 1.1fr);
  gap: 12px;
  margin-top: 12px;
}

.checker-failures {
  display: flex;
  align-items: flex-start;
  gap: 18px;
  margin-top: 12px;
  padding: 12px 16px;
  color: #7c3f16;
  background: #fff6e8;
  border: 1px solid #f3d6ad;
  border-radius: 12px;
}

.checker-failures strong {
  flex: 0 0 auto;
  font-size: 0.84rem;
}

.checker-failures ul {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.checker-failures li {
  display: flex;
  gap: 7px;
  font-size: 0.8rem;
}

.checker-failures__category {
  font-weight: 800;
}

@media (min-width: 981px) {
  .review-toolbar {
    min-height: 64px;
  }

  .review-toolbar__actions {
    grid-template-columns: minmax(240px, 0.8fr) minmax(240px, 0.8fr) minmax(420px, 1.4fr);
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
