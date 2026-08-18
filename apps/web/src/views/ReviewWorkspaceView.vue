<script setup lang="ts">
import DocumentViewer from '../components/review/DocumentViewer.vue'
import IssuePanel from '../components/review/IssuePanel.vue'
import ReviewNavigation from '../components/review/ReviewNavigation.vue'
import ReviewToolbar from '../components/review/ReviewToolbar.vue'
import { useReviewWorkspace } from '../composables/useReviewWorkspace'
import type { FileType } from '../types/review'

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
  setFindQuery,
  setReplaceText,
  goToPreviousMatch,
  goToNextMatch,
  replaceAllMatches,
  retrySummary,
  retryDocument,
  retryIssues
} = useReviewWorkspace(props.jobId)
</script>

<template>
  <section class="review-workspace" aria-label="文档审阅工作台">
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

    <div class="review-workspace__columns">
      <ReviewNavigation
        :summary="summary"
        :issues="issues"
        :issue-status-by-id="issueStatusById"
        :selected-issue-id="selectedIssueId"
        :loading="loading.issues"
        :error="errors.issues"
        :filters="filters"
        @select="selectIssue"
        @retry="retryIssues"
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

.review-workspace__columns {
  display: grid;
  min-height: calc(100vh - 164px);
  grid-template-columns: minmax(220px, 0.8fr) minmax(480px, 2.3fr) minmax(240px, 0.9fr);
  gap: 14px;
  margin-top: 14px;
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

@media (max-width: 980px) {
  .review-workspace__columns {
    grid-template-columns: minmax(190px, 0.75fr) minmax(430px, 1.8fr);
  }

  .review-workspace__columns :deep(aside) {
    grid-column: 1 / -1;
    min-height: auto;
  }
}
</style>
