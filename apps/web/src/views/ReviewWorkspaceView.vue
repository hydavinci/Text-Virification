<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'

import DocumentViewer from '../components/review/DocumentViewer.vue'
import IssuePanel from '../components/review/IssuePanel.vue'
import ReviewNavigation from '../components/review/ReviewNavigation.vue'
import ReviewToolbar from '../components/review/ReviewToolbar.vue'
import { useReviewWorkspace } from '../composables/useReviewWorkspace'
import type { FileType } from '../types/review'

type MobileReviewTab = 'document' | 'issues'

const props = defineProps<{
  jobId: string
  sourceName: string
  fileType: FileType
}>()

const {
  summary,
  filters,
  blocks,
  issues,
  issueStatusById,
  selectedIssueId,
  selectedIssue,
  selectedBlockId,
  blockCursor,
  issueCursor,
  loading,
  errors,
  checkerFailures,
  decisionError,
  canRetryDecision,
  decisionAnnouncement,
  batchLimit,
  visibleIssueCount,
  highRiskVisibleIssueCount,
  batchDecisionError,
  bulkActionPending,
  findQuery,
  replaceText,
  findStatus,
  canNavigateMatches,
  canReplaceAllMatches,
  findReplaceError,
  selectIssue,
  selectHighlight,
  setFilters,
  decide,
  decideVisible,
  retryDecision,
  loadNextBlocks,
  loadNextIssues,
  setFindQuery,
  setReplaceText,
  goToPreviousMatch,
  goToNextMatch,
  replaceAllMatches,
  retrySummary,
  retryDocument,
  retryIssues
} = useReviewWorkspace(props.jobId)

const processedIssueCount = computed(() => {
  const decisions = summary.value?.by_decision
  return decisions
    ? decisions.accepted + decisions.ignored + decisions.custom
    : 0
})
const unprocessedIssueCount = computed(
  () => summary.value?.by_decision.unreviewed ?? 0
)
const highRiskIssueCount = computed(
  () => summary.value?.by_severity.error ?? 0
)

const MOBILE_BREAKPOINT_QUERY = '(max-width: 900px)'
const mediaQuery =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia(MOBILE_BREAKPOINT_QUERY)
    : null

const isMobile = ref(mediaQuery?.matches ?? false)
const activeMobileTab = ref<MobileReviewTab>('document')
const tabButtons = new Map<MobileReviewTab, HTMLButtonElement>()

function handleViewportChange(event: MediaQueryListEvent): void {
  isMobile.value = event.matches
}

if (mediaQuery) {
  if (typeof mediaQuery.addEventListener === 'function') {
    mediaQuery.addEventListener('change', handleViewportChange)
  } else {
    mediaQuery.addListener(handleViewportChange)
  }
}

function registerTabButton(tab: MobileReviewTab, candidate: unknown): void {
  if (candidate instanceof HTMLButtonElement) {
    tabButtons.set(tab, candidate)
    return
  }

  tabButtons.delete(tab)
}

function activateMobileTab(tab: MobileReviewTab, preserveFocus = false): void {
  activeMobileTab.value = tab

  if (preserveFocus) {
    void nextTick(() => {
      tabButtons.get(tab)?.focus()
    })
  }
}

function onTabKeydown(event: KeyboardEvent): void {
  const orderedTabs: MobileReviewTab[] = ['document', 'issues']
  const currentIndex = orderedTabs.indexOf(activeMobileTab.value)

  if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
    event.preventDefault()
    const delta = event.key === 'ArrowRight' ? 1 : -1
    const nextIndex = (currentIndex + delta + orderedTabs.length) % orderedTabs.length
    activateMobileTab(orderedTabs[nextIndex] ?? 'document', true)
    return
  }

  if (event.key === 'Home') {
    event.preventDefault()
    activateMobileTab('document', true)
    return
  }

  if (event.key === 'End') {
    event.preventDefault()
    activateMobileTab('issues', true)
  }
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false
  }

  return (
    target.isContentEditable ||
    target.closest('input, textarea, select, [contenteditable="true"]') !== null
  )
}

function onWorkspaceKeydown(event: KeyboardEvent): void {
  if (
    event.defaultPrevented ||
    event.altKey ||
    event.ctrlKey ||
    event.metaKey ||
    isEditableTarget(event.target) ||
    issues.value.length < 2
  ) {
    return
  }

  const normalizedKey = event.key.toLowerCase()
  if (normalizedKey !== 'j' && normalizedKey !== 'k') {
    return
  }

  const selectedIndex = selectedIssueId.value
    ? issues.value.findIndex((issue) => issue.issue_id === selectedIssueId.value)
    : 0
  const currentIndex = selectedIndex === -1 ? 0 : selectedIndex
  const nextIndex =
    normalizedKey === 'j'
      ? Math.min(currentIndex + 1, issues.value.length - 1)
      : Math.max(currentIndex - 1, 0)

  if (nextIndex === currentIndex) {
    return
  }

  event.preventDefault()
  const nextIssue = issues.value[nextIndex]
  if (nextIssue) {
    selectIssue(nextIssue.issue_id)
  }
}

onBeforeUnmount(() => {
  if (!mediaQuery) {
    return
  }

  if (typeof mediaQuery.removeEventListener === 'function') {
    mediaQuery.removeEventListener('change', handleViewportChange)
  } else {
    mediaQuery.removeListener(handleViewportChange)
  }
})
</script>

<template>
  <section class="review-workspace" aria-label="文档审阅工作台" @keydown="onWorkspaceKeydown">
    <ReviewToolbar
      :job-id="jobId"
      :source-name="sourceName"
      :file-type="fileType"
      :summary="summary"
      :loading="loading.summary"
      :error="errors.summary"
      :checker-failures="checkerFailures"
      :batch-limit="batchLimit"
      :visible-issue-count="visibleIssueCount"
      :high-risk-visible-issue-count="highRiskVisibleIssueCount"
      :batch-decision-error="batchDecisionError"
      :bulk-action-pending="bulkActionPending"
      :find-query="findQuery"
      :replace-text="replaceText"
      :find-status="findStatus"
      :can-navigate-matches="canNavigateMatches"
      :can-replace-all-matches="canReplaceAllMatches"
      :find-replace-error="findReplaceError"
      @retry="retrySummary"
      @accept-visible="decideVisible('accepted')"
      @ignore-visible="decideVisible('ignored')"
      @update-find-query="setFindQuery"
      @update-replace-text="setReplaceText"
      @previous-match="goToPreviousMatch"
      @next-match="goToNextMatch"
      @replace-all="replaceAllMatches"
    />

    <template v-if="isMobile">
      <div class="review-workspace__tabs" role="tablist" aria-label="工作台视图" @keydown="onTabKeydown">
        <button
          :ref="(element) => registerTabButton('document', element)"
          type="button"
          role="tab"
          class="review-workspace__tab"
          :class="{ 'review-workspace__tab--active': activeMobileTab === 'document' }"
          :aria-selected="activeMobileTab === 'document'"
          aria-controls="review-document-panel"
          :tabindex="activeMobileTab === 'document' ? 0 : -1"
          @click="activateMobileTab('document', true)"
        >
          文档
        </button>
        <button
          :ref="(element) => registerTabButton('issues', element)"
          type="button"
          role="tab"
          class="review-workspace__tab"
          :class="{ 'review-workspace__tab--active': activeMobileTab === 'issues' }"
          :aria-selected="activeMobileTab === 'issues'"
          aria-controls="review-issues-panel"
          :tabindex="activeMobileTab === 'issues' ? 0 : -1"
          @click="activateMobileTab('issues', true)"
        >
          问题
        </button>
      </div>

      <section
        id="review-document-panel"
        class="review-workspace__mobile-panel"
        role="tabpanel"
        aria-label="文档"
        :aria-hidden="activeMobileTab !== 'document'"
        v-show="activeMobileTab === 'document'"
      >
        <DocumentViewer
          :blocks="blocks"
          :issues="issues"
          :selected-issue-id="selectedIssueId"
          :selected-block-id="selectedBlockId"
          :next-cursor="blockCursor"
          :loading="loading.document"
          :error="errors.document"
          @select-highlight="selectHighlight"
          @load-next="loadNextBlocks"
          @retry="retryDocument"
        />
      </section>

      <section
        id="review-issues-panel"
        class="review-workspace__mobile-panel review-workspace__mobile-panel--issues"
        role="tabpanel"
        aria-label="问题"
        :aria-hidden="activeMobileTab !== 'issues'"
        v-show="activeMobileTab === 'issues'"
      >
        <ReviewNavigation
          :summary="summary"
          :issues="issues"
          :issue-status-by-id="issueStatusById"
          :selected-issue-id="selectedIssueId"
          :loading="loading.issues"
          :error="errors.issues"
          :filters="filters"
          :next-cursor="issueCursor"
          @select="selectIssue"
          @retry="retryIssues"
          @load-next="loadNextIssues"
          @filter-change="setFilters"
        />
        <IssuePanel
          :issue="selectedIssue"
          :decision-error="decisionError"
          :can-retry-decision="canRetryDecision"
          @decide="decide"
          @retry-decision="retryDecision"
        />
      </section>
    </template>

    <div v-else class="review-workspace__columns">
      <ReviewNavigation
        :summary="summary"
        :issues="issues"
        :issue-status-by-id="issueStatusById"
        :selected-issue-id="selectedIssueId"
        :loading="loading.issues"
        :error="errors.issues"
        :filters="filters"
        :next-cursor="issueCursor"
        @select="selectIssue"
        @retry="retryIssues"
        @load-next="loadNextIssues"
        @filter-change="setFilters"
      />
      <DocumentViewer
        :blocks="blocks"
        :issues="issues"
        :selected-issue-id="selectedIssueId"
        :selected-block-id="selectedBlockId"
        :next-cursor="blockCursor"
        :loading="loading.document"
        :error="errors.document"
        @select-highlight="selectHighlight"
        @load-next="loadNextBlocks"
        @retry="retryDocument"
      />
      <IssuePanel
        :issue="selectedIssue"
        :decision-error="decisionError"
        :can-retry-decision="canRetryDecision"
        @decide="decide"
        @retry-decision="retryDecision"
      />
    </div>
    <footer v-if="summary" class="review-workspace__statistics" aria-label="审阅统计">
      <dl>
        <div data-review-counter="processed">
          <dt>已处理</dt>
          <dd>{{ processedIssueCount }}</dd>
        </div>
        <div data-review-counter="unprocessed">
          <dt>未处理</dt>
          <dd>{{ unprocessedIssueCount }}</dd>
        </div>
        <div data-review-counter="high-risk">
          <dt>高风险</dt>
          <dd>{{ highRiskIssueCount }}</dd>
        </div>
      </dl>
    </footer>
    <p
      class="review-workspace__announcement"
      data-testid="decision-announcement"
      aria-live="polite"
    >
      {{ decisionAnnouncement }}
    </p>
  </section>
</template>

<style scoped>
.review-workspace {
  width: min(100% - 32px, 1560px);
  margin: 0 auto;
  padding: 24px 0;
}

.review-workspace :deep(button),
.review-workspace :deep(select),
.review-workspace :deep(input[type="search"]),
.review-workspace :deep(textarea),
.review-workspace :deep(a) {
  min-height: 44px;
}

.review-workspace__tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.review-workspace__tab {
  padding: 0 16px;
  color: #4256c9;
  font-weight: 700;
  background: #eef0ff;
  border: 1px solid #d4dcff;
  border-radius: 12px;
  cursor: pointer;
}

.review-workspace__tab--active {
  color: #fff;
  background: linear-gradient(135deg, #5c75f7, #7958d9);
  border-color: transparent;
}

.review-workspace__tab[role="tab"]:focus-visible {
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
}

.review-workspace__mobile-panel {
  margin-top: 14px;
}

.review-workspace__mobile-panel--issues {
  display: grid;
  gap: 14px;
}

.review-workspace__columns {
  display: grid;
  min-height: calc(100vh - 164px);
  grid-template-columns: minmax(220px, 0.8fr) minmax(480px, 2.3fr) minmax(240px, 0.9fr);
  gap: 14px;
  margin-top: 14px;
}

.review-workspace__statistics {
  margin-top: 14px;
  padding: 14px 18px;
  background: #fff;
  border: 1px solid #e2e7f0;
  border-radius: 16px;
}

.review-workspace__statistics dl {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 0;
}

.review-workspace__statistics dl > div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 12px;
  color: #596276;
  background: #f8f9fc;
  border-radius: 10px;
}

.review-workspace__statistics dt,
.review-workspace__statistics dd {
  margin: 0;
}

.review-workspace__statistics dd {
  color: #252e42;
  font-size: 1.15rem;
  font-weight: 800;
}

.review-workspace__announcement {
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

@media (max-width: 900px) {
  .review-workspace {
    width: min(100% - 24px, 100%);
    padding-top: 18px;
  }

  .review-workspace__statistics dl {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
