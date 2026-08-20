<script setup lang="ts">
const props = defineProps<{
  query: string
  replacement: string
  status: string
  canNavigate: boolean
  canReplaceAll: boolean
  busy: boolean
  error: string | null
}>()

const emit = defineEmits<{
  updateQuery: [value: string]
  updateReplacement: [value: string]
  previousMatch: []
  nextMatch: []
  replaceAll: []
}>()
</script>

<template>
  <section class="find-replace" aria-label="文档查找与替换">
    <div class="find-replace__heading">
      <strong>查找与替换</strong>
      <p>仅在已加载文档内容中搜索。</p>
    </div>

    <div class="find-replace__fields">
      <label>
        <span>查找内容</span>
        <input
          :value="query"
          type="search"
          aria-label="查找内容"
          placeholder="输入要查找的文本"
          @input="emit('updateQuery', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <label>
        <span>替换为</span>
        <input
          :value="replacement"
          aria-label="替换为"
          placeholder="输入替换文本"
          @input="emit('updateReplacement', ($event.target as HTMLInputElement).value)"
        />
      </label>
    </div>

    <div class="find-replace__actions">
      <div class="find-replace__nav">
        <button
          type="button"
          name="previous-match"
          :disabled="busy || !canNavigate"
          @click="emit('previousMatch')"
        >
          上一处
        </button>
        <button
          type="button"
          name="next-match"
          :disabled="busy || !canNavigate"
          @click="emit('nextMatch')"
        >
          下一处
        </button>
      </div>
      <button
        type="button"
        name="replace-all"
        :disabled="busy || !canReplaceAll"
        @click="emit('replaceAll')"
      >
        全部替换
      </button>
    </div>

    <p class="find-replace__status" data-testid="find-status" role="status">{{ status }}</p>
    <p v-if="error" class="find-replace__error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.find-replace {
  display: grid;
  min-width: 0;
  gap: var(--review-space-3);
}

.find-replace__heading strong {
  display: block;
  color: var(--review-text);
  font-size: 0.86rem;
}

.find-replace__heading p,
.find-replace__status,
.find-replace__error {
  margin: 4px 0 0;
  font-size: 0.76rem;
  line-height: 1.5;
}

.find-replace__heading p,
.find-replace__status {
  color: var(--review-text-muted);
}

.find-replace__fields {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: calc(var(--review-space-2) + 2px);
}

.find-replace__fields label {
  display: grid;
  gap: 5px;
  color: var(--review-text-muted);
  font-size: 0.72rem;
  font-weight: 700;
}

.find-replace__fields input {
  width: 100%;
  min-width: 0;
  min-height: 44px;
  padding: 8px 9px;
  color: var(--review-text);
  font-size: 0.78rem;
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) - 4px);
}

.find-replace__fields input:focus-visible,
.find-replace__actions button:focus-visible {
  outline: 2px solid #6579e8;
  outline-offset: 2px;
}

.find-replace__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--review-space-3);
  flex-wrap: nowrap;
}

.find-replace__nav {
  display: flex;
  gap: var(--review-space-2);
}

.find-replace__actions button {
  min-height: 44px;
  padding: 9px 11px;
  color: var(--review-accent);
  font-weight: 700;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border: 1px solid transparent;
  border-radius: calc(var(--review-panel-radius) - 3px);
  cursor: pointer;
}

.find-replace__actions > button {
  color: var(--review-text-muted);
  background: var(--review-surface);
  border-color: var(--review-border);
}

.find-replace__actions button:disabled {
  color: #8c93a8;
  cursor: not-allowed;
  background: var(--review-canvas);
}

.find-replace__error {
  margin: 0;
  color: var(--review-danger);
}
</style>
