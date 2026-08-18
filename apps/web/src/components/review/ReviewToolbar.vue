<script setup lang="ts">
import { computed } from 'vue'

import BatchActions from './BatchActions.vue'
import FindReplace from './FindReplace.vue'
import type {
  AnalysisSummaryResponse,
  CheckerFailureMap
} from '../../types/analysis'
import type { FileType } from '../../types/review'

const props = defineProps<{
  sourceName: string
  fileType: FileType
  summary: AnalysisSummaryResponse | null
  loading: boolean
  error: string | null
  checkerFailures: CheckerFailureMap
  batchLimit: number
  visibleIssueCount: number
  visibleIssueOverflow: boolean
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
  retry: []
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
  <header class="review-toolbar">
    <div>
      <p class="review-toolbar__eyebrow">文档审阅</p>
      <h1>{{ sourceName }}</h1>
      <p class="review-toolbar__meta">
        {{ fileType.toUpperCase() }}
        <span aria-hidden="true">·</span>
        {{ summary ? `${summary.total_issues} 个问题` : '正在读取问题总览' }}
      </p>
    </div>

    <p v-if="loading" class="review-toolbar__status" role="status">正在加载总览…</p>
    <div v-else-if="error" class="review-toolbar__error" role="alert">
      <span>{{ error }}</span>
      <button type="button" @click="emit('retry')">重试总览</button>
    </div>
  </header>

  <section class="review-toolbar__actions" aria-label="批量与查找工具">
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
        <code>{{ category }}</code>
        <span>{{ failure.message }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.review-toolbar {
  display: flex;
  min-height: 92px;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 18px 24px;
  background: #fff;
  border: 1px solid #e2e7f0;
  border-radius: 18px;
  box-shadow: 0 12px 36px rgba(36, 49, 80, 0.08);
}

.review-toolbar__eyebrow {
  margin: 0 0 4px;
  color: #5a6fe7;
  font-size: 0.75rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  color: #1c2538;
  font-size: 1.35rem;
}

.review-toolbar__meta {
  display: flex;
  gap: 7px;
  margin: 6px 0 0;
  color: #697287;
  font-size: 0.8rem;
}

.review-toolbar__status {
  margin: 0;
  color: #667085;
}

.review-toolbar__error {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #a53636;
}

button {
  padding: 7px 11px;
  color: #4256c9;
  font-weight: 700;
  background: #eef0ff;
  border: 0;
  border-radius: 8px;
  cursor: pointer;
}

.review-toolbar__actions {
  display: grid;
  grid-template-columns: minmax(280px, 0.9fr) minmax(320px, 1.1fr);
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

.checker-failures code {
  font-weight: 800;
}

@media (max-width: 980px) {
  .review-toolbar__actions {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
