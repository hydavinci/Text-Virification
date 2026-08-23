<script setup lang="ts">
import { computed } from 'vue'

import type { OperationBatch, OperationBatchPage } from '../../types/revisions'

const props = defineProps<{
  historyPage: OperationBatchPage | null
  latestBatch: OperationBatch | null
  canUndoLatestBatch: boolean
  undoConflict: string | null
  busy: boolean
}>()

const emit = defineEmits<{
  undoLatest: []
  undoBatch: [batchId: string]
}>()

function operationLabel(batch: OperationBatch): string {
  return batch.operation_type === 'undo' ? '撤销操作' : '处理决定'
}

const visibleBatches = computed(() =>
  props.historyPage?.items.length
    ? props.historyPage.items
    : props.latestBatch
      ? [props.latestBatch]
      : []
)
const visibleTotal = computed(() => props.historyPage?.total ?? visibleBatches.value.length)
function canUndoBatch(batch: OperationBatch): boolean {
  return (
    !props.busy &&
    batch.operation_type === 'decision' &&
    !isBatchUndone(batch)
  )
}

function isBatchUndone(batch: OperationBatch): boolean {
  const batchTime = Date.parse(batch.created_at)
  return visibleBatches.value.some((item) => {
    if (item.operation_type !== 'undo' || item.undoes_batch_id !== batch.batch_id) {
      return false
    }
    const undoTime = Date.parse(item.created_at)
    return Number.isNaN(batchTime) || Number.isNaN(undoTime) || undoTime > batchTime
  })
}
</script>

<template>
  <section class="operation-history" data-testid="operation-history" aria-label="操作历史">
    <div class="operation-history__heading">
      <div>
        <strong>操作历史</strong>
        <p>查看服务端记录的批处理，并可撤销最近一次处理。</p>
      </div>
      <span>{{ visibleTotal }} 项</span>
    </div>

    <button
      type="button"
      name="undo-latest"
      data-testid="history-undo-latest"
      :disabled="busy || !canUndoLatestBatch"
      @click="emit('undoLatest')"
    >
      撤销最近处理
    </button>

    <p v-if="undoConflict" class="operation-history__error" role="alert">
      {{ undoConflict }}
    </p>

    <ol v-if="visibleBatches.length" class="operation-history__list">
      <li v-for="batch in visibleBatches" :key="batch.batch_id">
        <div>
          <span>{{ operationLabel(batch) }}</span>
          <small>{{ batch.affected_count }} 项 · {{ batch.created_at }}</small>
        </div>
        <button
          v-if="batch.operation_type === 'decision'"
          type="button"
          name="undo-batch"
          :disabled="!canUndoBatch(batch)"
          @click="emit('undoBatch', batch.batch_id)"
        >
          撤销此批次
        </button>
      </li>
    </ol>
    <p v-else class="operation-history__empty">暂无操作历史。</p>
  </section>
</template>

<style scoped>
.operation-history {
  display: grid;
  gap: var(--review-space-3);
}

.operation-history__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--review-space-3);
}

.operation-history__heading strong {
  display: block;
  color: var(--review-text);
  font-size: 0.86rem;
}

.operation-history__heading p,
.operation-history__empty,
.operation-history__error,
.operation-history__list small {
  margin: 4px 0 0;
  font-size: 0.76rem;
  line-height: 1.5;
}

.operation-history__heading p,
.operation-history__empty,
.operation-history__list small {
  color: var(--review-text-muted);
}

.operation-history__heading > span {
  padding: var(--review-space-1) var(--review-space-2);
  color: var(--review-accent);
  font-size: 0.74rem;
  font-weight: 800;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border-radius: 999px;
}

.operation-history button {
  min-height: 44px;
  padding: 9px 11px;
  color: var(--review-accent);
  font-weight: 700;
  background: var(--review-accent-soft);
  border: 1px solid transparent;
  border-radius: calc(var(--review-panel-radius) - 3px);
  cursor: pointer;
}

.operation-history button:focus-visible {
  outline: 2px solid #6579e8;
  outline-offset: 2px;
}

.operation-history button:disabled {
  color: #8c93a8;
  cursor: not-allowed;
  background: var(--review-canvas);
}

.operation-history__error {
  margin: 0;
  color: var(--review-danger);
}

.operation-history__list {
  display: grid;
  gap: var(--review-space-2);
  padding: 0;
  margin: 0;
  list-style: none;
}

.operation-history__list li {
  display: grid;
  gap: 3px;
  padding: 10px;
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) - 4px);
}

.operation-history__list span {
  color: var(--review-text);
  font-size: 0.82rem;
  font-weight: 700;
}
</style>
