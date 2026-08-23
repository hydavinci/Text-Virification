<script setup lang="ts">
import { computed } from 'vue'

import type { DocumentBlock } from '../../types/analysis'
import type { DraftBlock } from '../../types/revisions'

const props = defineProps<{
  blocks: DocumentBlock[]
  draftBlocks: DraftBlock[]
  busy: boolean
  error: string | null
}>()

const emit = defineEmits<{
  updateBlock: [blockId: string, text: string]
  saveReanalyze: []
  discard: []
}>()

const editorBlocks = computed<DocumentBlock[]>(() => {
  const nextBlocks = [...props.blocks]
  const seen = new Set(nextBlocks.map((block) => block.block_id))
  props.draftBlocks.forEach((draftBlock, index) => {
    if (seen.has(draftBlock.block_id)) {
      return
    }
    nextBlocks.push({
      block_id: draftBlock.block_id,
      kind: 'paragraph',
      text: draftBlock.text,
      page: null,
      paragraph_index: props.blocks.length + index,
      parent_id: null,
      style: {},
      source_locator: {}
    })
  })
  return nextBlocks
})

function draftText(block: DocumentBlock): string {
  return (
    props.draftBlocks.find((draftBlock) => draftBlock.block_id === block.block_id)?.text ??
    block.text
  )
}

function paragraphNumber(block: DocumentBlock, index: number): number {
  return typeof block.paragraph_index === 'number' ? block.paragraph_index + 1 : index + 1
}

function updateBlock(blockId: string, event: Event): void {
  const target = event.target
  if (target instanceof HTMLTextAreaElement) {
    emit('updateBlock', blockId, target.value)
  }
}
</script>

<template>
  <form class="document-editor" aria-label="编辑草稿" @submit.prevent="emit('saveReanalyze')">
    <div class="document-editor__blocks">
      <div
        v-for="(block, index) in editorBlocks"
        :key="block.block_id"
        class="document-editor__block"
        :data-block-id="block.block_id"
      >
        <label :for="`draft-${block.block_id}`">第 {{ paragraphNumber(block, index) }} 段</label>
        <textarea
          :id="`draft-${block.block_id}`"
          :aria-label="`第 ${paragraphNumber(block, index)} 段`"
          :value="draftText(block)"
          :disabled="busy"
          rows="4"
          @input="updateBlock(block.block_id, $event)"
        />
      </div>
    </div>

    <p v-if="error" class="document-editor__error" role="alert">{{ error }}</p>

    <div class="document-editor__actions">
      <button
        type="button"
        name="save-reanalyze"
        :disabled="busy"
        @click="emit('saveReanalyze')"
      >
        保存草稿并重新检查
      </button>
      <button
        type="button"
        name="discard-draft"
        class="document-editor__secondary"
        :disabled="busy"
        @click="emit('discard')"
      >
        放弃草稿
      </button>
    </div>
  </form>
</template>

<style scoped>
.document-editor {
  display: grid;
  max-height: clamp(220px, calc(100dvh - 360px), 360px);
  gap: var(--review-space-4);
  grid-template-rows: minmax(0, 1fr) auto auto;
}

.document-editor__blocks {
  display: grid;
  min-height: 0;
  gap: var(--review-space-4);
  overflow: auto;
  padding-right: var(--review-space-1);
}

.document-editor__block {
  display: grid;
  gap: var(--review-space-2);
}

.document-editor__block label {
  color: var(--review-text-muted);
  font-size: 0.78rem;
  font-weight: 800;
}

.document-editor textarea {
  width: 100%;
  min-height: 120px;
  padding: var(--review-space-3);
  color: var(--review-text);
  font: inherit;
  line-height: 1.7;
  resize: vertical;
  background: #fbfcff;
  border: 1px solid var(--review-border);
  border-radius: var(--review-panel-radius);
}

.document-editor__error {
  margin: 0;
  color: var(--review-danger);
  font-weight: 700;
}

.document-editor__actions {
  display: flex;
  justify-content: end;
  gap: var(--review-space-2);
  padding-top: var(--review-space-3);
  border-top: 1px solid var(--review-border);
}

.document-editor__actions button {
  min-height: 44px;
  padding: 0 var(--review-space-4);
  color: #fff;
  font-weight: 800;
  background: var(--review-accent);
  border: 0;
  border-radius: var(--review-panel-radius);
  cursor: pointer;
}

.document-editor__actions button:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.document-editor__actions .document-editor__secondary {
  color: var(--review-accent);
  background: var(--review-accent-soft);
}
</style>
