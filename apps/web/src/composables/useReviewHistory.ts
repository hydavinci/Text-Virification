import { computed, onScopeDispose, ref, type ComputedRef, type Ref } from 'vue'

import type { RevisionsApi } from '../api/revisions'
import type { OperationBatch, OperationBatchPage } from '../types/revisions'

const UNDO_TOAST_DURATION_MS = 10_000

export interface ReviewHistoryState {
  latestBatch: Ref<OperationBatch | null>
  undoToastDeadline: Ref<Date | null>
  undoToastVisible: Ref<boolean>
  historyPage: Ref<OperationBatchPage | null>
  undoConflict: Ref<string | null>
  canUndoLatestBatch: ComputedRef<boolean>
  recordDecisionBatch(
    batchId: string | undefined,
    versionId: string | null,
    affectedCount: number
  ): void
  setVersionScope(versionId: string | null): void
  loadHistory(versionId: string): Promise<void>
  undoLatestBatch(): Promise<void>
  undoBatch(batchId: string): Promise<void>
}

export function useReviewHistory(
  jobId: string,
  revisionsApi: RevisionsApi,
  onUndoApplied?: (undoBatch: OperationBatch) => Promise<void> | void
): ReviewHistoryState {
  const latestBatch = ref<OperationBatch | null>(null)
  const undoToastDeadline = ref<Date | null>(null)
  const undoToastVisible = ref(false)
  const historyPage = ref<OperationBatchPage | null>(null)
  const undoConflict = ref<string | null>(null)
  const scopedVersionId = ref<string | null>(null)

  let active = true
  let toastTimer: ReturnType<typeof setTimeout> | null = null
  let historyGeneration = 0

  const canUndoLatestBatch = computed(
    () =>
      latestBatch.value !== null &&
      latestBatch.value.operation_type === 'decision' &&
      latestBatch.value.version_id === scopedVersionId.value
  )

  function recordDecisionBatch(
    batchId: string | undefined,
    versionId: string | null,
    affectedCount: number
  ): void {
    if (!batchId || !versionId || affectedCount < 1) {
      return
    }
    if (scopedVersionId.value === null) {
      scopedVersionId.value = versionId
    }
    if (scopedVersionId.value !== versionId) {
      return
    }

    historyGeneration += 1
    latestBatch.value = {
      batch_id: batchId,
      job_id: jobId,
      version_id: versionId,
      operation_type: 'decision',
      affected_count: affectedCount,
      undoes_batch_id: null,
      created_at: new Date().toISOString()
    }
    if (historyPage.value?.version_id === versionId) {
      historyPage.value = {
        ...historyPage.value,
        total: historyPage.value.total + 1,
        items: [latestBatch.value, ...historyPage.value.items]
      }
    }
    undoToastDeadline.value = new Date(Date.now() + UNDO_TOAST_DURATION_MS)
    undoToastVisible.value = true
    undoConflict.value = null

    if (toastTimer) {
      clearTimeout(toastTimer)
    }
    toastTimer = setTimeout(() => {
      undoToastVisible.value = false
      toastTimer = null
    }, UNDO_TOAST_DURATION_MS)
  }

  async function loadHistory(versionId: string): Promise<void> {
    if (scopedVersionId.value !== versionId) {
      setVersionScope(versionId)
    }
    const generation = ++historyGeneration
    const page = await revisionsApi.listHistory(jobId, versionId)
    if (
      active &&
      generation === historyGeneration &&
      scopedVersionId.value === page.version_id
    ) {
      applyHistoryPage(page)
    }
  }

  async function undoLatestBatch(): Promise<void> {
    const batch = latestBatch.value
    if (!batch || batch.version_id !== scopedVersionId.value) {
      return
    }

    await undoBatch(batch.batch_id)
  }

  async function undoBatch(batchId: string): Promise<void> {
    const batch = findScopedUndoableBatch(batchId)
    if (!batch) {
      return
    }

    const versionId = scopedVersionId.value
    const generation = ++historyGeneration
    try {
      const undoBatch = await revisionsApi.undoBatch(jobId, batch.batch_id)
      if (!isCurrentHistoryRequest(generation, versionId, undoBatch.version_id)) {
        return
      }

      applyUndoBatch(undoBatch)
      undoConflict.value = null
      undoToastVisible.value = false
      if (toastTimer) {
        clearTimeout(toastTimer)
        toastTimer = null
      }
      await onUndoApplied?.(undoBatch)
    } catch (error) {
      if (!isCurrentHistoryRequest(generation, versionId)) {
        return
      }

      undoConflict.value = error instanceof Error ? error.message : '撤销失败。'
    }
  }

  function isCurrentHistoryRequest(
    generation: number,
    requestedVersionId: string | null,
    responseVersionId: string | null = requestedVersionId
  ): boolean {
    return (
      active &&
      generation === historyGeneration &&
      scopedVersionId.value === requestedVersionId &&
      responseVersionId === requestedVersionId
    )
  }

  function applyHistoryPage(page: OperationBatchPage): void {
    if (page.version_id !== scopedVersionId.value) {
      return
    }
    historyPage.value = page
    latestBatch.value = latestUndoableBatch(page.items)
  }

  function applyUndoBatch(undoBatch: OperationBatch): void {
    if (historyPage.value?.version_id === undoBatch.version_id) {
      historyPage.value = {
        ...historyPage.value,
        total: historyPage.value.total + 1,
        items: [undoBatch, ...historyPage.value.items]
      }
      latestBatch.value = latestUndoableBatch(historyPage.value.items)
      return
    }

    if (!historyPage.value) {
      historyPage.value = {
        job_id: jobId,
        version_id: undoBatch.version_id,
        total: 1,
        items: [undoBatch],
        next_cursor: null
      }
    }

    if (latestBatch.value?.batch_id === undoBatch.undoes_batch_id) {
      latestBatch.value = null
    }
  }

  function findScopedUndoableBatch(batchId: string): OperationBatch | null {
    const candidates = [
      ...(historyPage.value?.items ?? []),
      ...(latestBatch.value ? [latestBatch.value] : [])
    ]
    const batch =
      candidates.find(
        (item) => item.batch_id === batchId && item.version_id === scopedVersionId.value
      ) ?? null
    if (
      !batch ||
      batch.operation_type !== 'decision' ||
      isBatchUndone(batch, candidates)
    ) {
      return null
    }
    return batch
  }

  function setVersionScope(versionId: string | null): void {
    if (scopedVersionId.value === versionId) {
      return
    }

    scopedVersionId.value = versionId
    historyGeneration += 1
    latestBatch.value = null
    undoToastDeadline.value = null
    undoToastVisible.value = false
    undoConflict.value = null
    if (historyPage.value?.version_id !== versionId) {
      historyPage.value = null
    }
    if (toastTimer) {
      clearTimeout(toastTimer)
      toastTimer = null
    }
  }

  onScopeDispose(() => {
    active = false
    historyGeneration += 1
    if (toastTimer) {
      clearTimeout(toastTimer)
    }
  })

  return {
    latestBatch,
    undoToastDeadline,
    undoToastVisible,
    historyPage,
    undoConflict,
    canUndoLatestBatch,
    recordDecisionBatch,
    setVersionScope,
    loadHistory,
    undoLatestBatch,
    undoBatch
  }
}

function latestUndoableBatch(items: OperationBatch[]): OperationBatch | null {
  const newestFirst = [...items].sort(
    (left, right) =>
      new Date(right.created_at).getTime() - new Date(left.created_at).getTime()
  )

  return (
    newestFirst.find(
      (item) => item.operation_type === 'decision' && !isBatchUndone(item, items)
    ) ?? null
  )
}

function isBatchUndone(batch: OperationBatch, items: OperationBatch[]): boolean {
  const batchTime = Date.parse(batch.created_at)
  return items.some((item) => {
    if (item.operation_type !== 'undo' || item.undoes_batch_id !== batch.batch_id) {
      return false
    }
    const undoTime = Date.parse(item.created_at)
    return Number.isNaN(batchTime) || Number.isNaN(undoTime) || undoTime > batchTime
  })
}
