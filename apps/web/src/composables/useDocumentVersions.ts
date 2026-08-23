import { computed, onScopeDispose, ref, type ComputedRef, type Ref } from 'vue'

import type { RevisionsApi } from '../api/revisions'
import type { DocumentVersion, VersionEvent } from '../types/revisions'

export interface ReanalysisProgress {
  versionId: string
  sequence: number
  status: VersionEvent['status']
  progress: number
  message: string
  createdAt: string
  metadata: VersionEvent['metadata']
}

export interface DocumentVersionsState {
  versions: Ref<DocumentVersion[]>
  activeVersionId: Ref<string | null>
  selectedVersionId: Ref<string | null>
  selectedVersion: ComputedRef<DocumentVersion | null>
  reanalysis: Ref<ReanalysisProgress | null>
  selectVersion(versionId: string): Promise<void>
  refreshVersions(): Promise<void>
}

export interface DocumentVersionsController extends DocumentVersionsState {
  trackReanalysis(
    version: DocumentVersion,
    onSucceeded?: (versionId: string) => Promise<void> | void
  ): void
}

export function useDocumentVersions(
  jobId: string,
  revisionsApi: RevisionsApi
): DocumentVersionsController {
  const versions = ref<DocumentVersion[]>([])
  const activeVersionId = ref<string | null>(null)
  const selectedVersionId = ref<string | null>(null)
  const reanalysis = ref<ReanalysisProgress | null>(null)

  let active = true
  let versionsGeneration = 0
  let reanalysisGeneration = 0
  let unsubscribeEvents: (() => void) | null = null

  const selectedVersion = computed(
    () =>
      versions.value.find((version) => version.version_id === selectedVersionId.value) ??
      null
  )

  async function refreshVersions(): Promise<void> {
    const generation = ++versionsGeneration
    const response = await revisionsApi.listVersions(jobId)
    if (!isCurrent(generation, versionsGeneration)) {
      return
    }

    versions.value = response.versions
    activeVersionId.value = response.active_version_id
    if (
      selectedVersionId.value === null ||
      !response.versions.some((version) => version.version_id === selectedVersionId.value)
    ) {
      selectedVersionId.value = response.active_version_id
    }
  }

  async function selectVersion(versionId: string): Promise<void> {
    selectedVersionId.value = versionId
  }

  function trackReanalysis(
    version: DocumentVersion,
    onSucceeded?: (versionId: string) => Promise<void> | void
  ): void {
    const generation = ++reanalysisGeneration
    unsubscribeEvents?.()
    reanalysis.value = {
      versionId: version.version_id,
      sequence: 0,
      status: version.status,
      progress: version.status === 'queued' ? 0 : 100,
      message: version.failure_message ?? '',
      createdAt: version.created_at,
      metadata: null
    }

    unsubscribeEvents = revisionsApi.subscribeVersionEvents(
      jobId,
      version.version_id,
      (event) => {
        if (!isCurrent(generation, reanalysisGeneration)) {
          return
        }
        if (
          reanalysis.value?.versionId === version.version_id &&
          event.sequence < reanalysis.value.sequence
        ) {
          return
        }

        reanalysis.value = {
          versionId: version.version_id,
          sequence: event.sequence,
          status: event.status,
          progress: event.progress,
          message: event.message,
          createdAt: event.created_at,
          metadata: event.metadata
        }

        if (event.status === 'succeeded') {
          void (async () => {
            await refreshVersions()
            if (isCurrent(generation, reanalysisGeneration)) {
              selectedVersionId.value = version.version_id
              await onSucceeded?.(version.version_id)
            }
          })()
        }
      },
      (message) => {
        if (isCurrent(generation, reanalysisGeneration)) {
          reanalysis.value = {
            versionId: version.version_id,
            sequence: reanalysis.value?.sequence ?? 0,
            status: reanalysis.value?.status ?? version.status,
            progress: reanalysis.value?.progress ?? 0,
            message,
            createdAt: reanalysis.value?.createdAt ?? version.created_at,
            metadata: reanalysis.value?.metadata ?? null
          }
        }
      }
    )
  }

  function isCurrent(generation: number, currentGeneration: number): boolean {
    return active && generation === currentGeneration
  }

  onScopeDispose(() => {
    active = false
    versionsGeneration += 1
    reanalysisGeneration += 1
    unsubscribeEvents?.()
  })

  return {
    versions,
    activeVersionId,
    selectedVersionId,
    selectedVersion,
    reanalysis,
    selectVersion,
    refreshVersions,
    trackReanalysis
  }
}
