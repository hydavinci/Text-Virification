<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, type Ref } from 'vue'

import BatchActions from '../components/review/BatchActions.vue'
import CheckerFailureNotice from '../components/review/CheckerFailureNotice.vue'
import DocumentViewer from '../components/review/DocumentViewer.vue'
import IssuePanel from '../components/review/IssuePanel.vue'
import ReviewNavigation from '../components/review/ReviewNavigation.vue'
import ReviewToolbar from '../components/review/ReviewToolbar.vue'
import ToolRail from '../components/review/ToolRail.vue'
import WorkspaceSidePanel from '../components/review/WorkspaceSidePanel.vue'
import { useReviewWorkspace } from '../composables/useReviewWorkspace'
import type { FileType } from '../types/review'
import type {
  InspectorTab,
  RailTool,
  SidePanelTool,
  WorkspaceTool
} from '../components/review/workspaceLayout'

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

const MOBILE_BREAKPOINT_QUERY = '(max-width: 1100px)'
const DESKTOP_BREAKPOINT_QUERY = '(min-width: 1280px)'
const supportsMatchMedia =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'

const mobileMediaQuery =
  supportsMatchMedia ? window.matchMedia(MOBILE_BREAKPOINT_QUERY) : null
const desktopMediaQuery =
  supportsMatchMedia ? window.matchMedia(DESKTOP_BREAKPOINT_QUERY) : null

const workspaceRoot = ref<HTMLElement | null>(null)
const isMobile = ref(mobileMediaQuery?.matches ?? false)
const isDesktop = ref(desktopMediaQuery?.matches ?? !isMobile.value)
const activeMobileTab = ref<MobileReviewTab>('document')
const activeRailTool = ref<RailTool>('issues')
const activeSidePanelTool = ref<SidePanelTool>('issues')
const isSidePanelOpen = ref(true)
const activeInspectorTab = ref<InspectorTab>('details')
const tabButtons = new Map<MobileReviewTab, HTMLButtonElement>()

function bindMediaQuery(
  mediaQuery: MediaQueryList | null,
  target: Ref<boolean>
): (() => void) | null {
  if (!mediaQuery) {
    return null
  }

  const handleChange = (event: MediaQueryListEvent): void => {
    target.value = event.matches
  }

  if (typeof mediaQuery.addEventListener === 'function') {
    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }

  mediaQuery.addListener(handleChange)
  return () => mediaQuery.removeListener(handleChange)
}

const cleanupMobileMediaQuery = bindMediaQuery(mobileMediaQuery, isMobile)
const cleanupDesktopMediaQuery = bindMediaQuery(desktopMediaQuery, isDesktop)

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

function activateDesktopTool(tool: WorkspaceTool): void {
  if (tool === 'document') {
    return
  }

  if (tool === 'search') {
    activeRailTool.value = 'search'
    activeInspectorTab.value = 'search'
    return
  }

  if (
    activeRailTool.value === tool &&
    activeSidePanelTool.value === tool &&
    isSidePanelOpen.value
  ) {
    isSidePanelOpen.value = false
    return
  }

  activeRailTool.value = tool
  activeSidePanelTool.value = tool
  isSidePanelOpen.value = true

  if (tool === 'issues') {
    activeInspectorTab.value = 'details'
  }
}

function closeSidePanel(): void {
  isSidePanelOpen.value = false
}

function focusToolbarExport(): void {
  void nextTick(() => {
    workspaceRoot.value
      ?.querySelector<HTMLSelectElement>('select[name="export-type"]')
      ?.focus()
  })
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
  cleanupMobileMediaQuery?.()
  cleanupDesktopMediaQuery?.()
})
</script>

<template>
  <section
    ref="workspaceRoot"
    class="review-workspace"
    aria-label="文档审阅工作台"
    @keydown="onWorkspaceKeydown"
  >
    <ReviewToolbar
      :job-id="jobId"
      :file-type="fileType"
      :bulk-action-pending="bulkActionPending"
      :find-query="findQuery"
      :replace-text="replaceText"
      :find-status="findStatus"
      :can-navigate-matches="canNavigateMatches"
      :can-replace-all-matches="canReplaceAllMatches"
      :find-replace-error="findReplaceError"
      @update-find-query="setFindQuery"
      @update-replace-text="setReplaceText"
      @previous-match="goToPreviousMatch"
      @next-match="goToNextMatch"
      @replace-all="replaceAllMatches"
    />

    <div v-if="!isDesktop" class="review-workspace__supplements">
      <CheckerFailureNotice v-if="!isDesktop" :failures="checkerFailures" />

      <section class="review-workspace__auxiliary-panel" aria-label="批量">
        <BatchActions
          :issue-count="visibleIssueCount"
          :batch-limit="batchLimit"
          :high-risk-security-count="highRiskVisibleIssueCount"
          :busy="bulkActionPending"
          :error="batchDecisionError"
          @accept-visible="decideVisible('accepted')"
          @ignore-visible="decideVisible('ignored')"
        />
      </section>
    </div>

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
          :source-name="sourceName"
          :file-type="fileType"
          :total-issues="summary?.total_issues ?? null"
          :summary-loading="loading.summary"
          :summary-error="errors.summary"
          :blocks="blocks"
          :issues="issues"
          :selected-issue-id="selectedIssueId"
          :selected-block-id="selectedBlockId"
          :next-cursor="blockCursor"
          :loading="loading.document"
          :error="errors.document"
          @select-highlight="selectHighlight"
          @load-next="loadNextBlocks"
          @retry-summary="retrySummary"
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
        <div
          class="review-workspace__inspector-placeholder"
          :data-inspector-tab="activeInspectorTab"
        >
          <IssuePanel
            :issue="selectedIssue"
            :decision-error="decisionError"
            :can-retry-decision="canRetryDecision"
            @decide="decide"
            @retry-decision="retryDecision"
          />
        </div>
      </section>
    </template>

    <div
      v-else-if="isDesktop"
      class="review-workspace__desktop-shell"
      :data-side-panel-open="isSidePanelOpen"
    >
      <ToolRail
        mode="rail"
        :active-tool="activeRailTool"
        :side-panel-open="isSidePanelOpen"
        :export-open="true"
        @activate="activateDesktopTool"
        @toggle-export="focusToolbarExport"
      />

      <WorkspaceSidePanel
        :open="isSidePanelOpen"
        :title="activeSidePanelTool === 'issues' ? '问题' : '批量'"
        @close="closeSidePanel"
      >
        <div
          class="review-workspace__side-panel-content"
          :class="`review-workspace__side-panel-content--${activeSidePanelTool}`"
        >
          <template v-if="activeSidePanelTool === 'issues'">
            <CheckerFailureNotice :failures="checkerFailures" />
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
          </template>

          <BatchActions
            v-else
            :issue-count="visibleIssueCount"
            :batch-limit="batchLimit"
            :high-risk-security-count="highRiskVisibleIssueCount"
            :busy="bulkActionPending"
            :error="batchDecisionError"
            @accept-visible="decideVisible('accepted')"
            @ignore-visible="decideVisible('ignored')"
          />
        </div>
      </WorkspaceSidePanel>

      <DocumentViewer
        :source-name="sourceName"
        :file-type="fileType"
        :total-issues="summary?.total_issues ?? null"
        :summary-loading="loading.summary"
        :summary-error="errors.summary"
        :blocks="blocks"
        :issues="issues"
        :selected-issue-id="selectedIssueId"
        :selected-block-id="selectedBlockId"
        :next-cursor="blockCursor"
        :loading="loading.document"
        :error="errors.document"
        @select-highlight="selectHighlight"
        @load-next="loadNextBlocks"
        @retry-summary="retrySummary"
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
        :source-name="sourceName"
        :file-type="fileType"
        :total-issues="summary?.total_issues ?? null"
        :summary-loading="loading.summary"
        :summary-error="errors.summary"
        :blocks="blocks"
        :issues="issues"
        :selected-issue-id="selectedIssueId"
        :selected-block-id="selectedBlockId"
        :next-cursor="blockCursor"
        :loading="loading.document"
        :error="errors.document"
        @select-highlight="selectHighlight"
        @load-next="loadNextBlocks"
        @retry-summary="retrySummary"
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
  display: flex;
  width: min(100% - 32px, 1560px);
  height: 100%;
  flex-direction: column;
  margin: 0 auto;
  padding: 16px 0;
  overflow: hidden;
}

.review-workspace :deep(button),
.review-workspace :deep(select),
.review-workspace :deep(input[type="search"]),
.review-workspace :deep(textarea),
.review-workspace :deep(a) {
  min-height: 44px;
}

.review-workspace__supplements {
  display: grid;
  gap: 12px;
  margin-top: 14px;
}

.review-workspace__auxiliary-panel,
.review-workspace__columns :deep(.review-navigation),
.review-workspace__mobile-panel--issues :deep(.review-navigation) {
  background: #fff;
  border: 1px solid #e2e7f0;
  border-radius: 16px;
}

.review-workspace__auxiliary-panel {
  padding: 16px;
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

.review-workspace__desktop-shell,
.review-workspace__columns {
  display: grid;
  min-height: 0;
  flex: 1;
  gap: 14px;
  margin-top: 14px;
  grid-template-rows: minmax(0, 1fr);
}

.review-workspace__desktop-shell > *,
.review-workspace__columns > * {
  min-width: 0;
  min-height: 0;
}

.review-workspace__desktop-shell {
  align-items: stretch;
}

.review-workspace__inspector-placeholder {
  min-width: 0;
  min-height: 0;
}

.review-workspace__side-panel-content {
  display: grid;
  gap: 14px;
  min-height: 0;
}

.review-workspace__columns {
  grid-template-columns: minmax(220px, 0.8fr) minmax(480px, 2.3fr) minmax(240px, 0.9fr);
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

@media (min-width: 1280px) {
  .review-workspace__desktop-shell {
    grid-template-columns: 64px 280px minmax(0, 1fr) 360px;
  }

  .review-workspace__desktop-shell[data-side-panel-open='false'] {
    grid-template-columns: 64px minmax(0, 1fr) 360px;
  }
}

@media (max-width: 1100px) {
  .review-workspace {
    width: min(100% - 24px, 100%);
    height: auto;
    padding-top: 18px;
    overflow: visible;
  }
}
</style>
