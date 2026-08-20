<script setup lang="ts">
import type { FileType } from '../../types/review'

defineProps<{
  sourceName: string
  fileType: FileType
  loadedParagraphCount: number
  totalIssues: number | null
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{
  retry: []
  processAnotherFile: []
}>()
</script>

<template>
  <header class="document-header" data-testid="document-header">
    <div class="document-header__body">
      <div class="document-header__identity">
        <strong :title="sourceName">{{ sourceName }}</strong>
        <span>{{ fileType.toUpperCase() }}</span>
      </div>
      <p>{{ loadedParagraphCount }} 个已加载段落 · {{ totalIssues ?? '—' }} 个问题</p>
    </div>

    <div class="document-header__actions">
      <span v-if="loading" class="document-header__status" role="status">
        正在读取问题总览…
      </span>

      <div v-else-if="error" class="document-header__error" role="alert">
        <span>{{ error }}</span>
        <button type="button" @click="emit('retry')">重试总览</button>
      </div>

      <button
        type="button"
        name="process-another-file"
        class="document-header__new-file"
        @click="emit('processAnotherFile')"
      >
        处理其他文件
      </button>
    </div>
  </header>
</template>

<style scoped>
.document-header {
  position: sticky;
  z-index: 2;
  top: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--review-space-4);
  padding: calc(var(--review-space-3) + 1px) calc(var(--review-space-4) + 2px);
  background: rgba(255, 255, 255, 0.95);
  border-bottom: 1px solid var(--review-border);
  backdrop-filter: blur(8px);
}

.document-header__body {
  min-width: 0;
}

.document-header__actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: var(--review-space-2);
}

.document-header__identity {
  display: flex;
  align-items: center;
  gap: calc(var(--review-space-2) + 2px);
}

.document-header__identity strong {
  overflow: hidden;
  color: var(--review-text);
  font-size: 0.95rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-header__identity span {
  flex: 0 0 auto;
  padding: 2px var(--review-space-2);
  color: var(--review-accent);
  font-size: 0.72rem;
  font-weight: 800;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border-radius: 999px;
}

.document-header__body p,
.document-header__status {
  margin: 4px 0 0;
  color: var(--review-text-muted);
  font-size: 0.78rem;
}

.document-header__error {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: calc(var(--review-space-2) + 2px);
  color: var(--review-danger);
  font-size: 0.78rem;
}

.document-header__error button {
  min-height: 44px;
  padding: 7px calc(var(--review-space-2) + 2px);
  color: var(--review-accent);
  font-weight: 700;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border: 0;
  border-radius: calc(var(--review-panel-radius) - 4px);
  cursor: pointer;
}

.document-header__new-file {
  min-height: 44px;
  padding: 0 var(--review-space-3);
  color: var(--review-accent);
  font-weight: 700;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) - 2px);
  cursor: pointer;
}

@media (max-width: 680px) {
  .document-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .document-header__error {
    flex-wrap: wrap;
  }

  .document-header__actions {
    width: 100%;
    justify-content: space-between;
  }
}
</style>
