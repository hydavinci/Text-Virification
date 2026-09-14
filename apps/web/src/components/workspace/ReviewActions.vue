<script setup lang="ts">
import type {
  IssueState,
  WorkspaceReviewSummary
} from '../../types/verification'

const props = defineProps<{
  selectedIssueId: string | null
  selectedIssueState: IssueState | null
  visibleIssueIds: readonly string[]
  summary: WorkspaceReviewSummary
  hasConflicts: boolean
  conflictIssueIds: readonly string[]
  canUndoLastBatch: boolean
  disabled: boolean
}>()

const emit = defineEmits<{
  'set-issue-state': [issueId: string, state: IssueState]
  'undo-issue': [issueId: string]
  'set-visible-state': [issueIds: string[], state: IssueState]
  'undo-batch': []
}>()

function setSelectedState(state: 'accepted' | 'rejected'): void {
  if (props.selectedIssueId !== null && !props.disabled) {
    emit('set-issue-state', props.selectedIssueId, state)
  }
}

function undoSelected(): void {
  if (props.selectedIssueId !== null && !props.disabled) {
    emit('undo-issue', props.selectedIssueId)
  }
}

function setVisibleState(state: IssueState): void {
  if (!props.disabled && props.visibleIssueIds.length > 0) {
    emit('set-visible-state', [...props.visibleIssueIds], state)
  }
}
</script>

<template>
  <div class="review-actions" aria-label="审阅操作">
    <div class="review-counts" aria-label="审阅计数">
      <span>待处理 <strong data-count="pending">{{ summary.pending }}</strong></span>
      <span>已接受 <strong data-count="accepted">{{ summary.accepted }}</strong></span>
      <span>已忽略 <strong data-count="rejected">{{ summary.rejected }}</strong></span>
    </div>

    <p v-if="hasConflicts" class="conflict" role="alert">
      {{ conflictIssueIds.length }} 个已接受问题存在替换冲突
    </p>

    <details class="review-disclosure">
      <summary>审阅操作</summary>
      <div class="action-groups">
      <div class="selected-actions" aria-label="当前问题操作">
        <button
          class="btn accept small ui-button ui-button--primary"
          type="button"
          data-action="accept-selected"
          :disabled="disabled || selectedIssueId === null"
          @click="setSelectedState('accepted')"
        >
          接受当前
        </button>
        <button
          class="btn reject small ui-button ui-button--quiet"
          type="button"
          data-action="reject-selected"
          :disabled="disabled || selectedIssueId === null"
          @click="setSelectedState('rejected')"
        >
          忽略当前
        </button>
        <button
          class="btn small ui-button"
          type="button"
          data-action="reset-selected"
          :disabled="
            disabled ||
            selectedIssueId === null ||
            selectedIssueState === 'pending'
          "
          @click="undoSelected"
        >
          撤销当前
        </button>
      </div>

      <div class="batch-actions" aria-label="当前筛选结果批量操作">
        <button
          class="btn accept small ui-button ui-button--primary"
          type="button"
          data-action="accept-batch"
          :disabled="disabled || visibleIssueIds.length === 0"
          @click="setVisibleState('accepted')"
        >
          全部接受
        </button>
        <button
          class="btn reject small ui-button ui-button--quiet"
          type="button"
          data-action="reject-batch"
          :disabled="disabled || visibleIssueIds.length === 0"
          @click="setVisibleState('rejected')"
        >
          全部忽略
        </button>
        <button
          class="btn small ui-button"
          type="button"
          data-action="reset-batch"
          :disabled="disabled || visibleIssueIds.length === 0"
          @click="setVisibleState('pending')"
        >
          重置状态
        </button>
        <button
          class="btn small ui-button"
          type="button"
          data-action="undo-batch"
          :disabled="disabled || !canUndoLastBatch"
          @click="emit('undo-batch')"
        >
          撤销批量操作
        </button>
      </div>
      </div>
    </details>
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

.review-counts,
.action-groups,
.selected-actions,
.batch-actions {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}

.review-counts {
  color: var(--muted);
  font-size: 12px;
  gap: 10px;
  font-variant-numeric: tabular-nums;
}
.review-counts > span { white-space: nowrap; }

.review-counts strong {
  color: var(--text);
  font-weight: 600;
}
.review-counts [data-count='pending'] { color: var(--primary); }
.review-counts [data-count='accepted'] { color: var(--success); }

.action-groups {
  flex-direction: column;
  align-items: stretch;
}
.review-disclosure { position: relative; }
.review-disclosure summary { min-height: 36px; cursor: pointer; padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--radius-control); background: var(--surface); font-size: 13px; line-height: 18px; box-shadow: var(--shadow-small); }
.review-disclosure .action-groups { position: absolute; right: 0; top: calc(100% + 6px); z-index: 25; width: min(320px, calc(100vw - 32px)); padding: 12px; border: 1px solid var(--border); border-radius: 9px; background: var(--surface); box-shadow: var(--shadow); }
.batch-actions { padding-top: 10px; border-top: 1px solid var(--border); }

.conflict {
  margin: 0;
  color: var(--warning);
  font-size: 12px;
  font-weight: 500;
}
</style>
