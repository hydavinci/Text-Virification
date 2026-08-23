import { computed, onScopeDispose, ref, type ComputedRef, type Ref } from 'vue'

import type { RevisionsApi } from '../api/revisions'
import { ApiError } from '../types/api'
import type { DocumentVersion, DraftBlock, EditDraft } from '../types/revisions'

export interface DraftConflict {
  code: string
  message: string
  submittedBlocks: DraftBlock[]
}

export interface EditDraftState {
  draft: Ref<EditDraft | null>
  localBlocks: Ref<DraftBlock[]>
  dirty: ComputedRef<boolean>
  conflict: Ref<DraftConflict | null>
  begin(baseVersionId: string): Promise<void>
  updateBlock(blockId: string, text: string): void
  save(): Promise<EditDraft>
  discard(): Promise<void>
  reanalyze(): Promise<DocumentVersion>
}

export function useEditDraft(
  jobId: string,
  revisionsApi: RevisionsApi,
  onReanalysisStarted?: (version: DocumentVersion) => void
): EditDraftState {
  const draft = ref<EditDraft | null>(null)
  const localBlocks = ref<DraftBlock[]>([])
  const conflict = ref<DraftConflict | null>(null)

  let active = true
  let lifecycleGeneration = 0
  let saveGeneration = 0
  let reanalysisGeneration = 0
  const reanalysisKeys = new Map<string, string>()

  const dirty = computed(() => {
    const currentDraft = draft.value
    return currentDraft ? !blocksEqual(localBlocks.value, currentDraft.blocks) : false
  })

  async function begin(baseVersionId: string): Promise<void> {
    const generation = ++lifecycleGeneration
    saveGeneration += 1
    reanalysisGeneration += 1
    const createdDraft = await revisionsApi.createDraft(jobId, baseVersionId)
    if (!isCurrentLifecycle(generation)) {
      return
    }
    draft.value = createdDraft
    localBlocks.value = cloneBlocks(createdDraft.blocks)
    conflict.value = null
    reanalysisKeys.clear()
  }

  function updateBlock(blockId: string, text: string): void {
    const nextBlocks = cloneBlocks(localBlocks.value)
    const index = nextBlocks.findIndex((block) => block.block_id === blockId)
    const updatedBlock = { block_id: blockId, text }

    if (index === -1) {
      nextBlocks.push(updatedBlock)
    } else {
      nextBlocks[index] = updatedBlock
    }

    localBlocks.value = nextBlocks
    conflict.value = null
  }

  async function save(): Promise<EditDraft> {
    const currentDraft = draft.value
    if (!currentDraft) {
      throw new Error('No active edit draft.')
    }

    const submittedBlocks = cloneBlocks(localBlocks.value)
    const requestGeneration = ++saveGeneration
    const requestLifecycleGeneration = lifecycleGeneration
    try {
      const savedDraft = await revisionsApi.updateDraft(jobId, currentDraft.draft_id, {
        expected_revision: currentDraft.revision,
        blocks: submittedBlocks
      })
      if (
        !isCurrentLifecycle(requestLifecycleGeneration) ||
        requestGeneration !== saveGeneration ||
        draft.value?.draft_id !== currentDraft.draft_id
      ) {
        return savedDraft
      }
      draft.value = savedDraft
      if (blocksEqual(localBlocks.value, submittedBlocks)) {
        localBlocks.value = cloneBlocks(savedDraft.blocks)
      }
      conflict.value = null
      return savedDraft
    } catch (error) {
      if (
        isDraftConflict(error) &&
        isCurrentLifecycle(requestLifecycleGeneration) &&
        requestGeneration === saveGeneration &&
        draft.value?.draft_id === currentDraft.draft_id
      ) {
        conflict.value = {
          code: error.detail.code,
          message: error.message,
          submittedBlocks
        }
      }
      throw error
    }
  }

  async function discard(): Promise<void> {
    const currentDraft = draft.value
    const generation = ++lifecycleGeneration
    saveGeneration += 1
    reanalysisGeneration += 1
    if (currentDraft) {
      await revisionsApi.deleteDraft(jobId, currentDraft.draft_id)
    }
    if (!isCurrentLifecycle(generation)) {
      return
    }
    draft.value = null
    localBlocks.value = []
    conflict.value = null
    reanalysisKeys.clear()
  }

  async function reanalyze(): Promise<DocumentVersion> {
    const savedDraft = dirty.value ? await save() : draft.value
    if (!savedDraft) {
      throw new Error('No active edit draft.')
    }

    const requestGeneration = ++reanalysisGeneration
    const requestLifecycleGeneration = lifecycleGeneration
    const draftKey = `${savedDraft.draft_id}:${savedDraft.revision}`
    const idempotencyKey = getReanalysisKey(draftKey)
    const response = await revisionsApi.reanalyze(jobId, savedDraft.draft_id, {
      expected_draft_revision: savedDraft.revision,
      idempotency_key: idempotencyKey
    })
    reanalysisKeys.delete(draftKey)
    if (
      isCurrentLifecycle(requestLifecycleGeneration) &&
      requestGeneration === reanalysisGeneration &&
      draft.value?.draft_id === savedDraft.draft_id &&
      draft.value.revision === savedDraft.revision
    ) {
      onReanalysisStarted?.(response.version)
    }
    return response.version
  }

  function getReanalysisKey(draftKey: string): string {
    const existingKey = reanalysisKeys.get(draftKey)
    if (existingKey) {
      return existingKey
    }

    const nextKey = `reanalyze-${draftKey}-${Date.now()}`
    reanalysisKeys.set(draftKey, nextKey)
    return nextKey
  }

  function isCurrentLifecycle(generation: number): boolean {
    return active && generation === lifecycleGeneration
  }

  onScopeDispose(() => {
    active = false
    lifecycleGeneration += 1
    saveGeneration += 1
    reanalysisGeneration += 1
  })

  return {
    draft,
    localBlocks,
    dirty,
    conflict,
    begin,
    updateBlock,
    save,
    discard,
    reanalyze
  }
}

function cloneBlocks(blocks: DraftBlock[]): DraftBlock[] {
  return blocks.map((block) => ({ ...block }))
}

function blocksEqual(left: DraftBlock[], right: DraftBlock[]): boolean {
  if (left.length !== right.length) {
    return false
  }

  return left.every(
    (block, index) =>
      block.block_id === right[index]?.block_id && block.text === right[index]?.text
  )
}

function isDraftConflict(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    error.detail.code === 'stale_draft_revision'
  )
}
