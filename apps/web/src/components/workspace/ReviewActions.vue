<script setup lang="ts">
import type { WorkspaceReviewSummary } from '../../types/verification'

defineProps<{
  summary: WorkspaceReviewSummary
  hasConflicts: boolean
  conflictIssueIds: readonly string[]
}>()
</script>

<template>
  <div class="review-actions" aria-label="审阅状态">
    <div class="review-counts" aria-label="审阅计数">
      <span>待处理 <strong data-count="pending">{{ summary.pending }}</strong></span>
      <span>已接受 <strong data-count="accepted">{{ summary.accepted }}</strong></span>
      <span>已忽略 <strong data-count="rejected">{{ summary.rejected }}</strong></span>
    </div>

    <p v-if="hasConflicts" class="conflict" role="alert">
      {{ conflictIssueIds.length }} 个已接受问题存在替换冲突
    </p>
  </div>
</template>

<style scoped>
.review-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 12px;
}

.review-counts {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  color: var(--muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.review-counts > span { white-space: nowrap; }

.review-counts strong {
  color: var(--text);
  font-weight: 600;
}
.review-counts [data-count='pending'] { color: var(--primary); }
.review-counts [data-count='accepted'] { color: var(--success); }

.conflict {
  margin: 0;
  color: var(--warning);
  font-size: 12px;
  font-weight: 500;
}
</style>
