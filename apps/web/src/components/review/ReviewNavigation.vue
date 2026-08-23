<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

import type { AnalysisSummaryResponse, Issue } from '../../types/analysis'
import type {
  CheckCategory,
  IssueDecisionState,
  IssueSeverity
} from '../../types/review'
import { CHECK_CATEGORY_VALUES } from '../../types/review'
import type { ReviewIssueFilters } from '../../composables/useReviewWorkspace'
import {
  categoryLabel,
  decisionStateLabel,
  issueTypeLabel
} from './presentation'
import { describeSeverity } from './severity'

const props = defineProps<{
  summary: AnalysisSummaryResponse | null
  issues: Issue[]
  issueStatusById: Record<string, string>
  selectedIssueId: string | null
  loading: boolean
  error: string | null
  filters: ReviewIssueFilters
  nextCursor: string | null
}>()

const emit = defineEmits<{
  select: [issueId: string, trigger: HTMLElement | null]
  retry: []
  loadNext: []
  filterChange: [filters: ReviewIssueFilters]
}>()

const categoryOrder = CHECK_CATEGORY_VALUES
const decisionOrder: IssueDecisionState[] = [
  'unreviewed',
  'accepted',
  'ignored'
]
const category = ref<CheckCategory | ''>(props.filters.category ?? '')
const severity = ref<IssueSeverity | ''>(props.filters.severity ?? '')
const decision = ref<IssueDecisionState | ''>(props.filters.decision ?? '')
const searchInput = ref(props.filters.search ?? '')
const appliedSearch = ref(props.filters.search ?? '')
let searchTimer: ReturnType<typeof setTimeout> | null = null

function currentFilters(search = appliedSearch.value): ReviewIssueFilters {
  const filters: ReviewIssueFilters = {}
  if (category.value) {
    filters.category = category.value
  }
  if (severity.value) {
    filters.severity = severity.value
  }
  if (decision.value) {
    filters.decision = decision.value
  }
  if (search) {
    filters.search = search
  }
  return filters
}

function applyCategoricalFilters(): void {
  emit('filterChange', currentFilters())
}

function scheduleSearch(): void {
  if (searchTimer) {
    clearTimeout(searchTimer)
  }

  searchTimer = setTimeout(() => {
    searchTimer = null
    appliedSearch.value = searchInput.value
    emit('filterChange', currentFilters(searchInput.value))
  }, 250)
}

watch(
  () => props.filters,
  (filters) => {
    category.value = filters.category ?? ''
    severity.value = filters.severity ?? ''
    decision.value = filters.decision ?? ''
    appliedSearch.value = filters.search ?? ''
    if (!searchTimer) {
      searchInput.value = appliedSearch.value
    }
  }
)

onBeforeUnmount(() => {
  if (searchTimer) {
    clearTimeout(searchTimer)
  }
})

function severityLabel(severityLevel: IssueSeverity): string {
  const presentation = describeSeverity(severityLevel)
  return `${presentation.icon} ${presentation.text}`
}

function selectIssue(issueId: string, event: MouseEvent): void {
  emit(
    'select',
    issueId,
    event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  )
}
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

    <section
      v-if="summary"
      class="review-navigation__overview"
      aria-labelledby="review-overview-heading"
    >
      <h2 id="review-overview-heading">问题总览</h2>
      <div class="review-navigation__overview-group">
        <h3>类别</h3>
        <dl aria-label="问题类别统计">
          <div
            v-for="categoryId in categoryOrder"
            :key="categoryId"
            :data-summary-category="categoryId"
          >
            <dt>{{ categoryLabel(categoryId) }}</dt>
            <dd>{{ summary.by_category[categoryId] }}</dd>
          </div>
        </dl>
      </div>
      <div class="review-navigation__overview-group">
        <h3>处理状态</h3>
        <dl aria-label="问题处理状态统计">
          <div
            v-for="decisionId in decisionOrder"
            :key="decisionId"
            :data-summary-decision="decisionId"
          >
            <dt>{{ decisionStateLabel(decisionId) }}</dt>
            <dd>{{ summary.by_decision[decisionId] }}</dd>
          </div>
        </dl>
      </div>
    </section>

    <div class="review-navigation__filters">
      <label>
        <span>类别</span>
        <select
          v-model="category"
          aria-label="问题类别"
          @change="applyCategoricalFilters"
        >
          <option value="">全部类别</option>
          <option value="character">文字</option>
          <option value="vocabulary">词汇</option>
          <option value="sentence">句子</option>
          <option value="format">格式</option>
          <option value="discourse">篇章</option>
          <option value="security">安全</option>
        </select>
      </label>
      <label>
        <span>严重程度</span>
        <select
          v-model="severity"
          aria-label="问题严重程度"
          @change="applyCategoricalFilters"
        >
          <option value="">全部程度</option>
          <option value="error">错误</option>
          <option value="warning">警告</option>
          <option value="info">提示</option>
        </select>
      </label>
      <label>
        <span>处理状态</span>
        <select
          v-model="decision"
          aria-label="问题处理状态"
          @change="applyCategoricalFilters"
        >
          <option value="">全部状态</option>
          <option value="unreviewed">未处理</option>
          <option value="accepted">已接受</option>
          <option value="ignored">已忽略</option>
          <option value="custom">已自定义</option>
        </select>
      </label>
      <label class="review-navigation__search">
        <span>关键词</span>
        <input
          v-model="searchInput"
          type="search"
          aria-label="搜索问题"
          placeholder="搜索原文或说明"
          @input="scheduleSearch"
        />
      </label>
    </div>

    <p
      v-if="loading && !issues.length && !nextCursor"
      class="review-navigation__status"
      role="status"
    >
      正在加载问题…
    </p>

    <div v-if="error" class="review-navigation__error" role="alert">
      <p>{{ error }}</p>
      <button type="button" data-testid="retry-issues" @click="emit('retry')">
        重试问题列表
      </button>
    </div>

    <p
      v-if="!loading && !error && !issues.length && !nextCursor"
      class="review-navigation__empty"
      data-testid="empty-issues"
    >
      未发现问题，可以继续阅读文档。
    </p>

    <ol v-if="issues.length" class="issue-list">
      <li v-for="issue in issues" :key="issue.issue_id">
        <button
          type="button"
          class="issue-card"
          :class="{ 'issue-card--active': issue.issue_id === selectedIssueId }"
          :data-issue-id="issue.issue_id"
          :aria-current="issue.issue_id === selectedIssueId ? 'true' : 'false'"
          @click="selectIssue(issue.issue_id, $event)"
        >
          <span class="issue-card__meta">
            <span class="issue-card__type">{{ issueTypeLabel(issue.type) }}</span>
            <span
              class="issue-card__severity"
              :class="`issue-card__severity--${issue.severity}`"
            >
              {{ severityLabel(issue.severity) }}
            </span>
          </span>
          <strong>{{ issue.original }}</strong>
          <span class="issue-card__status">{{ issueStatusById[issue.issue_id] ?? '未处理' }}</span>
          <span>{{ issue.message }}</span>
        </button>
      </li>
    </ol>

    <div v-if="issues.length || nextCursor" class="review-navigation__pagination">
      <p
        v-if="loading"
        class="review-navigation__status"
        data-testid="issue-pagination-status"
        role="status"
      >
        正在加载更多问题…
      </p>
      <button
        v-else-if="nextCursor && !error"
        type="button"
        data-testid="load-more-issues"
        aria-label="加载更多问题"
        @click="emit('loadNext')"
      >
        加载更多问题
      </button>
      <p
        v-else-if="!error"
        class="review-navigation__status"
        data-testid="issue-pagination-status"
        role="status"
      >
        已加载全部问题
      </p>
    </div>
  </nav>
</template>

<style scoped>
.review-navigation {
  min-width: 0;
  min-height: 0;
  overflow: auto;
}

.review-navigation__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: calc(var(--review-space-4) + 2px);
  border-bottom: 1px solid var(--review-border);
}

.review-navigation__heading p {
  margin: 0;
  color: var(--review-text-muted);
  font-size: 0.75rem;
}

.review-navigation__heading strong {
  display: block;
  margin-top: 3px;
  color: var(--review-text);
  font-size: 1.5rem;
}

.review-navigation__heading > span {
  color: var(--review-text-muted);
  font-size: 0.72rem;
  white-space: nowrap;
}

.review-navigation__filters {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: calc(var(--review-space-2) + 2px);
  padding: calc(var(--review-space-3) + 2px) var(--review-space-3);
  border-bottom: 1px solid var(--review-border);
}

.review-navigation__overview {
  display: grid;
  gap: var(--review-space-3);
  padding: calc(var(--review-space-3) + 2px) var(--review-space-3);
  border-bottom: 1px solid var(--review-border);
}

.review-navigation__overview h2,
.review-navigation__overview h3 {
  margin: 0;
  color: var(--review-text);
}

.review-navigation__overview h2 {
  font-size: 0.86rem;
}

.review-navigation__overview h3 {
  font-size: 0.72rem;
}

.review-navigation__overview-group {
  display: grid;
  gap: calc(var(--review-space-2) - 1px);
}

.review-navigation__overview dl {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  margin: 0;
}

.review-navigation__overview dl > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--review-space-2);
  padding: 7px var(--review-space-2);
  color: var(--review-text-muted);
  font-size: 0.72rem;
  background: var(--review-surface);
  border-radius: calc(var(--review-panel-radius) - 4px);
}

.review-navigation__overview dt,
.review-navigation__overview dd {
  margin: 0;
}

.review-navigation__overview dd {
  color: var(--review-text);
  font-weight: 800;
}

.review-navigation__filters label {
  display: grid;
  gap: 5px;
  color: var(--review-text-muted);
  font-size: 0.7rem;
  font-weight: 700;
}

.review-navigation__filters select,
.review-navigation__filters input {
  width: 100%;
  min-width: 0;
  padding: 8px 9px;
  min-height: 44px;
  color: var(--review-text);
  font-size: 0.78rem;
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) - 4px);
}

.review-navigation__filters select:focus-visible,
.review-navigation__filters input:focus-visible {
  border-color: #6579e8;
  outline: 2px solid rgba(101, 121, 232, 0.22);
}

.review-navigation__search {
  grid-column: 1 / -1;
}

.review-navigation__status,
.review-navigation__empty,
.review-navigation__error {
  margin: var(--review-space-4);
  color: var(--review-text-muted);
  font-size: 0.84rem;
}

.review-navigation__error {
  color: var(--review-danger);
}

.review-navigation__error p {
  margin: 0 0 10px;
}

.review-navigation__error button {
  min-height: 44px;
  padding: 7px 10px;
  color: var(--review-accent);
  font-weight: 700;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border: 0;
  border-radius: calc(var(--review-panel-radius) - 4px);
  cursor: pointer;
}

.review-navigation__pagination {
  display: grid;
  padding: var(--review-space-1) calc(var(--review-space-2) + 2px)
    calc(var(--review-space-3) + 2px);
}

.review-navigation__pagination .review-navigation__status {
  margin: 6px;
  text-align: center;
}

.review-navigation__pagination button {
  min-height: 44px;
  padding: 8px var(--review-space-3);
  color: var(--review-accent);
  font-weight: 800;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) - 2px);
  cursor: pointer;
}

.review-navigation__pagination button:focus-visible {
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
}

.issue-list {
  display: grid;
  gap: var(--review-space-2);
  margin: 0;
  padding: calc(var(--review-space-2) + 2px);
  list-style: none;
}

.issue-card {
  display: grid;
  width: 100%;
  min-height: 44px;
  gap: calc(var(--review-space-2) - 1px);
  padding: calc(var(--review-space-3) + 1px);
  color: var(--review-text-muted);
  text-align: left;
  background: var(--review-surface);
  border: 1px solid transparent;
  border-radius: calc(var(--review-panel-radius) - 1px);
  cursor: pointer;
}

.issue-card:hover,
.issue-card:focus-visible {
  border-color: #aeb9f5;
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
}

.issue-card--active {
  background: var(--review-accent-soft);
  border-color: var(--review-accent);
}

.issue-card__meta {
  display: flex;
  justify-content: space-between;
  gap: var(--review-space-2);
  color: var(--review-accent);
  font-size: 0.68rem;
  font-weight: 800;
  text-transform: uppercase;
}

.issue-card__severity {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.issue-card__severity--error {
  color: #b42318;
}

.issue-card__severity--warning {
  color: #b54708;
}

.issue-card__severity--info {
  color: #155eef;
}

.issue-card strong {
  overflow: hidden;
  color: var(--review-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.issue-card__status {
  color: var(--review-accent);
  font-size: 0.72rem;
  font-weight: 800;
  white-space: nowrap;
}

.issue-card > span:last-child {
  font-size: 0.78rem;
  line-height: 1.45;
}
</style>
