<script setup lang="ts">
import { computed } from 'vue'

import type { VerificationIssue } from '../../types/verification'

const props = defineProps<{
  issue: VerificationIssue
  selectedSuggestion?: string | null
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:suggestion': [suggestion: string | null]
}>()

const effectiveSuggestion = computed(() =>
  props.selectedSuggestion === undefined
    ? props.issue.suggestion
    : props.selectedSuggestion
)

const alternatives = computed<readonly string[]>(() => {
  const seen = new Set<string>()
  const values: string[] = []
  for (const alternative of props.issue.alternatives ?? []) {
    if (
      alternative === props.issue.suggestion ||
      seen.has(alternative)
    ) {
      continue
    }
    seen.add(alternative)
    values.push(alternative)
  }
  return values
})

const selectableSuggestions = computed<readonly (string | null)[]>(() => {
  const values: (string | null)[] = [props.issue.suggestion]
  for (const alternative of alternatives.value) {
    if (!values.includes(alternative)) {
      values.push(alternative)
    }
  }
  return values
})

function visibleText(text: string): string {
  if (!/^\s+$/u.test(text)) return text
  const names: Record<string, string> = {
    ' ': '空格', '\t': '制表符', '\n': '换行', '\r': '回车',
    '\u00a0': '不换行空格', '\u3000': '全角空格'
  }
  return (text.match(/(\r\n|[\s])\1*/gu) ?? []).map((run) => {
    const character = run.startsWith('\r\n') ? '\r\n' : run[0]
    const name = character === '\r\n' ? '换行' : names[character] ?? '空白字符'
    return `${run.length / character.length} 个${name}`
  }).join(' + ')
}

function suggestionLabel(suggestion: string | null): string {
  if (suggestion === null) {
    return '无自动建议'
  }
  return suggestion === '' ? '（删除）' : visibleText(suggestion)
}

function updateSuggestion(event: Event): void {
  if (event.target instanceof HTMLSelectElement) {
    const selectedIndex = Number(event.target.value)
    const suggestion = selectableSuggestions.value[selectedIndex]
    if (
      Number.isInteger(selectedIndex) &&
      selectedIndex >= 0 &&
      selectedIndex < selectableSuggestions.value.length &&
      suggestion !== undefined
    ) {
      emit('update:suggestion', suggestion)
    }
  }
}
</script>

<template>
  <div class="issue-details">
    <div class="diff">
      <del data-original>{{ visibleText(issue.original) || '（空）' }}</del>
      <span aria-hidden="true">→</span>
      <span data-suggestion>{{ suggestionLabel(effectiveSuggestion) }}</span>
    </div>

    <label v-if="alternatives.length" class="suggestion-picker">
      <span>选择修改建议</span>
      <select
        class="ui-field"
        :value="
          selectableSuggestions.findIndex(
            (suggestion) => suggestion === effectiveSuggestion
          )
        "
        aria-label="选择修改建议"
        :disabled="disabled"
        @change="updateSuggestion"
      >
        <option
          v-for="(suggestion, index) in selectableSuggestions"
          :key="`${index}-${suggestion ?? 'manual'}`"
          :value="index"
        >
          {{ suggestionLabel(suggestion) }}
        </option>
      </select>
    </label>

    <div v-if="alternatives.length" class="alternatives">
      <strong>其他建议</strong>
      <ul>
        <li
          v-for="(alternative, index) in alternatives"
          :key="alternative"
          data-alternative
        >
          <span :data-recommended="index === 0 ? '' : undefined">
            {{ suggestionLabel(alternative) }}
          </span>
          <small v-if="index === 0">推荐</small>
        </li>
      </ul>
    </div>

    <p>{{ issue.description }}</p>
    <blockquote>{{ issue.context }}</blockquote>
    <p v-if="issue.review_reason" class="review-note">
      语义复核：{{ issue.review_reason }}
    </p>
  </div>
</template>

<style scoped>
.diff {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 14px 0;
  padding: 10px 12px;
  border-radius: var(--radius-control);
  background: var(--surface-2);
  font-size: 14px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.diff del {
  color: var(--danger);
}

[data-suggestion] {
  color: var(--success);
}

.suggestion-picker {
  display: grid;
  gap: 6px;
  margin: 8px 0;
  color: var(--muted);
  font-size: 12px;
}

.suggestion-picker select {
  max-width: 100%;
}

.alternatives {
  margin: 10px 0;
  font-size: 12px;
}

.alternatives ul {
  margin: 5px 0 0;
  padding-left: 20px;
}

.alternatives li {
  margin: 3px 0;
}

.alternatives small {
  margin-left: 6px;
  color: var(--primary);
  font-size: 12px;
  font-weight: 500;
}

p {
  margin: 7px 0;
  font-size: 12px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}

blockquote {
  margin: 8px 0;
  padding: 10px 12px;
  border-left: 2px solid var(--border-strong);
  border-radius: 0 6px 6px 0;
  color: var(--muted);
  background: var(--surface-2);
  font-size: 12px;
  line-height: 1.8;
  overflow-wrap: anywhere;
}

.review-note {
  color: var(--primary);
}
</style>
