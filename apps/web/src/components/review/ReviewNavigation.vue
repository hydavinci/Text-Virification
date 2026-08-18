<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'

import type { AnalysisSummaryResponse, Issue } from '../../types/analysis'
import type {
  CheckCategory,
  IssueDecisionState,
  IssueSeverity
} from '../../types/review'
import type { ReviewIssueFilters } from '../../composables/useReviewWorkspace'
import { describeSeverity } from './severity'

const props = defineProps<{
  summary: AnalysisSummaryResponse | null
  issues: Issue[]
  issueStatusById: Record<string, string>
  selectedIssueId: string | null
  loading: boolean
  error: string | null
  filters: ReviewIssueFilters
}>()

const emit = defineEmits<{
  select: [issueId: string]
  retry: []
  filterChange: [filters: ReviewIssueFilters]
}>()

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
      v-if="!loading && !error && !issues.length"
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
          @click="emit('select', issue.issue_id)"
        >
          <span class="issue-card__meta">
            <span>{{ issue.type }}</span>
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

.review-navigation__filters {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 14px 12px;
  border-bottom: 1px solid #edf0f5;
}

.review-navigation__filters label {
  display: grid;
  gap: 5px;
  color: #667085;
  font-size: 0.7rem;
  font-weight: 700;
}

.review-navigation__filters select,
.review-navigation__filters input {
  width: 100%;
  min-width: 0;
  padding: 8px 9px;
  min-height: 44px;
  color: #30394d;
  font-size: 0.78rem;
  background: #f8f9fc;
  border: 1px solid #dfe4ee;
  border-radius: 8px;
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
  min-height: 44px;
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
  min-height: 44px;
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
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
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
  color: #252e42;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.issue-card__status {
  color: #4356c9;
  font-size: 0.72rem;
  font-weight: 800;
}

.issue-card > span:last-child {
  font-size: 0.78rem;
  line-height: 1.45;
}
</style>
