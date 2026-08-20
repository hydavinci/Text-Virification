<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, type Ref } from 'vue'

import BatchActions from '../components/review/BatchActions.vue'
import CheckerFailureNotice from '../components/review/CheckerFailureNotice.vue'
import ContextInspector from '../components/review/ContextInspector.vue'
import DocumentViewer from '../components/review/DocumentViewer.vue'
import ExportPanel from '../components/review/ExportPanel.vue'
import FindReplace from '../components/review/FindReplace.vue'
import IssuePanel from '../components/review/IssuePanel.vue'
import ReviewNavigation from '../components/review/ReviewNavigation.vue'
import ToolRail from '../components/review/ToolRail.vue'
import WorkspaceSidePanel from '../components/review/WorkspaceSidePanel.vue'
import { useReviewWorkspace } from '../composables/useReviewWorkspace'
import type { FileType } from '../types/review'
import type {
  CompactWorkspaceView,
  InspectorTab,
  RailTool,
  SidePanelTool,
  WorkspaceTool
} from '../components/review/workspaceLayout'

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

const COMPACT_BREAKPOINT_QUERY = '(max-width: 1279px)'
const PHONE_BREAKPOINT_QUERY = '(max-width: 767px)'
const supportsMatchMedia =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'

const compactMediaQuery =
  supportsMatchMedia ? window.matchMedia(COMPACT_BREAKPOINT_QUERY) : null
const phoneMediaQuery =
  supportsMatchMedia ? window.matchMedia(PHONE_BREAKPOINT_QUERY) : null

const workspaceRoot = ref<HTMLElement | null>(null)
const isCompact = ref(compactMediaQuery?.matches ?? false)
const isPhone = ref(phoneMediaQuery?.matches ?? false)
const isDesktop = computed(() => !isCompact.value)
const activeCompactView = ref<CompactWorkspaceView>('document')
const phoneIssueSubview = ref<'list' | 'details'>('list')
const activeRailTool = ref<RailTool>('issues')
const activeSidePanelTool = ref<SidePanelTool>('issues')
const isSidePanelOpen = ref(true)
const isExportOpen = ref(false)
const activeInspectorTab = ref<InspectorTab>('details')
const toolRail = ref<{ focusExportButton(): void } | null>(null)
const lastPhoneIssueTrigger = ref<HTMLElement | null>(null)

function bindMediaQuery(
  mediaQuery: MediaQueryList | null,
  target: Ref<boolean>
): (() => void) | null {
  if (!mediaQuery) {
    return null
  }

  const syncMatches = (matches: boolean): void => {
    target.value = matches
  }

  const handleChange = (event: MediaQueryListEvent): void => {
    syncMatches(event.matches)
  }

  const handleLegacyChange = (
    event: MediaQueryListEvent | MediaQueryList
  ): void => {
    syncMatches(event.matches)
  }

  const cleanup: Array<() => void> = []

  if (typeof mediaQuery.addEventListener === 'function') {
    mediaQuery.addEventListener('change', handleChange)
    cleanup.push(() => mediaQuery.removeEventListener('change', handleChange))
  }

  if (typeof mediaQuery.addListener === 'function') {
    mediaQuery.addListener(handleLegacyChange)
    cleanup.push(() => mediaQuery.removeListener(handleLegacyChange))
  }

  return cleanup.length ? () => cleanup.forEach((callback) => callback()) : null
}

const cleanupCompactMediaQuery = bindMediaQuery(compactMediaQuery, isCompact)
const cleanupPhoneMediaQuery = bindMediaQuery(phoneMediaQuery, isPhone)

function activateCompactView(tool: WorkspaceTool): void {
  activeCompactView.value = tool

  if (tool === 'issues') {
    activeInspectorTab.value = 'details'
    if (isPhone.value) {
      phoneIssueSubview.value = 'list'
    }
    return
  }

  if (tool === 'search') {
    activeInspectorTab.value = 'search'
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

function selectIssueAndShowDetails(
  issueId: string,
  trigger: HTMLElement | null = null
): void {
  selectIssue(issueId)

  if (isCompact.value) {
    activeCompactView.value = 'issues'
    activeInspectorTab.value = 'details'

    if (isPhone.value) {
      lastPhoneIssueTrigger.value = trigger
      phoneIssueSubview.value = 'details'
    }
    return
  }

  activeRailTool.value = 'issues'
  activeInspectorTab.value = 'details'
}

function selectHighlightAndShowDetails(issueId: string): void {
  selectHighlight(issueId)

  if (isCompact.value) {
    if (activeCompactView.value === 'issues') {
      activeInspectorTab.value = 'details'
      if (isPhone.value) {
        phoneIssueSubview.value = 'details'
      }
    }
    return
  }

  activeRailTool.value = 'issues'
  activeInspectorTab.value = 'details'
}

function closeSidePanel(): void {
  isSidePanelOpen.value = false
}

function focusExportTrigger(): void {
  void nextTick(() => {
    toolRail.value?.focusExportButton()
  })
}

function closeExport(): void {
  if (!isExportOpen.value) {
    return
  }

  isExportOpen.value = false
  focusExportTrigger()
}

function toggleExport(): void {
  if (isExportOpen.value) {
    closeExport()
    return
  }

  isExportOpen.value = true
}

function returnToPhoneIssueList(): void {
  phoneIssueSubview.value = 'list'
  void nextTick(() => lastPhoneIssueTrigger.value?.focus())
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
  cleanupCompactMediaQuery?.()
  cleanupPhoneMediaQuery?.()
})
</script>

<template>
  <section
    ref="workspaceRoot"
    class="review-workspace"
    aria-label="文档审阅工作台"
    @keydown="onWorkspaceKeydown"
  >
    <div v-if="isCompact" class="review-workspace__compact-shell">
      <div class="review-workspace__compact-main">
        <section
          v-show="activeCompactView === 'document'"
          class="review-workspace__compact-panel review-workspace__compact-panel--document"
          aria-label="文档"
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
            @select-highlight="selectHighlightAndShowDetails"
            @load-next="loadNextBlocks"
            @retry-summary="retrySummary"
            @retry="retryDocument"
          />
        </section>

        <section
          v-show="activeCompactView === 'issues'"
          class="review-workspace__compact-panel review-workspace__compact-panel--issues"
          aria-label="问题工作台"
        >
          <CheckerFailureNotice :failures="checkerFailures" />

          <div v-if="isPhone" class="review-workspace__phone-issues">
            <div
              v-show="phoneIssueSubview === 'list'"
              class="review-workspace__compact-surface"
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
                @select="selectIssueAndShowDetails"
                @retry="retryIssues"
                @load-next="loadNextIssues"
                @filter-change="setFilters"
              />
            </div>

            <section
              v-show="phoneIssueSubview === 'details'"
              data-testid="phone-issue-details"
              class="review-workspace__compact-surface review-workspace__compact-surface--padded review-workspace__phone-issue-details"
              aria-label="问题详情"
            >
              <button
                type="button"
                class="review-workspace__phone-back"
                aria-label="返回问题列表"
                @click="returnToPhoneIssueList"
              >
                返回问题列表
              </button>
              <IssuePanel
                :issue="selectedIssue"
                :decision-error="decisionError"
                :can-retry-decision="canRetryDecision"
                @decide="decide"
                @retry-decision="retryDecision"
              />
            </section>
          </div>

          <div v-else class="review-workspace__compact-issue-grid">
            <div class="review-workspace__compact-surface">
              <ReviewNavigation
                :summary="summary"
                :issues="issues"
                :issue-status-by-id="issueStatusById"
                :selected-issue-id="selectedIssueId"
                :loading="loading.issues"
                :error="errors.issues"
                :filters="filters"
                :next-cursor="issueCursor"
                @select="selectIssueAndShowDetails"
                @retry="retryIssues"
                @load-next="loadNextIssues"
                @filter-change="setFilters"
              />
            </div>

            <section
              class="review-workspace__compact-surface review-workspace__compact-surface--padded"
              aria-label="问题详情"
            >
              <IssuePanel
                :issue="selectedIssue"
                :decision-error="decisionError"
                :can-retry-decision="canRetryDecision"
                @decide="decide"
                @retry-decision="retryDecision"
              />
            </section>
          </div>
        </section>

        <section
          v-show="activeCompactView === 'search'"
          class="review-workspace__compact-panel"
          aria-label="查找"
        >
          <div class="review-workspace__compact-surface review-workspace__compact-surface--padded">
            <FindReplace
              :query="findQuery"
              :replacement="replaceText"
              :status="findStatus"
              :can-navigate="canNavigateMatches"
              :can-replace-all="canReplaceAllMatches"
              :busy="bulkActionPending"
              :error="findReplaceError"
              @update-query="setFindQuery"
              @update-replacement="setReplaceText"
              @previous-match="goToPreviousMatch"
              @next-match="goToNextMatch"
              @replace-all="replaceAllMatches"
            />
          </div>
        </section>

        <section
          v-show="activeCompactView === 'batch'"
          class="review-workspace__compact-panel"
          aria-label="批量"
        >
          <div class="review-workspace__compact-surface review-workspace__compact-surface--padded">
            <BatchActions
              :issue-count="visibleIssueCount"
              :batch-limit="batchLimit"
              :high-risk-security-count="highRiskVisibleIssueCount"
              :busy="bulkActionPending"
              :error="batchDecisionError"
              @accept-visible="decideVisible('accepted')"
              @ignore-visible="decideVisible('ignored')"
            />
          </div>
        </section>
      </div>

      <div class="review-workspace__compact-footer">
        <div class="review-workspace__compact-rail-stack">
          <ToolRail
            ref="toolRail"
            mode="bottom"
            :active-tool="activeCompactView"
            :side-panel-open="false"
            :export-open="isExportOpen"
            @activate="activateCompactView"
            @toggle-export="toggleExport"
          />
          <ExportPanel
            class="review-workspace__compact-export-panel"
            :job-id="jobId"
            :file-type="fileType"
            :open="isExportOpen"
            @close="closeExport"
          />
        </div>
      </div>
    </div>

    <div
      v-else
      class="review-workspace__desktop-shell"
      :data-side-panel-open="isSidePanelOpen"
    >
      <div class="review-workspace__rail-stack">
        <ToolRail
          ref="toolRail"
          mode="rail"
          :active-tool="activeRailTool"
          :side-panel-open="isSidePanelOpen"
          :export-open="isExportOpen"
          @activate="activateDesktopTool"
          @toggle-export="toggleExport"
        />
        <ExportPanel
          :job-id="jobId"
          :file-type="fileType"
          :open="isExportOpen"
          @close="closeExport"
        />
      </div>

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
              @select="selectIssueAndShowDetails"
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
        @select-highlight="selectHighlightAndShowDetails"
        @load-next="loadNextBlocks"
        @retry-summary="retrySummary"
        @retry="retryDocument"
      />

      <ContextInspector v-model:active-tab="activeInspectorTab">
        <template #details>
          <IssuePanel
            :issue="selectedIssue"
            :decision-error="decisionError"
            :can-retry-decision="canRetryDecision"
            @decide="decide"
            @retry-decision="retryDecision"
          />
        </template>
        <template #search>
          <FindReplace
            :query="findQuery"
            :replacement="replaceText"
            :status="findStatus"
            :can-navigate="canNavigateMatches"
            :can-replace-all="canReplaceAllMatches"
            :busy="bulkActionPending"
            :error="findReplaceError"
            @update-query="setFindQuery"
            @update-replacement="setReplaceText"
            @previous-match="goToPreviousMatch"
            @next-match="goToNextMatch"
            @replace-all="replaceAllMatches"
          />
        </template>
      </ContextInspector>
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
  --review-accent: #4f5fd5;
  --review-accent-soft: #eef0ff;
  --review-surface: #ffffff;
  --review-canvas: #f3f5f8;
  --review-border: #dfe3ea;
  --review-text: #202939;
  --review-text-muted: #667085;
  --review-danger: #a53636;
  --review-space-1: 4px;
  --review-space-2: 8px;
  --review-space-3: 12px;
  --review-space-4: 16px;
  --review-panel-radius: 12px;
  position: relative;
  display: flex;
  width: min(100% - 32px, 1560px);
  height: 100%;
  flex-direction: column;
  margin: 0 auto;
  padding: var(--review-space-4) 0;
  color: var(--review-text);
  overflow: hidden;
}

.review-workspace :deep(button),
.review-workspace :deep(select),
.review-workspace :deep(input[type="search"]),
.review-workspace :deep(textarea),
.review-workspace :deep(a) {
  min-height: 44px;
}

.review-workspace__compact-shell {
  display: grid;
  min-height: 0;
  flex: 1;
  gap: var(--review-space-3);
  grid-template-rows: minmax(0, 1fr) auto;
}

.review-workspace__compact-main {
  min-height: 0;
  overflow: auto;
}

.review-workspace__compact-panel {
  display: grid;
  min-height: 0;
  gap: var(--review-space-3);
}

.review-workspace__compact-panel--document {
  height: 100%;
}

.review-workspace__compact-panel--issues {
  align-content: start;
}

.review-workspace__compact-surface {
  min-height: 0;
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) + var(--review-space-1));
  overflow: hidden;
}

.review-workspace__compact-surface--padded {
  padding: var(--review-space-4);
}

.review-workspace__compact-issue-grid,
.review-workspace__phone-issues,
.review-workspace__phone-issue-details {
  display: grid;
  gap: var(--review-space-3);
  min-height: 0;
}

.review-workspace__compact-footer {
  position: sticky;
  bottom: 0;
  z-index: 4;
  padding-bottom: env(safe-area-inset-bottom, 0);
}

.review-workspace__compact-rail-stack {
  position: relative;
  padding-top: var(--review-space-2);
}

.review-workspace__compact-rail-stack :deep(.tool-rail) {
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) + 6px);
  box-shadow: 0 14px 32px rgba(22, 31, 52, 0.12);
  backdrop-filter: blur(8px);
}

.review-workspace__compact-export-panel :deep(.export-panel) {
  left: 12px;
  right: 12px;
  top: auto;
  bottom: calc(100% + 12px);
  width: auto;
  max-height: min(420px, calc(100dvh - 140px));
}

.review-workspace__phone-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  justify-self: start;
  min-width: 44px;
  padding: 0 var(--review-space-4);
  color: var(--review-accent);
  font-weight: 700;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border: 1px solid var(--review-border);
  border-radius: var(--review-panel-radius);
  cursor: pointer;
}

.review-workspace__phone-back:focus-visible {
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
}

.review-workspace__desktop-shell,
.review-workspace__columns {
  display: grid;
  min-height: 0;
  flex: 1;
  gap: var(--review-space-3);
  margin-top: var(--review-space-3);
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

.review-workspace__rail-stack {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: visible;
}

.review-workspace__side-panel-content {
  display: grid;
  gap: var(--review-space-3);
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

@media (max-width: 1279px) {
  .review-workspace {
    width: min(100% - 24px, 100%);
    min-height: calc(100dvh - 24px);
    height: auto;
    padding-top: 18px;
    overflow: visible;
  }
}
</style>
