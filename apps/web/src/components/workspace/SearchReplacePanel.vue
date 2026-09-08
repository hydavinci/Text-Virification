<script setup lang="ts">
import { toRef, watch } from 'vue'

import {
  useSearchReplace,
  type DocumentSearchState,
  type SearchReplacement
} from '../../composables/useSearchReplace'

const props = defineProps<{
  text: string
  disabled?: boolean
  canUndo?: boolean
}>()

const emit = defineEmits<{
  'undo-text-edit': []
  'search-change': [state: DocumentSearchState]
  'replace-text': [
    text: string,
    kind: SearchReplacement['kind'],
    count: number
  ]
}>()

const search = useSearchReplace({
  text: toRef(props, 'text'),
  onReplace(nextText, action) {
    emit('replace-text', nextText, action.kind, action.count)
  }
})

function navigateSearch(event: KeyboardEvent): void {
  if (props.disabled || event.isComposing) return
  event.preventDefault()
  if (event.shiftKey) search.previous()
  else search.next()
}

watch(
  [() => props.text, search.matches, search.activeMatchIndex],
  ([text, matches, activeMatchIndex]) => {
    emit('search-change', { text, matches, activeMatchIndex })
  },
  { immediate: true }
)
</script>

<template>
  <section class="search-replace-panel" aria-label="查找和替换">
    <label>
      <span>查找</span>
      <input
        v-model="search.query.value"
        data-search-input
        aria-label="查找内容"
        autocomplete="off"
        :disabled="disabled"
        @keydown.enter="navigateSearch"
      />
    </label>
    <label>
      <span>替换为</span>
      <input
        v-model="search.replacement.value"
        data-replacement-input
        aria-label="替换内容"
        autocomplete="off"
        :disabled="disabled"
      />
    </label>
    <label class="case-sensitive">
      <input
        v-model="search.caseSensitive.value"
        data-case-sensitive
        type="checkbox"
        aria-label="区分大小写"
        :disabled="disabled"
      />
      <span>区分大小写</span>
    </label>

    <p
      class="status"
      data-search-status
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      {{ search.statusText.value }}
    </p>

    <div class="actions">
      <button
        type="button"
        data-action="search-previous"
        :disabled="disabled || search.matches.value.length === 0"
        @click="search.previous"
      >
        上一个
      </button>
      <button
        type="button"
        data-action="search-next"
        :disabled="disabled || search.matches.value.length === 0"
        @click="search.next"
      >
        下一个
      </button>
      <button
        type="button"
        data-action="replace-current"
        :disabled="disabled || search.matches.value.length === 0"
        @click="search.replaceCurrent"
      >
        替换当前
      </button>
      <button
        class="primary"
        type="button"
        data-action="replace-all"
        :disabled="disabled || search.matches.value.length === 0"
        @click="search.replaceAll"
      >
        全部替换
      </button>
    </div>
    <button
      class="undo-text-edit"
      type="button"
      data-action="undo-text-edit"
      title="撤销上一次替换或已保存的原文编辑"
      :disabled="disabled || !canUndo"
      @click="emit('undo-text-edit')"
    >
      撤销修改
    </button>
  </section>
</template>

<style scoped>
.search-replace-panel {
  padding: 12px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: end;
  gap: 10px;
  background: var(--surface);
}

label {
  min-width: 0;
  display: grid;
  gap: 4px;
  color: var(--muted);
  font-size: 11px;
}

input[type='text'],
input:not([type]) {
  min-width: 0;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 9px;
  color: var(--text);
  background: var(--surface-2);
}

.case-sensitive {
  display: flex;
  align-items: center;
  align-self: center;
  gap: 6px;
}

.status {
  min-width: 0;
  margin: 0;
  align-self: center;
  color: var(--muted);
  font-size: 12px;
}

.actions {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  align-items: center;
  gap: 6px;
}

.undo-text-edit {
  grid-column: 1 / -1;
}

button {
  padding: 7px 2px;
  border: 1px solid var(--border);
  border-radius: 9px;
  color: var(--text);
  background: var(--surface);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
}

button.primary {
  border-color: transparent;
  color: white;
  background: linear-gradient(135deg, var(--primary), var(--primary-2));
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

button:focus-visible,
input:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--primary) 35%, transparent);
  outline-offset: 2px;
}
</style>
