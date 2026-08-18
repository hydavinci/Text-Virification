<script setup lang="ts">
import type { AnalysisSummaryResponse, Issue } from '../../types/analysis'

defineProps<{
  summary: AnalysisSummaryResponse | null
  issues: Issue[]
  selectedIssueId: string | null
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{
  select: [issueId: string]
  retry: []
}>()
</script>

<template>
  <nav class="review-navigation" aria-label="问题筛选">
    <div class="review-navigation__heading">
      <div>
        <p>问题列表</p>
        <strong>{{ summary?.total_issues ?? issues.length }}</strong>
      </div>
      <span>当前页 {{ issues.length }}</span>
    </div>

    <p v-if="loading && !issues.length" class="review-navigation__status" role="status">
      正在加载问题…
    </p>

    <div v-if="error" class="review-navigation__error" role="alert">
      <p>{{ error }}</p>
      <button type="button" data-testid="retry-issues" @click="emit('retry')">
        重试问题列表
      </button>
    </div>

    <p
      v-else-if="!loading && !issues.length"
      class="review-navigation__empty"
      data-testid="empty-issues"
    >
      未发现问题，可以继续阅读文档。
    </p>

    <ol v-else class="issue-list">
      <li v-for="issue in issues" :key="issue.issue_id">
        <button
          type="button"
          class="issue-card"
          :class="{ 'issue-card--active': issue.issue_id === selectedIssueId }"
          :data-issue-id="issue.issue_id"
          :aria-current="issue.issue_id === selectedIssueId ? 'true' : 'false'"
          @click="emit('select', issue.issue_id)"
        >
          <span class="issue-card__meta">
            <span>{{ issue.type }}</span>
            <span>{{ issue.severity }}</span>
          </span>
          <strong>{{ issue.original }}</strong>
          <span>{{ issue.message }}</span>
        </button>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.review-navigation {
  min-width: 0;
  overflow: auto;
  background: #fff;
  border: 1px solid #e2e7f0;
  border-radius: 16px;
}

.review-navigation__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px;
  border-bottom: 1px solid #edf0f5;
}

.review-navigation__heading p {
  margin: 0;
  color: #667085;
  font-size: 0.75rem;
}

.review-navigation__heading strong {
  display: block;
  margin-top: 3px;
  color: #20283a;
  font-size: 1.5rem;
}

.review-navigation__heading > span {
  color: #758096;
  font-size: 0.72rem;
}

.review-navigation__status,
.review-navigation__empty,
.review-navigation__error {
  margin: 16px;
  color: #667085;
  font-size: 0.84rem;
}

.review-navigation__error {
  color: #a53636;
}

.review-navigation__error p {
  margin: 0 0 10px;
}

.review-navigation__error button {
  padding: 7px 10px;
  color: #4256c9;
  font-weight: 700;
  background: #eef0ff;
  border: 0;
  border-radius: 8px;
  cursor: pointer;
}

.issue-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 10px;
  list-style: none;
}

.issue-card {
  display: grid;
  width: 100%;
  gap: 7px;
  padding: 13px;
  color: #596276;
  text-align: left;
  background: #f8f9fc;
  border: 1px solid transparent;
  border-radius: 11px;
  cursor: pointer;
}

.issue-card:hover,
.issue-card:focus-visible {
  border-color: #aeb9f5;
  outline: none;
}

.issue-card--active {
  background: #eef0ff;
  border-color: #7a8bea;
}

.issue-card__meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: #6977c9;
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
}

.issue-card strong {
  overflow: hidden;
  color: #252e42;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.issue-card > span:last-child {
  font-size: 0.78rem;
  line-height: 1.45;
}
</style>
