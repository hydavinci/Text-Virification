import { onScopeDispose, ref, type Ref } from 'vue'

import type { RevisionsApi } from '../api/revisions'
import type {
  DiffDerivedResponse,
  DocumentViewMode,
  ModifiedDerivedResponse
} from '../types/revisions'

export interface DerivedPreviewState {
  modified: Ref<ModifiedDerivedResponse | null>
  diff: Ref<DiffDerivedResponse | null>
  loading: Ref<DocumentViewMode | null>
  error: Ref<string | null>
  decisionSnapshotSha256: Ref<string | null>
  load(
    mode: Extract<DocumentViewMode, 'modified' | 'diff'>,
    versionId: string,
    expectedDecisionSnapshotSha256?: string | null
  ): Promise<void>
  clear(): void
}

export function useDerivedPreview(
  jobId: string,
  revisionsApi: RevisionsApi
): DerivedPreviewState {
  const modified = ref<ModifiedDerivedResponse | null>(null)
  const diff = ref<DiffDerivedResponse | null>(null)
  const loading = ref<DocumentViewMode | null>(null)
  const error = ref<string | null>(null)
  const decisionSnapshotSha256 = ref<string | null>(null)

  let active = true
  let generation = 0

  async function load(
    mode: Extract<DocumentViewMode, 'modified' | 'diff'>,
    versionId: string,
    expectedDecisionSnapshotSha256: string | null = decisionSnapshotSha256.value
  ): Promise<void> {
    const requestGeneration = ++generation
    loading.value = mode
    error.value = null

    try {
      const response = await revisionsApi.getDerived(jobId, versionId, mode)
      if (!isCurrent(requestGeneration)) {
        return
      }
      if (
        expectedDecisionSnapshotSha256 !== null &&
        response.decision_snapshot_sha256 !== expectedDecisionSnapshotSha256
      ) {
        return
      }

      decisionSnapshotSha256.value = response.decision_snapshot_sha256
      if (mode === 'modified') {
        modified.value = response as ModifiedDerivedResponse
      } else {
        diff.value = response as DiffDerivedResponse
      }
    } catch (caughtError) {
      if (isCurrent(requestGeneration)) {
        error.value = caughtError instanceof Error ? caughtError.message : '无法加载预览。'
      }
    } finally {
      if (isCurrent(requestGeneration)) {
        loading.value = null
      }
    }
  }

  function clear(): void {
    generation += 1
    modified.value = null
    diff.value = null
    loading.value = null
    error.value = null
    decisionSnapshotSha256.value = null
  }

  function isCurrent(requestGeneration: number): boolean {
    return active && requestGeneration === generation
  }

  onScopeDispose(() => {
    active = false
    generation += 1
  })

  return {
    modified,
    diff,
    loading,
    error,
    decisionSnapshotSha256,
    load,
    clear
  }
}
