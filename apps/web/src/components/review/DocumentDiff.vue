<script setup lang="ts">
import type { DerivedDiffBlock, DiffSegment } from '../../types/revisions'

defineProps<{
  blocks: DerivedDiffBlock[]
}>()

function segmentClass(segment: DiffSegment): string {
  return `document-diff__segment document-diff__segment--${segment.kind}`
}
</script>

<template>
  <div class="document-diff" aria-label="差异内容">
    <p
      v-for="block in blocks"
      :key="block.block_id"
      class="document-block document-diff__block"
      :data-block-id="block.block_id"
    >
      <template v-for="(segment, index) in block.segments" :key="`${block.block_id}-${index}`">
        <ins v-if="segment.kind === 'insert'" :class="segmentClass(segment)">{{ segment.text }}</ins>
        <del v-else-if="segment.kind === 'delete'" :class="segmentClass(segment)">{{ segment.text }}</del>
        <span v-else :class="segmentClass(segment)">{{ segment.text }}</span>
      </template>
    </p>

    <p v-if="!blocks.length" class="document-diff__empty">没有可显示的差异。</p>
  </div>
</template>

<style scoped>
.document-diff {
  display: block;
}

.document-diff__segment {
  white-space: pre-wrap;
}

.document-diff__segment--insert {
  color: #166534;
  text-decoration: none;
  background: #dcfce7;
}

.document-diff__segment--delete {
  color: #991b1b;
  background: #fee2e2;
}

.document-diff__empty {
  color: var(--review-text-muted);
  text-align: center;
}
</style>
