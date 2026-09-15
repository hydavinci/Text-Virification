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
    <label class="query-field">
      <span>查找</span>
      <input
        class="ui-field"
        v-model="search.query.value"
        data-search-input
        aria-label="查找内容"
        autocomplete="off"
        :disabled="disabled"
        @keydown.enter="navigateSearch"
      />
    </label>
    <label class="replacement-field">
      <span>替换为</span>
      <input
        class="ui-field"
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
        class="ui-button"
        type="button"
        data-action="search-previous"
        :disabled="disabled || search.matches.value.length === 0"
        @click="search.previous"
      >
        上一个
      </button>
      <button
        class="ui-button"
        type="button"
        data-action="search-next"
        :disabled="disabled || search.matches.value.length === 0"
        @click="search.next"
      >
        下一个
      </button>
      <button
        class="ui-button"
        type="button"
        data-action="replace-current"
        :disabled="disabled || search.matches.value.length === 0"
        @click="search.replaceCurrent"
      >
        替换当前
      </button>
      <button
        class="primary ui-button ui-button--primary"
        type="button"
        data-action="replace-all"
        :disabled="disabled || search.matches.value.length === 0"
        @click="search.replaceAll"
      >
        全部替换
      </button>
    </div>
    <button
      class="undo-text-edit ui-button ui-button--quiet"
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
  padding: 8px 12px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: end;
  gap: 6px 12px;
  background: transparent;
}

label {
  min-width: 0;
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 500;
}

input[type='text'],
input:not([type]) {
  min-width: 0;
  width: 100%;
}

.query-field,
.replacement-field {
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
}

.case-sensitive {
  display: flex;
  align-items: center;
  align-self: center;
  gap: 6px;
}
.case-sensitive input { width: 16px; height: 16px; margin: 0; }

.status {
  min-width: 0;
  margin: 0;
  align-self: center;
  color: var(--muted);
  font-size: 12px;
  padding: 0;
  font-variant-numeric: tabular-nums;
}

.actions {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.undo-text-edit {
  grid-column: 1 / -1;
  justify-self: start;
}

.actions button { padding-inline: 8px; white-space: nowrap; }

@container document-search (min-width: 600px) {
  .search-replace-panel {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
    grid-template-areas: "query replacement actions" "case status undo";
  }
  .query-field { grid-area: query; }
  .replacement-field { grid-area: replacement; }
  .case-sensitive { grid-area: case; }
  .status { grid-area: status; }
  .actions { grid-area: actions; flex-wrap: nowrap; }
  .undo-text-edit { grid-area: undo; justify-self: end; }
}

@container document-search (min-width: 900px) {
  .search-replace-panel {
    grid-template-columns: minmax(120px, 1fr) minmax(120px, 1fr) auto auto auto auto;
    grid-template-areas: "query replacement case status actions undo";
    gap: 8px;
  }
  .case-sensitive, .status { white-space: nowrap; }
}
</style>
