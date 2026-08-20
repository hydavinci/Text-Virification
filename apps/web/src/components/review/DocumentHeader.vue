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

    <span v-if="loading" class="document-header__status" role="status">
      正在读取问题总览…
    </span>

    <div v-else-if="error" class="document-header__error" role="alert">
      <span>{{ error }}</span>
      <button type="button" @click="emit('retry')">重试总览</button>
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
  gap: 16px;
  padding: 13px 18px;
  background: rgba(255, 255, 255, 0.95);
  border-bottom: 1px solid #dfe5ef;
  backdrop-filter: blur(8px);
}

.document-header__body {
  min-width: 0;
}

.document-header__identity {
  display: flex;
  align-items: center;
  gap: 10px;
}

.document-header__identity strong {
  overflow: hidden;
  color: #1c2538;
  font-size: 0.95rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-header__identity span {
  flex: 0 0 auto;
  padding: 2px 8px;
  color: #4256c9;
  font-size: 0.72rem;
  font-weight: 800;
  background: #eef0ff;
  border-radius: 999px;
}

.document-header__body p,
.document-header__status {
  margin: 4px 0 0;
  color: #667085;
  font-size: 0.78rem;
}

.document-header__error {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 10px;
  color: #a53636;
  font-size: 0.78rem;
}

.document-header__error button {
  min-height: 44px;
  padding: 7px 10px;
  color: #4256c9;
  font-weight: 700;
  background: #eef0ff;
  border: 0;
  border-radius: 8px;
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
}
</style>
