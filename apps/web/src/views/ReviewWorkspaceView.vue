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
  blocks,
  issues,
  selectedIssueId,
  selectedIssue,
  selectedBlockId,
  blockCursor,
  loading,
  errors,
  checkerFailures,
  selectIssue,
  selectHighlight,
  loadNextBlocks,
  retrySummary,
  retryDocument,
  retryIssues
} = useReviewWorkspace(props.jobId)
</script>

<template>
  <section class="review-workspace" aria-label="文档审阅工作台">
    <ReviewToolbar
      :source-name="sourceName"
      :file-type="fileType"
      :summary="summary"
      :loading="loading.summary"
      :error="errors.summary"
      :checker-failures="checkerFailures"
      @retry="retrySummary"
    />

    <div class="review-workspace__columns">
      <ReviewNavigation
        :summary="summary"
        :issues="issues"
        :selected-issue-id="selectedIssueId"
        :loading="loading.issues"
        :error="errors.issues"
        @select="selectIssue"
        @retry="retryIssues"
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
      <IssuePanel :issue="selectedIssue" />
    </div>
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
