import { computed, ref, type ComputedRef, type Ref } from 'vue'

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

  const dirty = computed(() => {
    const currentDraft = draft.value
    return currentDraft ? !blocksEqual(localBlocks.value, currentDraft.blocks) : false
  })

  async function begin(baseVersionId: string): Promise<void> {
    const createdDraft = await revisionsApi.createDraft(jobId, baseVersionId)
    draft.value = createdDraft
    localBlocks.value = cloneBlocks(createdDraft.blocks)
    conflict.value = null
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
    try {
      const savedDraft = await revisionsApi.updateDraft(jobId, currentDraft.draft_id, {
        expected_revision: currentDraft.revision,
        blocks: submittedBlocks
      })
      draft.value = savedDraft
      localBlocks.value = cloneBlocks(savedDraft.blocks)
      conflict.value = null
      return savedDraft
    } catch (error) {
      if (isDraftConflict(error)) {
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
    if (currentDraft) {
      await revisionsApi.deleteDraft(jobId, currentDraft.draft_id)
    }
    draft.value = null
    localBlocks.value = []
    conflict.value = null
  }

  async function reanalyze(): Promise<DocumentVersion> {
    const savedDraft = dirty.value ? await save() : draft.value
    if (!savedDraft) {
      throw new Error('No active edit draft.')
    }

    const response = await revisionsApi.reanalyze(jobId, savedDraft.draft_id, {
      expected_draft_revision: savedDraft.revision,
      idempotency_key: `reanalyze-${savedDraft.draft_id}-${savedDraft.revision}-${Date.now()}`
    })
    onReanalysisStarted?.(response.version)
    return response.version
  }

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
